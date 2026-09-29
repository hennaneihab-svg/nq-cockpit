"""Couche de données et persistance locale SQLite pour NQ Cockpit."""

from nqcockpit.data.archiver import BarArchiver
from nqcockpit.data.basis import (
    compute_live_basis,
    compute_previous_session_basis,
    synthetic_futures_basis_from_options,
)
from nqcockpit.data.cache import DiskCache
from nqcockpit.data.calendar import CALENDAR, MarketCalendar
from nqcockpit.data.cboe import (
    CboeChainSnapshot,
    fetch_cboe_options_chain,
    parse_cboe_payload,
)
from nqcockpit.data.db import (
    apply_migrations,
    get_bars,
    get_db_connection,
    insert_bars,
    insert_snapshot,
)
from nqcockpit.data.fetcher import DataFetcher
from nqcockpit.data.models import (
    Bar,
    BarSeries,
    BasisSnapshot,
    DataStatus,
    FredObservation,
    RollInfo,
)
from nqcockpit.data.roll import detect_nq_roll

__all__ = [
    "BarArchiver",
    "CboeChainSnapshot",
    "fetch_cboe_options_chain",
    "parse_cboe_payload",
    "compute_live_basis",
    "compute_previous_session_basis",
    "synthetic_futures_basis_from_options",
    "DiskCache",
    "CALENDAR",
    "MarketCalendar",
    "apply_migrations",
    "get_db_connection",
    "insert_bars",
    "get_bars",
    "insert_snapshot",
    "DataFetcher",
    "Bar",
    "BarSeries",
    "BasisSnapshot",
    "DataStatus",
    "FredObservation",
    "RollInfo",
    "detect_nq_roll",
]
