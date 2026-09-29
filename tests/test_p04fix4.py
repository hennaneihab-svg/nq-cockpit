"""Tests P04-fix4 : Recherche unique de paire, lue par Base et Diagnostic 1c.

Vérifications requises :
- barre 16:00 en mémoire
- barre 16:00 seulement en SQLite
- barre absente partout
- barre présente au-delà de 100 barres (requête par heure sans limite artificielle)
- Δt hors tolérance
- Test de non-régression : BASE et 1c ne peuvent jamais afficher des statuts contradictoires
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from nqcockpit.data.basis import compute_previous_session_basis, find_basis_pair
from nqcockpit.data.db import apply_migrations, get_bar_at_or_before, insert_bars
from nqcockpit.data.models import Bar, DataStatus
from nqcockpit.levels.engine import build_diagnostic_1c

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Crée un datetime ET converti en UTC."""
    return datetime(year, month, day, hour, minute, 0, tzinfo=ET).astimezone(UTC)


def _bar(ts_utc: datetime, close: float) -> Bar:
    """Crée une barre OHLCV fictive."""
    return Bar(timestamp_utc=ts_utc, open=close, high=close, low=close, close=close)


@pytest.fixture
def mem_db():
    """Base SQLite en mémoire pour les tests isolés."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    yield conn
    conn.close()


def test_bar_16h_in_memory():
    """Barre 16:00 présente en mémoire → trouvée avec origine 'memoire'."""
    target_utc = _et(2026, 9, 28, 16, 0)
    nq_bars = [
        _bar(_et(2026, 9, 28, 15, 59), 20500.0),
        _bar(_et(2026, 9, 28, 16, 0), 20510.0),
    ]
    ndx_bars = [
        _bar(_et(2026, 9, 28, 15, 59), 20200.0),
    ]

    res = find_basis_pair(target=target_utc, nq_bars=nq_bars, ndx_bars=ndx_bars)

    assert res.is_found is True
    assert res.nq_origin == "memoire"
    assert res.ndx_origin == "memoire"
    assert res.cause_code == "PAIRE_TROUVEE"
    assert res.is_aligned is True
    assert res.delta_t_minutes == pytest.approx(1.0, abs=0.01)
    assert res.nq_bar is not None and res.nq_bar.close == 20510.0


def test_bar_16h_only_in_sqlite(mem_db):
    """Barre 16:00 absente de la mémoire mais présente en SQLite → origine 'sqlite'."""
    target_utc = _et(2026, 9, 28, 16, 0)

    # En mémoire : seulement des barres post-market (après 19h ET)
    nq_mem = [
        _bar(_et(2026, 9, 28, 19, 12), 20550.0),
        _bar(_et(2026, 9, 28, 20, 51), 20560.0),
    ]
    ndx_mem = [
        _bar(_et(2026, 9, 28, 15, 59), 20277.51),
    ]

    # En SQLite : la barre NQ de 16:00 est présente
    bar_16h = _bar(target_utc, 30571.75)
    insert_bars(
        conn=mem_db,
        bars=[bar_16h],
        symbol="NQ=F",
        interval="1m",
        source="yfinance",
        fetched_at_utc=datetime.now(UTC),
    )

    res = find_basis_pair(
        target=target_utc,
        nq_bars=nq_mem,
        ndx_bars=ndx_mem,
        conn=mem_db,
    )

    assert res.is_found is True
    assert res.nq_origin == "sqlite"
    assert res.ndx_origin == "memoire"
    assert res.cause_code == "PAIRE_TROUVEE"
    assert res.nq_bar is not None and res.nq_bar.close == 30571.75
    assert res.ndx_bar is not None and res.ndx_bar.close == 20277.51


def test_bar_absent_everywhere(mem_db):
    """Barre NQ absente en mémoire et en SQLite → NQ_BAR_ABSENTE, pas de paire."""
    target_utc = _et(2026, 9, 28, 16, 0)
    ndx_mem = [_bar(_et(2026, 9, 28, 15, 59), 20277.51)]

    res = find_basis_pair(
        target=target_utc,
        nq_bars=[],
        ndx_bars=ndx_mem,
        conn=mem_db,
    )

    assert res.nq_bar is None
    assert res.cause_code == "NQ_BAR_ABSENTE"
    assert res.is_aligned is False


def test_bar_beyond_100_bars_in_sqlite(mem_db):
    """Requête par heure sans limite artificielle : trouve la barre même au-delà de 100 barres."""
    target_utc = _et(2026, 9, 28, 16, 0)

    # Insérer la barre cible à 16:00
    target_bar = _bar(target_utc, 30500.0)

    # Insérer 120 barres antérieures (14:00 à 15:59)
    older_bars = [
        _bar(_et(2026, 9, 28, 14, 0) + timedelta(minutes=i), 30400.0 + i)
        for i in range(120)
    ]
    all_bars = older_bars + [target_bar]
    insert_bars(
        conn=mem_db,
        bars=all_bars,
        symbol="NQ=F",
        interval="1m",
        source="test",
        fetched_at_utc=datetime.now(UTC),
    )

    # get_bar_at_or_before doit trouver exactement target_bar sans être tronqué
    found = get_bar_at_or_before("NQ=F", target_utc, conn=mem_db)
    assert found is not None
    assert found.timestamp_utc == target_utc
    assert found.close == 30500.0


def test_delta_t_out_of_tolerance():
    """Δt > 1.0 min → cause HORS_TOLERANCE, is_aligned=False."""
    target_utc = _et(2026, 9, 28, 16, 0)
    nq_bars = [_bar(target_utc, 30500.0)]
    # NDX 5 minutes plus tôt
    ndx_bars = [_bar(_et(2026, 9, 28, 15, 55), 30200.0)]

    res = find_basis_pair(
        target=target_utc,
        nq_bars=nq_bars,
        ndx_bars=ndx_bars,
        tolerance_minutes=1.0,
    )

    assert res.is_found is True
    assert res.delta_t_minutes == pytest.approx(5.0, abs=0.01)
    assert res.is_aligned is False
    assert res.cause_code == "HORS_TOLERANCE"


def test_non_regression_base_and_1c_never_contradict(mem_db):
    """Test de non-régression fondamental : BASE et 1c lisent le même PairResult.

    Il est impossible que 1c affiche 'Barre NQ : ABSENTE' pendant que BASE affiche
    'NQ barre utilisée : close=30571.75' (le bug de P04-fix3).
    """
    target_utc = _et(2026, 9, 28, 16, 0)
    session_d = date(2026, 9, 28)

    # Cas 1 : NQ trouvé en SQLite, NDX en mémoire
    bar_16h = _bar(target_utc, 30571.75)
    insert_bars(
        conn=mem_db,
        bars=[bar_16h],
        symbol="NQ=F",
        interval="1m",
        source="test",
        fetched_at_utc=datetime.now(UTC),
    )
    nq_mem = [_bar(_et(2026, 9, 28, 20, 0), 30600.0)]  # post market
    ndx_mem = [_bar(_et(2026, 9, 28, 15, 59), 30277.51)]

    # Recherche UNIQUE
    pair_res = find_basis_pair(
        target=target_utc,
        nq_bars=nq_mem,
        ndx_bars=ndx_mem,
        conn=mem_db,
    )

    # Base et 1c consomment tous deux pair_res
    snap = compute_previous_session_basis(
        nq_bars=nq_mem,
        ndx_bars=ndx_mem,
        ref_utc=_et(2026, 9, 29, 8, 0),
        pair_result=pair_res,
    )
    diag_1c = build_diagnostic_1c(
        session_date=session_d,
        pair_result=pair_res,
    )

    # Assertions de stricte concordance
    assert diag_1c.nq_candidate_found is True
    assert diag_1c.nq_candidate_close == 30571.75
    assert diag_1c.nq_origin == "sqlite"
    assert snap.nq_price == diag_1c.nq_candidate_close
    assert snap.ndx_price == diag_1c.ndx_candidate_spot
    assert snap.status == DataStatus.OK
    assert diag_1c.cause_code == "PAIRE_TROUVEE"

    # Cas 2 : Données absentes partout
    empty_pair = find_basis_pair(
        target=target_utc,
        nq_bars=[],
        ndx_bars=[],
        conn=sqlite3.connect(":memory:"),
    )
    snap_empty = compute_previous_session_basis(
        nq_bars=[],
        ndx_bars=[],
        ref_utc=_et(2026, 9, 29, 8, 0),
        pair_result=empty_pair,
    )
    diag_empty = build_diagnostic_1c(
        session_date=session_d,
        pair_result=empty_pair,
    )

    # Concordance en cas d'absence
    assert snap_empty.status == DataStatus.BLOCKED
    assert diag_empty.nq_candidate_found is False
    assert diag_empty.ndx_candidate_found is False
    assert "ABSENTE" in diag_empty.cause_code
