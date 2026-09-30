"""Persistance SQLite du journal de trades (P09).

Table `trades` : une ligne par trade enregistré.
Toutes les requêtes sont paramétrées (pas d'injection SQL possible).
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from nqcockpit.journal.models import (
    GammaRegime,
    TradeDirection,
    TradeEntry,
    TradeOutcome,
    VolRegime,
)

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id            TEXT PRIMARY KEY,
    recorded_at         TEXT NOT NULL,
    session_date        TEXT NOT NULL,
    instrument          TEXT NOT NULL DEFAULT 'MNQ',
    direction           TEXT NOT NULL DEFAULT 'NONE',
    entry_price         REAL NOT NULL DEFAULT 0,
    stop_price          REAL NOT NULL DEFAULT 0,
    tp1_price           REAL,
    tp2_price           REAL,
    exit_price          REAL NOT NULL DEFAULT 0,
    exit_reason         TEXT NOT NULL DEFAULT '',
    r_realized          REAL NOT NULL DEFAULT 0,
    fees_points         REAL NOT NULL DEFAULT 0,
    outcome             TEXT NOT NULL DEFAULT 'BREAKEVEN',
    window_name         TEXT NOT NULL DEFAULT '',
    entry_time_ny       TEXT,
    exit_time_ny        TEXT,
    minutes_after_last_sl REAL,
    event_risk_label    TEXT NOT NULL DEFAULT '',
    gamma_regime        TEXT NOT NULL DEFAULT 'inconnu',
    vol_regime          TEXT NOT NULL DEFAULT 'inconnu',
    distance_flip_pts   REAL,
    distance_wall_pts   REAL,
    day_of_week         INTEGER NOT NULL DEFAULT -1,
    sl_moved            INTEGER NOT NULL DEFAULT 0,
    early_exit          INTEGER NOT NULL DEFAULT 0,
    risk_pct_used       REAL NOT NULL DEFAULT 0,
    setup_tag           TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT '',
    screenshot_path     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_date);
CREATE INDEX IF NOT EXISTS idx_trades_recorded ON trades(recorded_at);
"""


def init_journal_db(db_path: str | Path) -> sqlite3.Connection:
    """Ouvre (ou crée) la base et initialise le schéma journal."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")

    # Migration si table legacy existante sans 'session_date'
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    if cols and "session_date" not in cols:
        row_count = conn.execute("SELECT count(*) FROM trades").fetchone()[0]
        if row_count == 0:
            conn.execute("DROP TABLE trades")
            conn.commit()

    conn.executescript(_DDL)
    conn.commit()
    logger.debug("journal DB initialisée : %s", path)
    return conn


def save_trade(conn: sqlite3.Connection, trade: TradeEntry) -> str:
    """Insère ou remplace un trade. Retourne le trade_id."""
    if not trade.trade_id:
        trade.trade_id = str(uuid.uuid4())

    conn.execute(
        """
        INSERT OR REPLACE INTO trades (
            trade_id, recorded_at, session_date, instrument, direction,
            entry_price, stop_price, tp1_price, tp2_price,
            exit_price, exit_reason, r_realized, fees_points, outcome,
            window_name, entry_time_ny, exit_time_ny, minutes_after_last_sl,
            event_risk_label, gamma_regime, vol_regime,
            distance_flip_pts, distance_wall_pts, day_of_week,
            sl_moved, early_exit, risk_pct_used,
            setup_tag, notes, screenshot_path
        ) VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        (
            trade.trade_id,
            trade.recorded_at.isoformat(),
            trade.session_date,
            trade.instrument,
            trade.direction.value,
            trade.entry_price,
            trade.stop_price,
            trade.tp1_price,
            trade.tp2_price,
            trade.exit_price,
            trade.exit_reason,
            trade.r_realized,
            trade.fees_points,
            trade.outcome.value,
            trade.window_name,
            trade.entry_time_ny.isoformat() if trade.entry_time_ny else None,
            trade.exit_time_ny.isoformat() if trade.exit_time_ny else None,
            trade.minutes_after_last_sl,
            trade.event_risk_label,
            trade.gamma_regime.value,
            trade.vol_regime.value,
            trade.distance_flip_pts,
            trade.distance_wall_pts,
            trade.day_of_week,
            int(trade.sl_moved),
            int(trade.early_exit),
            trade.risk_pct_used,
            trade.setup_tag,
            trade.notes,
            trade.screenshot_path,
        ),
    )
    conn.commit()
    logger.info("trade sauvegardé : %s (%s)", trade.trade_id, trade.session_date)
    return trade.trade_id


