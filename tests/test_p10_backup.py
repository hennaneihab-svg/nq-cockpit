"""Tests pour la sauvegarde quotidienne et la rétention de la base SQLite (P10 élément 3/3).

Vérifie :
1. Sauvegarde transactionnelle valide avec vérification d'intégrité OK.
2. Idempotence : mise à jour sécurisée si la sauvegarde du jour existe déjà.
3. Politique de rétention : suppression automatique des sauvegardes strictement plus anciennes.
4. Échec d'intégrité : détection d'état dégradé, non-écrasement
   et non-suppression des anciennes sauvegardes.
5. Base source manquante : signalement en état dégradé propre.
6. Commande CLI : intégration console et codes de retour.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from nqcockpit.journal.backup import create_journal_backup
from nqcockpit.journal.models import TradeDirection, TradeEntry
from nqcockpit.journal.store import init_journal_db, load_trades, save_trade


@pytest.fixture()
def sample_db(tmp_path: Path) -> Path:
    """Crée une base SQLite temporaire contenant un trade de test."""
    db_file = tmp_path / "journal_src.db"
    conn = init_journal_db(db_file)
    t = TradeEntry(
        trade_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        session_date="2026-09-30",
        instrument="MNQ",
        direction=TradeDirection.LONG,
        entry_price=20800.0,
        stop_price=20750.0,
        exit_price=20900.0,
        r_realized=2.0,
    )
    save_trade(conn, t)
    conn.close()
    return db_file


def test_backup_valid_integrity_ok(sample_db: Path, tmp_path: Path):
    """Sauvegarde transactionnelle valide avec vérification d'intégrité PRAGMA integrity_check."""
    backup_dir = tmp_path / "backups"
    target_d = date(2026, 9, 30)

    res = create_journal_backup(
        db_path=sample_db,
        backup_dir=backup_dir,
        retention_days=30,
        target_date=target_d,
    )

    assert res.is_success is True
    assert res.status == "OK"
    assert res.integrity_result == "ok"
    assert res.is_idempotent_overwrite is False
    assert res.backup_path.is_file()
    assert res.backup_path.name == "nqcockpit_2026-09-30.db"
    assert res.file_size_bytes > 0
    assert len(res.deleted_old_backups) == 0

    # Vérification du contenu dans la base de sauvegarde
    dest_conn = sqlite3.connect(str(res.backup_path))
    cur = dest_conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    assert cur.fetchall() == [("ok",)]
    trades = load_trades(dest_conn)
    assert len(trades) == 1
    assert trades[0].session_date == "2026-09-30"
    dest_conn.close()


def test_backup_idempotent_overwrite(sample_db: Path, tmp_path: Path):
    """Mise à jour idempotente d'une sauvegarde existante du jour sans perte de données."""
    backup_dir = tmp_path / "backups"
    target_d = date(2026, 9, 30)

    # 1ère sauvegarde
    res1 = create_journal_backup(
        db_path=sample_db,
        backup_dir=backup_dir,
        retention_days=30,
        target_date=target_d,
    )
    assert res1.is_success is True
    assert res1.is_idempotent_overwrite is False

    # Ajout d'un 2e trade dans la source
    conn = init_journal_db(sample_db)
    t2 = TradeEntry(
        trade_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        session_date="2026-09-30",
        instrument="NQ",
        direction=TradeDirection.SHORT,
        entry_price=20900.0,
        stop_price=20950.0,
        exit_price=20850.0,
        r_realized=1.0,
    )
    save_trade(conn, t2)
    conn.close()

    # 2e sauvegarde le même jour
    res2 = create_journal_backup(
        db_path=sample_db,
        backup_dir=backup_dir,
        retention_days=30,
        target_date=target_d,
    )
    assert res2.is_success is True
    assert res2.is_idempotent_overwrite is True
    assert res2.backup_path == res1.backup_path

    # Vérification que le fichier de sauvegarde contient désormais les 2 trades
    dest_conn = sqlite3.connect(str(res2.backup_path))
    trades = load_trades(dest_conn)
    assert len(trades) == 2
    dest_conn.close()


