"""Planificateur et comparateur de snapshots de niveaux (APScheduler)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from nqcockpit.config import load_config
from nqcockpit.data.cboe import fetch_cboe_options_chain
from nqcockpit.data.db import get_bars, get_db_connection
from nqcockpit.levels.engine import LevelsEngine
from nqcockpit.levels.models import LevelsSnapshot

log = logging.getLogger(__name__)

ALGIERS_TZ = ZoneInfo("Africa/Algiers")


@dataclass
class LevelMovement:
    """Mouvement constaté entre deux snapshots successifs."""

    metric: str
    prev_val: float | None
    new_val: float | None
    delta: float | None
    status: str  # "STABLE", "MIGRATION_HAUSSIERE", "MIGRATION_BAISSIERE"


def compare_snapshots(
    prev_snap: LevelsSnapshot,
    new_snap: LevelsSnapshot,
) -> list[LevelMovement]:
    """Compare deux snapshots successifs et détecte le déplacement des niveaux structuraux."""
    metrics_to_check = [
        ("Spot NDX", prev_snap.spot_ndx, new_snap.spot_ndx),
        ("Spot NQ", prev_snap.spot_nq, new_snap.spot_nq),
        ("Call Wall NDX", prev_snap.call_wall_ndx, new_snap.call_wall_ndx),
        ("Call Wall NQ", prev_snap.call_wall_nq, new_snap.call_wall_nq),
        ("Put Wall NDX", prev_snap.put_wall_ndx, new_snap.put_wall_ndx),
        ("Put Wall NQ", prev_snap.put_wall_nq, new_snap.put_wall_nq),
        ("Gamma Flip NDX", prev_snap.gamma_flip_ndx, new_snap.gamma_flip_ndx),
        ("Gamma Flip NQ", prev_snap.gamma_flip_nq, new_snap.gamma_flip_nq),
        ("Base NQ/NDX", prev_snap.basis, new_snap.basis),
    ]

    movements: list[LevelMovement] = []
    for name, p_val, n_val in metrics_to_check:
        if p_val is None or n_val is None:
            movements.append(
                LevelMovement(
                    metric=name,
                    prev_val=p_val,
                    new_val=n_val,
                    delta=None,
                    status="NON_DISPONIBLE",
                )
            )
            continue

        delta = n_val - p_val
        if abs(delta) < 1e-4:
            status = "STABLE"
        elif delta > 0:
            status = "MIGRATION_HAUSSIERE"
        else:
            status = "MIGRATION_BAISSIERE"

        movements.append(
            LevelMovement(
                metric=name,
                prev_val=p_val,
                new_val=n_val,
                delta=delta,
                status=status,
            )
        )

    return movements


class LevelsScheduler:
    """Planifie et exécute les calculs de niveaux selon les heures configurées (heure d'Alger)."""

    def __init__(self, engine: LevelsEngine | None = None) -> None:
        self.engine = engine or LevelsEngine()
        self.scheduler = BackgroundScheduler(timezone=ALGIERS_TZ)
        self.last_snapshot: LevelsSnapshot | None = None

    def trigger_snapshot(self) -> LevelsSnapshot:
        """Déclenche manuellement un snapshot complet."""
        log.info("Déclenchement du snapshot de niveaux...")
        chain = fetch_cboe_options_chain()

        conn = get_db_connection()
        nq_bars = get_bars(conn, "NQ=F", "1m", limit=500)
        ndx_bars = get_bars(conn, "^NDX", "1m", limit=500)
        conn.close()

        snap = self.engine.compute_snapshot(
            chain=chain,
            nq_bars=nq_bars,
            ndx_bars=ndx_bars,
            now_utc=datetime.now(timezone.utc),
        )

        if self.last_snapshot is not None:
            moves = compare_snapshots(self.last_snapshot, snap)
            for m in moves:
                if m.status != "STABLE":
                    log.info(
                        "Déplacement détecté sur %s : %+0.1f pts (%s)",
                        m.metric,
                        m.delta or 0,
                        m.status,
                    )

        self.last_snapshot = snap
        return snap

    def start(self) -> None:
        """Démarre le planificateur selon la configuration."""
        cfg = load_config()
        times_algiers = cfg.snapshots_algiers

        for t_str in times_algiers:
            parts = t_str.strip().split(":")
            if len(parts) == 2:
                hour = int(parts[0])
                minute = int(parts[1])
                self.scheduler.add_job(
                    self.trigger_snapshot,
                    "cron",
                    hour=hour,
                    minute=minute,
                    day_of_week="mon-fri",
                    id=f"snap_{hour:02d}_{minute:02d}",
                )
                log.info("Snapshot planifié à %02d:%02d (heure d'Alger)", hour, minute)

        self.scheduler.start()

    def stop(self) -> None:
        """Arrête le planificateur."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
