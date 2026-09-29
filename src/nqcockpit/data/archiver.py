"""Archiveur planifié de barres intraday dans SQLite pour NQ Cockpit."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nqcockpit.data.db import apply_migrations, get_db_connection, insert_bars
from nqcockpit.data.fetcher import DEFAULT_BAR_SYMBOLS, DataFetcher
from nqcockpit.data.models import BarSeries, DataStatus

log = logging.getLogger(__name__)


@dataclass
class ArchiveResult:
    """Résultat d'une passe d'archivage."""

    archived_at_utc: datetime
    symbols_attempted: list[str]
    symbols_succeeded: list[str]
    symbols_failed: list[str]
    total_bars_inserted: int
    details: dict[str, int]
    status: DataStatus


class BarArchiver:
    """Archiveur planifié assurant la persistance dédupliquée des barres dans SQLite."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        fetcher: DataFetcher | None = None,
    ) -> None:
        self.db_path = db_path
        self.fetcher = fetcher or DataFetcher()

    def archive_symbols(
        self,
        symbols: list[str] | None = None,
        intervals: list[str] | None = None,
        period: str = "5d",
    ) -> ArchiveResult:
        """Télécharge les barres pour chaque symbole et intervalle et les archive dans SQLite."""
        if symbols is None:
            symbols = DEFAULT_BAR_SYMBOLS
        if intervals is None:
            intervals = ["1m", "5m"]

        conn = get_db_connection(self.db_path)
        apply_migrations(conn)

        now_utc = datetime.now(timezone.utc)
        succeeded: list[str] = []
        failed: list[str] = []
        total_inserted = 0
        details: dict[str, int] = {}

        for sym in symbols:
            sym_ok = True
            for interval in intervals:
                try:
                    series: BarSeries = self.fetcher.fetch_yahoo_bars(
                        symbol=sym,
                        interval=interval,
                        period=period,
                    )
                    if series.status == DataStatus.BLOCKED or not series.bars:
                        sym_ok = False
                        continue

                    inserted = insert_bars(
                        conn=conn,
                        bars=series.bars,
                        symbol=sym,
                        interval=interval,
                        source=series.source,
                        fetched_at_utc=series.fetched_at_utc,
                        status=series.status,
                    )
                    total_inserted += inserted
                    details[f"{sym}_{interval}"] = inserted
                except Exception as e:
                    log.error("Erreur lors de l'archivage de %s (%s): %s", sym, interval, e)
                    sym_ok = False

            if sym_ok:
                succeeded.append(sym)
            else:
                failed.append(sym)

        conn.close()

        status = DataStatus.OK
        if failed:
            status = DataStatus.DEGRADED if succeeded else DataStatus.BLOCKED

        return ArchiveResult(
            archived_at_utc=now_utc,
            symbols_attempted=symbols,
            symbols_succeeded=succeeded,
            symbols_failed=failed,
            total_bars_inserted=total_inserted,
            details=details,
            status=status,
        )

    def archive_preloaded_series(
        self,
        series_list: list[BarSeries],
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Permet l'archivage direct de séries déjà chargées (ex: lors de tests unitaires)."""
        close_conn = False
        if conn is None:
            conn = get_db_connection(self.db_path)
            apply_migrations(conn)
            close_conn = True

        total_inserted = 0
        for s in series_list:
            inserted = insert_bars(
                conn=conn,
                bars=s.bars,
                symbol=s.symbol,
                interval=s.interval,
                source=s.source,
                fetched_at_utc=s.fetched_at_utc,
                status=s.status,
            )
            total_inserted += inserted

        if close_conn:
            conn.close()

        return total_inserted