def test_backup_retention_policy_prunes_strictly_older(sample_db: Path, tmp_path: Path):
    """La rétention supprime les sauvegardes strictement plus anciennes que cutoff_date."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Création de sauvegardes simulées :
    # target_date = 2026-09-30, retention = 30 jours -> cutoff_date = 2026-08-31
    old_file_1 = backup_dir / "nqcockpit_2026-08-01.db"  # > 30j -> doit être supprimé
    old_file_2 = backup_dir / "nqcockpit_2026-08-20.db"  # > 30j -> doit être supprimé
    recent_file_1 = backup_dir / "nqcockpit_2026-09-10.db"  # 20j -> doit être conservé
    recent_file_2 = backup_dir / "nqcockpit_2026-09-29.db"  # 1j -> doit être conservé
    non_backup_file = backup_dir / "notes.txt"  # autre fichier -> doit être conservé

    for f in [old_file_1, old_file_2, recent_file_1, recent_file_2]:
        f.write_bytes(b"SQLite format 3\x00")
    non_backup_file.write_text("ne pas toucher", encoding="utf-8")

    res = create_journal_backup(
        db_path=sample_db,
        backup_dir=backup_dir,
        retention_days=30,
        target_date=date(2026, 9, 30),
    )

    assert res.is_success is True
    deleted_names = [p.name for p in res.deleted_old_backups]
    assert "nqcockpit_2026-08-01.db" in deleted_names
    assert "nqcockpit_2026-08-20.db" in deleted_names
    assert len(res.deleted_old_backups) == 2

    # Vérification sur disque
    assert old_file_1.exists() is False
    assert old_file_2.exists() is False
    assert recent_file_1.exists() is True
    assert recent_file_2.exists() is True
    assert non_backup_file.exists() is True


def test_backup_integrity_failure_degraded_and_no_prune(tmp_path: Path):
    """En cas d'échec d'intégrité, statut DÉGRADÉ, pas de remplacement ni de purge."""
    source_corrupt = tmp_path / "corrupt.db"
    # Écriture d'un en-tête SQLite valide suivi d'octets corrompus
    # pour forcer l'échec de PRAGMA integrity_check
    header = b"SQLite format 3\x00" + b"\x00" * 84 + b"\x01\x00\x00\x00"
    source_corrupt.write_bytes(header + b"\xff" * 500)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Sauvegarde ancienne qui ne doit SURTOUT PAS être supprimée
    old_backup = backup_dir / "nqcockpit_2026-07-01.db"
    old_backup.write_bytes(b"ancienne sauvegarde vitale")

    # Sauvegarde du jour existante qui ne doit SURTOUT PAS être écrasée
    current_backup = backup_dir / "nqcockpit_2026-09-30.db"
    current_backup.write_bytes(b"bonne sauvegarde du matin")

    res = create_journal_backup(
        db_path=source_corrupt,
        backup_dir=backup_dir,
        retention_days=30,
        target_date=date(2026, 9, 30),
    )

    assert res.is_success is False
    assert res.status == "DEGRADED"
    assert res.integrity_result != "ok"
    assert len(res.deleted_old_backups) == 0

    # Les fichiers précédents doivent rester intacts
    assert old_backup.exists() is True
    assert old_backup.read_bytes() == b"ancienne sauvegarde vitale"
    assert current_backup.exists() is True
    assert current_backup.read_bytes() == b"bonne sauvegarde du matin"


def test_backup_source_missing_degraded(tmp_path: Path):
    """Base source inexistante -> statut DÉGRADÉ sans exception non gérée."""
    missing_source = tmp_path / "nonexistent.db"
    backup_dir = tmp_path / "backups"

    res = create_journal_backup(
        db_path=missing_source,
        backup_dir=backup_dir,
        retention_days=30,
        target_date=date(2026, 9, 30),
    )

    assert res.is_success is False
    assert res.status == "DEGRADED"
    assert res.integrity_result == "source_missing"
    assert "introuvable" in (res.error_message or "").lower()


def test_backup_cli_success(sample_db: Path, tmp_path: Path, monkeypatch, capsys):
    """Exécution CLI nqcockpit journal backup en cas de succès."""
    backup_dir = tmp_path / "cli_backups"
    monkeypatch.setenv("NQ_DATA_DB_PATH", str(sample_db))
    monkeypatch.setenv("NQ_DATA_BACKUP_DIR", str(backup_dir))

    from nqcockpit.cli import main

    code = main(["journal", "backup"])
    assert code == 0

    out = capsys.readouterr().out
    assert "SAUVEGARDE DU JOURNAL SQLITE" in out
    assert "✅ OK (Sauvegarde réussie)" in out
    assert "PRAGMA integrity_check validé" in out
    assert str(backup_dir) in out


def test_backup_cli_degraded(tmp_path: Path, monkeypatch, capsys):
    """Exécution CLI nqcockpit journal backup avec base introuvable -> exit code 1."""
    missing_db = tmp_path / "cli_missing.db"
    backup_dir = tmp_path / "cli_backups"
    monkeypatch.setenv("NQ_DATA_DB_PATH", str(missing_db))
    monkeypatch.setenv("NQ_DATA_BACKUP_DIR", str(backup_dir))

    from nqcockpit.cli import main

    code = main(["journal", "backup"])
    assert code == 1

    out = capsys.readouterr().out
    assert "DÉGRADÉ" in out
    assert "Base de données source introuvable" in out
