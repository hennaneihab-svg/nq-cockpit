"""Sauvegarde quotidienne transactionnelle et rétention de la base SQLite (P10).

Utilise l'API de backup en ligne sqlite3 (Connection.backup) pour garantir
une copie cohérente même en présence d'écritures WAL concurrentes.
Effectue une vérification d'intégrité (PRAGMA integrity_check) avant
l'écrasement idempotent et la purge de rétention.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig, load_config

logger = logging.getLogger(__name__)

BACKUP_FILENAME_REGEX = re.compile(r"^nqcockpit_(\d{4}-\d{2}-\d{2})\.db$")


@dataclass
class BackupResult:
    """Résultat d'une opération de sauvegarde du journal SQLite."""

    status: str  # "OK" ou "DEGRADED"
    backup_path: Path
    file_size_bytes: int
    integrity_result: str  # "ok" ou description de l'échec
    is_idempotent_overwrite: bool  # True si une sauvegarde existait déjà pour ce jour
    deleted_old_backups: list[Path] = field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status == "OK"


def create_journal_backup(
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    retention_days: int | None = None,
    target_date: Optional[date] = None,
    config: Optional[AppConfig] = None,
) -> BackupResult:
    """Exécute une sauvegarde transactionnelle sûre avec vérification d'intégrité et rétention.

    Args:
        db_path: Chemin vers la base SQLite source (défaut : config.data.db_path).
        backup_dir: Dossier de destination (défaut : config.data.backup_dir).
        retention_days: Nombre de jours de rétention (défaut : config.data.backup_retention_days).
        target_date: Date ciblée pour le nom de sauvegarde
            (défaut : date du jour en Africa/Algiers).
        config: Configuration globale (défaut : load_config()).

    Returns:
        BackupResult contenant les détails de la sauvegarde et l'état d'intégrité.
    """
    if config is None:
        config = load_config()

    # Résolution des paramètres
    source_db_path = Path(db_path if db_path is not None else config.data.db_path)
    target_backup_dir = Path(
        backup_dir if backup_dir is not None else config.data.backup_dir
    )
    retention = (
        int(retention_days)
        if retention_days is not None
        else config.data.backup_retention_days
    )
    if retention < 1:
        raise ValueError("retention_days doit être supérieur ou égal à 1.")

    if target_date is None:
        tz = ZoneInfo(config.timezones.display)
        target_date = datetime.now(tz).date()

    filename = f"nqcockpit_{target_date.isoformat()}.db"
    final_backup_path = (target_backup_dir / filename).resolve()

    # Vérification d'existence de la base source
    if not source_db_path.is_file():
        logger.error("Base de données source introuvable : %s", source_db_path)
        return BackupResult(
            status="DEGRADED",
            backup_path=final_backup_path,
            file_size_bytes=0,
            integrity_result="source_missing",
            is_idempotent_overwrite=False,
            deleted_old_backups=[],
            error_message=f"Base de données source introuvable : {source_db_path}",
        )

    target_backup_dir.mkdir(parents=True, exist_ok=True)
    temp_backup_path = target_backup_dir / f".tmp_{filename}_{uuid.uuid4().hex[:8]}.db"

    # 1. Copie transactionnelle via l'API sqlite3 backup
    try:
        src_conn = sqlite3.connect(str(source_db_path))
        try:
            # Checkpoint WAL passif si mode WAL actif
            src_conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        except sqlite3.Error:
            pass

        dest_conn = sqlite3.connect(str(temp_backup_path))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
            src_conn.close()
    except Exception as exc:
        logger.error("Erreur durant la copie transactionnelle SQLite : %s", exc)
        if temp_backup_path.exists():
            try:
                temp_backup_path.unlink()
            except OSError:
                pass
        return BackupResult(
            status="DEGRADED",
            backup_path=final_backup_path,
            file_size_bytes=0,
            integrity_result="backup_exception",
            is_idempotent_overwrite=False,
            deleted_old_backups=[],
            error_message=f"Échec de la sauvegarde transactionnelle : {exc}",
        )

    # 2. Vérification d'intégrité post-sauvegarde (PRAGMA integrity_check)
    try:
        chk_conn = sqlite3.connect(str(temp_backup_path))
        try:
            cur = chk_conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            rows = cur.fetchall()
        finally:
            chk_conn.close()
    except Exception as exc:
        logger.error("Erreur durant la vérification d'intégrité : %s", exc)
        if temp_backup_path.exists():
            try:
                temp_backup_path.unlink()
            except OSError:
                pass
        return BackupResult(
            status="DEGRADED",
            backup_path=final_backup_path,
            file_size_bytes=0,
            integrity_result="integrity_check_error",
            is_idempotent_overwrite=False,
            deleted_old_backups=[],
            error_message=f"Erreur d'accès lors de la vérification d'intégrité : {exc}",
        )

    if not (len(rows) == 1 and str(rows[0][0]).strip().lower() == "ok"):
        err_details = "; ".join(str(r[0]) for r in rows)
        logger.error("Échec d'intégrité SQLite sur la sauvegarde : %s", err_details)
        if temp_backup_path.exists():
            try:
                temp_backup_path.unlink()
            except OSError:
                pass
        # En cas d'intégrité invalide, JAMAIS de purge des anciennes sauvegardes
        return BackupResult(
            status="DEGRADED",
            backup_path=final_backup_path,
            file_size_bytes=0,
            integrity_result=f"failed: {err_details}",
            is_idempotent_overwrite=False,
            deleted_old_backups=[],
            error_message=f"Échec du test PRAGMA integrity_check : {err_details}",
        )

    # 3. Validation et remplacement idempotent atomique
    was_existing = final_backup_path.exists()
    try:
        os.replace(temp_backup_path, final_backup_path)
    except OSError as exc:
        logger.error("Impossible de déplacer le fichier temporaire : %s", exc)
        if temp_backup_path.exists():
            try:
                temp_backup_path.unlink()
            except OSError:
                pass
        return BackupResult(
            status="DEGRADED",
            backup_path=final_backup_path,
            file_size_bytes=0,
            integrity_result="replace_error",
            is_idempotent_overwrite=was_existing,
            deleted_old_backups=[],
            error_message=f"Échec du remplacement atomique du fichier : {exc}",
        )

    file_size_bytes = final_backup_path.stat().st_size

    # 4. Politique de rétention : suppression des sauvegardes strictement plus anciennes
    deleted_old: list[Path] = []
    cutoff_date = target_date - timedelta(days=retention)

    try:
        for f in sorted(target_backup_dir.glob("nqcockpit_*.db")):
            if f.resolve() == final_backup_path:
                continue
            m = BACKUP_FILENAME_REGEX.match(f.name)
            if m:
                try:
                    f_date = date.fromisoformat(m.group(1))
                    if f_date < cutoff_date:
                        f.unlink()
                        deleted_old.append(f)
                        logger.info("Purge de rétention : sauvegarde supprimée %s", f.name)
                except ValueError:
                    continue
    except Exception as exc:
        logger.warning("Avertissement lors de la purge de rétention : %s", exc)

    return BackupResult(
        status="OK",
        backup_path=final_backup_path,
        file_size_bytes=file_size_bytes,
        integrity_result="ok",
        is_idempotent_overwrite=was_existing,
        deleted_old_backups=deleted_old,
        error_message=None,
    )
