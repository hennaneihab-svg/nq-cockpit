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
    """Planifie et exécute les calculs de niveaux selon les heures de séance US.

    Exprimé en fuseau horaire America/New_York.
    """

    def __init__(self, engine: LevelsEngine | None = None) -> None:
        self.engine = engine or LevelsEngine()
        self.scheduler = BackgroundScheduler(timezone=ZoneInfo("America/New_York"))
        self.last_snapshot: LevelsSnapshot | None = None

    def trigger_snapshot(self) -> LevelsSnapshot:
        """Déclenche manuellement un snapshot complet."""
        log.info("Déclenchement du snapshot de niveaux...")
        chain = fetch_cboe_options_chain()

        conn = get_db_connection()
        nq_bars = get_bars(conn, "NQ=F", "1m", limit=500)
        ndx_bars = get_bars(conn, "^NDX", "1m", limit=500)

        if not nq_bars or not ndx_bars:
            try:
                from nqcockpit.data.db import insert_bars
                from nqcockpit.data.fetcher import DataFetcher

                now_utc = datetime.now(timezone.utc)
                f_live = DataFetcher()
                if not nq_bars:
                    res_nq = f_live.fetch_yahoo_bars("NQ=F", interval="1m", period="1d")
                    if res_nq.bars:
                        insert_bars(conn, res_nq.bars, "NQ=F", "1m", "yahoo", now_utc)
                        nq_bars = res_nq.bars
                if not ndx_bars:
                    res_ndx = f_live.fetch_yahoo_bars("^NDX", interval="1m", period="1d")
                    if res_ndx.bars:
                        insert_bars(conn, res_ndx.bars, "^NDX", "1m", "yahoo", now_utc)
                        ndx_bars = res_ndx.bars
            except Exception as exc:
                log.warning(
                    "Échec actualisation live des barres NQ/NDX dans trigger_snapshot: %s", exc
                )

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
        """Démarre le planificateur selon la configuration en America/New_York."""
        cfg = load_config()
        times_ny = getattr(cfg, "snapshots_ny", None) or ["08:00", "09:45", "15:45"]

        for t_str in times_ny:
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
                    id=f"snap_ny_{hour:02d}_{minute:02d}",
                )
                log.info("Snapshot planifié à %02d:%02d (America/New_York)", hour, minute)

        self.scheduler.start()

    def stop(self) -> None:
        """Arrête le planificateur."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
