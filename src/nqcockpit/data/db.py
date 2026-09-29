"""Gestionnaire de base de données SQLite pour NQ Cockpit."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nqcockpit.data.models import Bar, DataStatus

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/nqcockpit.db")

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "initial_schema",
        [
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS bars (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL DEFAULT 0.0,
                source TEXT NOT NULL,
                fetched_at_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (symbol, interval, timestamp_utc)
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_bars_symbol_time
            ON bars (symbol, timestamp_utc);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_bars_symbol_interval_time
            ON bars (symbol, interval, timestamp_utc);
            """,
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc TEXT NOT NULL,
                spot REAL,
                regime TEXT,
                gamma_flip REAL,
                call_wall REAL,
                put_support REAL,
                expected_move REAL,
                basis REAL,
                synthetic_basis REAL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT,
                created_at_utc TEXT NOT NULL
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_snapshots_time
            ON snapshots (timestamp_utc);
            """,
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                timestamp_utc TEXT NOT NULL,
                name TEXT NOT NULL,
                currency TEXT NOT NULL,
                impact TEXT NOT NULL,
                actual TEXT,
                forecast TEXT,
                previous TEXT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_events_time
            ON events (timestamp_utc);
            """,
            """
            CREATE TABLE IF NOT EXISTS event_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                pre_price REAL,
                post_5m_price REAL,
                post_15m_price REAL,
                post_60m_price REAL,
                max_favorable REAL,
                max_adverse REAL,
                recorded_at_utc TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events (event_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE NOT NULL,
                timestamp_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                pnl REAL NOT NULL,
                r_multiple REAL NOT NULL,
                setup TEXT,
                rules_respected INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_at_utc TEXT NOT NULL
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trades_time
            ON trades (timestamp_utc);
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                market_regime TEXT,
                bias TEXT,
                key_levels_json TEXT,
                notes TEXT,
                updated_at_utc TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                forecast_id TEXT UNIQUE NOT NULL,
                timestamp_utc TEXT NOT NULL,
                target_date TEXT NOT NULL,
                predicted_range_low REAL,
                predicted_range_high REAL,
                actual_low REAL,
                actual_high REAL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_forecasts_target
            ON forecasts (target_date);
            """,
        ],
    ),
]


def get_db_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Ouvre une connexion SQLite avec WAL, foreign keys et row_factory activés."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    is_memory = str(db_path) == ":memory:"

    if not is_memory:
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        conn.execute("PRAGMA journal_mode = WAL;")
    else:
        conn = sqlite3.connect(":memory:")

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn


def get_applied_migrations(conn: sqlite3.Connection) -> set[int]:
    """Retourne l'ensemble des versions de migration déjà appliquées."""
    try:
        cur = conn.execute("SELECT version FROM schema_version")
        return {row[0] for row in cur.fetchall()}
    except sqlite3.OperationalError:
        return set()


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Applique toutes les migrations manquantes dans l'ordre croissant."""
    applied = get_applied_migrations(conn)
    applied_count = 0

    for version, name, statements in sorted(MIGRATIONS, key=lambda m: m[0]):
        if version in applied:
            continue
        log.info("Application de la migration %d (%s)...", version, name)
        with conn:
            for stmt in statements:
                conn.execute(stmt)
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, now_iso),
            )
        applied_count += 1

    return applied_count