def load_trades(
    conn: sqlite3.Connection,
    session_date: Optional[str] = None,
    limit: int = 0,
) -> list[TradeEntry]:
    """Charge les trades depuis la DB (tous ou filtrés par date)."""
    if session_date:
        rows = conn.execute(
            "SELECT * FROM trades WHERE session_date=? ORDER BY recorded_at",
            (session_date,),
        ).fetchall()
    else:
        sql = "SELECT * FROM trades ORDER BY recorded_at"
        if limit > 0:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql).fetchall()

    cols = [d[0] for d in conn.execute("SELECT * FROM trades LIMIT 0").description or []]
    if not cols:
        cols = _column_names()

    result = []
    for row in rows:
        d = dict(zip(cols, row))
        try:
            t = _row_to_trade(d)
            result.append(t)
        except Exception as exc:  # noqa: BLE001
            logger.warning("trade ignoré (lecture échouée) : %s — %s", d.get("trade_id"), exc)
    return result


def delete_trade(conn: sqlite3.Connection, trade_id: str) -> int:
    """Supprime un trade. Retourne le nombre de lignes supprimées."""
    cur = conn.execute("DELETE FROM trades WHERE trade_id=?", (trade_id,))
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _column_names() -> list[str]:
    return [
        "trade_id", "recorded_at", "session_date", "instrument", "direction",
        "entry_price", "stop_price", "tp1_price", "tp2_price",
        "exit_price", "exit_reason", "r_realized", "fees_points", "outcome",
        "window_name", "entry_time_ny", "exit_time_ny", "minutes_after_last_sl",
        "event_risk_label", "gamma_regime", "vol_regime",
        "distance_flip_pts", "distance_wall_pts", "day_of_week",
        "sl_moved", "early_exit", "risk_pct_used",
        "setup_tag", "notes", "screenshot_path",
    ]


def _row_to_trade(d: dict) -> TradeEntry:
    def _dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        return datetime.fromisoformat(s)

    t = TradeEntry(
        trade_id=d["trade_id"],
        recorded_at=datetime.fromisoformat(d["recorded_at"]),
        session_date=d["session_date"],
        instrument=d.get("instrument", "MNQ"),
        direction=TradeDirection(d.get("direction", "NONE")),
        entry_price=float(d.get("entry_price", 0)),
        stop_price=float(d.get("stop_price", 0)),
        tp1_price=d.get("tp1_price"),
        tp2_price=d.get("tp2_price"),
        exit_price=float(d.get("exit_price", 0)),
        exit_reason=d.get("exit_reason", ""),
        r_realized=float(d.get("r_realized", 0)),
        fees_points=float(d.get("fees_points", 0)),
        outcome=TradeOutcome(d.get("outcome", "BREAKEVEN")),
        window_name=d.get("window_name", ""),
        entry_time_ny=_dt(d.get("entry_time_ny")),
        exit_time_ny=_dt(d.get("exit_time_ny")),
        minutes_after_last_sl=d.get("minutes_after_last_sl"),
        event_risk_label=d.get("event_risk_label", ""),
        gamma_regime=GammaRegime(d.get("gamma_regime", "inconnu")),
        vol_regime=VolRegime(d.get("vol_regime", "inconnu")),
        distance_flip_pts=d.get("distance_flip_pts"),
        distance_wall_pts=d.get("distance_wall_pts"),
        day_of_week=int(d.get("day_of_week", -1)),
        sl_moved=bool(int(d.get("sl_moved", 0))),
        early_exit=bool(int(d.get("early_exit", 0))),
        risk_pct_used=float(d.get("risk_pct_used", 0)),
        setup_tag=d.get("setup_tag", ""),
        notes=d.get("notes", ""),
        screenshot_path=d.get("screenshot_path", ""),
    )
    return t