def insert_bars(
    conn: sqlite3.Connection,
    bars: list[Bar],
    symbol: str,
    interval: str,
    source: str,
    fetched_at_utc: datetime,
    status: DataStatus | str = DataStatus.OK,
) -> int:
    """Insère ou remplace les barres OHLCV sans doublons.

    Retourne le nombre de barres enregistrées.
    """
    if not bars:
        return 0

    status_str = status.value if isinstance(status, DataStatus) else str(status)
    fetched_iso = fetched_at_utc.isoformat()

    records = [
        (
            symbol,
            interval,
            b.timestamp_utc.isoformat(),
            float(b.open),
            float(b.high),
            float(b.low),
            float(b.close),
            float(b.volume),
            source,
            fetched_iso,
            status_str,
        )
        for b in bars
    ]

    sql = """
    INSERT OR REPLACE INTO bars (
        symbol, interval, timestamp_utc, open, high, low, close, volume,
        source, fetched_at_utc, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with conn:
        conn.executemany(sql, records)

    return len(records)


def get_bars(
    conn: sqlite3.Connection,
    symbol: str,
    interval: str = "1m",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 5000,
) -> list[Bar]:
    """Récupère les barres ordonnées chronologiquement."""
    query = [
        "SELECT timestamp_utc, open, high, low, close, volume",
        "FROM bars WHERE symbol = ? AND interval = ?",
    ]
    params: list[Any] = [symbol, interval]

    if start_time is not None:
        query.append("AND timestamp_utc >= ?")
        params.append(start_time.isoformat())

    if end_time is not None:
        query.append("AND timestamp_utc <= ?")
        params.append(end_time.isoformat())

    query.append("ORDER BY timestamp_utc DESC LIMIT ?")
    params.append(limit)

    cur = conn.execute(" ".join(query), params)
    rows = cur.fetchall()

    result: list[Bar] = []
    for r in reversed(rows):
        ts = datetime.fromisoformat(r["timestamp_utc"])
        result.append(
            Bar(
                timestamp_utc=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
            )
        )
    return result


def get_bar_at_or_before(
    symbol: str,
    target_utc: datetime,
    conn: sqlite3.Connection | None = None,
    interval: str = "1m",
) -> Bar | None:
    """Récupère la barre la plus récente ayant eu lieu à ou avant target_utc.

    Exécute : SELECT ... FROM bars WHERE symbol = ? AND interval = ? AND timestamp_utc <= ?
    ORDER BY timestamp_utc DESC LIMIT 1.
    Sans limite artificielle de 100 barres.
    """
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=timezone.utc)
    else:
        target_utc = target_utc.astimezone(timezone.utc)

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        sql = """
            SELECT timestamp_utc, open, high, low, close, volume
            FROM bars
            WHERE symbol = ? AND interval = ? AND timestamp_utc <= ?
            ORDER BY timestamp_utc DESC
            LIMIT 1
        """
        cur = conn.execute(sql, (symbol, interval, target_utc.isoformat()))
        row = cur.fetchone()
        if row is None:
            return None
        ts = datetime.fromisoformat(row["timestamp_utc"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return Bar(
            timestamp_utc=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
    finally:
        if close_conn:
            conn.close()


def insert_snapshot(
    conn: sqlite3.Connection,
    timestamp_utc: datetime,
    spot: float | None,
    regime: str | None,
    gamma_flip: float | None,
    call_wall: float | None,
    put_support: float | None,
    expected_move: float | None,
    basis: float | None,
    synthetic_basis: float | None,
    source: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Enregistre un snapshot des niveaux et régimes de marché."""
    sql = """
    INSERT INTO snapshots (
        timestamp_utc, spot, regime, gamma_flip, call_wall, put_support,
        expected_move, basis, synthetic_basis, source, status, payload_json, created_at_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    payload_str = json.dumps(payload) if payload else None

    with conn:
        cur = conn.execute(
            sql,
            (
                timestamp_utc.isoformat(),
                spot,
                regime,
                gamma_flip,
                call_wall,
                put_support,
                expected_move,
                basis,
                synthetic_basis,
                source,
                status,
                payload_str,
                now_iso,
            ),
        )
    return cur.lastrowid or 0


def get_latest_snapshot(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Retourne le dernier snapshot disponible."""
    cur = conn.execute("SELECT * FROM snapshots ORDER BY timestamp_utc DESC LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


def insert_trade(
    conn: sqlite3.Connection,
    trade_id: str,
    timestamp_utc: datetime,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    r_multiple: float,
    setup: str | None = None,
    rules_respected: bool = True,
    notes: str | None = None,
) -> int:
    """Enregistre un trade exécuté."""
    sql = """
    INSERT OR REPLACE INTO trades (
        trade_id, timestamp_utc, symbol, side, entry_price, exit_price,
        pnl, r_multiple, setup, rules_respected, notes, created_at_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with conn:
        cur = conn.execute(
            sql,
            (
                trade_id,
                timestamp_utc.isoformat(),
                symbol,
                side,
                entry_price,
                exit_price,
                pnl,
                r_multiple,
                setup,
                1 if rules_respected else 0,
                notes,
                now_iso,
            ),
        )
    return cur.lastrowid or 0


def get_db_diagnostic_1c(conn: sqlite3.Connection) -> dict[str, Any]:
    """Diagnostic pour le problème 1c : paires utilisées, barres du 28/09, comptage 7j."""
    cur_old_nq = conn.execute(
        "SELECT timestamp_utc, close FROM bars WHERE symbol = 'NQ=F' AND interval = '1m' "
        "ORDER BY timestamp_utc ASC LIMIT 100"
    )
    old_nq_rows = cur_old_nq.fetchall()
    cur_old_ndx = conn.execute(
        "SELECT timestamp_utc, close FROM bars WHERE symbol = '^NDX' AND interval = '1m' "
        "ORDER BY timestamp_utc ASC LIMIT 100"
    )
    old_ndx_rows = cur_old_ndx.fetchall()

    cur_last_28_nq = conn.execute(
        "SELECT timestamp_utc, open, high, low, close FROM bars "
        "WHERE symbol = 'NQ=F' AND interval = '1m' AND timestamp_utc LIKE '2026-09-28%' "
        "ORDER BY timestamp_utc DESC LIMIT 1"
    )
    last_28_nq = cur_last_28_nq.fetchone()

    cur_last_28_ndx = conn.execute(
        "SELECT timestamp_utc, open, high, low, close FROM bars "
        "WHERE symbol = '^NDX' AND interval = '1m' AND timestamp_utc LIKE '2026-09-28%' "
        "ORDER BY timestamp_utc DESC LIMIT 1"
    )
    last_28_ndx = cur_last_28_ndx.fetchone()

    cur_close_28_nq = conn.execute(
        "SELECT timestamp_utc, close FROM bars "
        "WHERE symbol = 'NQ=F' AND interval = '1m' "
        "AND timestamp_utc <= '2026-09-28T20:00:00+00:00' "
        "ORDER BY timestamp_utc DESC LIMIT 1"
    )
    close_28_nq = cur_close_28_nq.fetchone()

    cur_close_28_ndx = conn.execute(
        "SELECT timestamp_utc, close FROM bars "
        "WHERE symbol = '^NDX' AND interval = '1m' "
        "AND timestamp_utc <= '2026-09-28T20:00:00+00:00' "
        "ORDER BY timestamp_utc DESC LIMIT 1"
    )
    close_28_ndx = cur_close_28_ndx.fetchone()

    cur_counts = conn.execute(
        "SELECT symbol, SUBSTR(timestamp_utc, 1, 10) as day, COUNT(*) as cnt "
        "FROM bars WHERE interval = '1m' "
        "GROUP BY symbol, day ORDER BY symbol, day DESC"
    )
    counts = cur_counts.fetchall()

    return {
        "old_used_nq": dict(old_nq_rows[-1]) if old_nq_rows else None,
        "old_used_ndx": dict(old_ndx_rows[-1]) if old_ndx_rows else None,
        "last_28_nq": dict(last_28_nq) if last_28_nq else None,
        "last_28_ndx": dict(last_28_ndx) if last_28_ndx else None,
        "close_28_nq": dict(close_28_nq) if close_28_nq else None,
        "close_28_ndx": dict(close_28_ndx) if close_28_ndx else None,
        "counts": [dict(r) for r in counts],
    }
