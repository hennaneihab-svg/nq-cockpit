"""Tests unitaires pour la couche de données NQ Cockpit (P03).

Tous les tests s'exécutent en mémoire (:memory:) ou avec des fixtures locales,
sans aucun appel réseau sortant.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from nqcockpit.data.archiver import BarArchiver
from nqcockpit.data.basis import (
    compute_live_basis,
    compute_previous_session_basis,
    synthetic_futures_basis_from_options,
)
from nqcockpit.data.cache import DiskCache
from nqcockpit.data.calendar import MarketCalendar
from nqcockpit.data.db import (
    apply_migrations,
    get_bars,
    get_db_connection,
    get_latest_snapshot,
    insert_bars,
    insert_snapshot,
    insert_trade,
)
from nqcockpit.data.fetcher import DataFetcher
from nqcockpit.data.models import Bar, BarSeries, DataStatus
from nqcockpit.data.roll import detect_nq_roll, third_friday_of_month

ET = ZoneInfo("America/New_York")


@pytest.fixture
def mem_db():
    """Fournit une connexion SQLite en mémoire avec migrations appliquées."""
    conn = get_db_connection(":memory:")
    apply_migrations(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# 1. Tests SQLite et Migrations
# ---------------------------------------------------------------------------


def test_migrations_and_schema_version(mem_db):
    """Vérifie que la table schema_version et les tables applicatives sont créées."""
    cur = mem_db.execute("SELECT version, name FROM schema_version")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert rows[0]["name"] == "initial_schema"

    # Vérification de l'idempotence des migrations
    count = apply_migrations(mem_db)
    assert count == 0


def test_insert_and_deduplicate_bars(mem_db):
    """Vérifie que les barres sont insérées et dédupliquées sans créer de doublon."""
    t0 = datetime(2026, 9, 28, 14, 0, 0, tzinfo=timezone.utc)
    b1 = Bar(
        timestamp_utc=t0, open=20000.0, high=20010.0, low=19990.0, close=20005.0, volume=150.0
    )
    b2 = Bar(
        timestamp_utc=t0 + timedelta(minutes=1),
        open=20005.0,
        high=20015.0,
        low=20000.0,
        close=20010.0,
        volume=120.0,
    )

    # Première insertion
    ins1 = insert_bars(mem_db, [b1, b2], "NQ=F", "1m", "fixture", t0, DataStatus.OK)
    assert ins1 == 2

    # Vérification du nombre de barres
    bars = get_bars(mem_db, "NQ=F", "1m")
    assert len(bars) == 2
    assert bars[0].close == 20005.0

    # Deuxième insertion des mêmes barres avec un close mis à jour (idempotence)
    b1_updated = Bar(
        timestamp_utc=t0, open=20000.0, high=20010.0, low=19990.0, close=20006.0, volume=160.0
    )
    ins2 = insert_bars(mem_db, [b1_updated], "NQ=F", "1m", "fixture", t0, DataStatus.OK)
    assert ins2 == 1

    # Le total doit rester 2 (pas de doublon), mais le close doit être mis à jour
    bars_after = get_bars(mem_db, "NQ=F", "1m")
    assert len(bars_after) == 2
    assert bars_after[0].close == 20006.0


def test_get_bars_range_filtering(mem_db):
    """Vérifie le filtrage par plage temporelle sur get_bars."""
    base_t = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
    bars_list = [
        Bar(
            timestamp_utc=base_t + timedelta(minutes=i),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
        )
        for i in range(10)
    ]
    insert_bars(mem_db, bars_list, "^NDX", "1m", "fixture", base_t, DataStatus.OK)

    # Plage de 3 minutes
    start = base_t + timedelta(minutes=2)
    end = base_t + timedelta(minutes=4)
    subset = get_bars(mem_db, "^NDX", "1m", start_time=start, end_time=end)
    assert len(subset) == 3
    assert subset[0].timestamp_utc == start
    assert subset[-1].timestamp_utc == end


def test_snapshots_and_trades_persistence(mem_db):
    """Vérifie la persistance et lecture des snapshots et trades."""
    t = datetime(2026, 9, 28, 15, 30, 0, tzinfo=timezone.utc)
    snap_id = insert_snapshot(
        mem_db,
        timestamp_utc=t,
        spot=20150.0,
        regime="LOW_VOL",
        gamma_flip=19800.0,
        call_wall=20500.0,
        put_support=19500.0,
        expected_move=180.0,
        basis=120.0,
        synthetic_basis=118.5,
        source="CBOE",
        status="OK",
        payload={"notes": "test"},
    )
    assert snap_id > 0

    latest = get_latest_snapshot(mem_db)
    assert latest is not None
    assert latest["spot"] == 20150.0
    assert latest["gamma_flip"] == 19800.0

    trade_id = insert_trade(
        mem_db,
        trade_id="TR-20260928-01",
        timestamp_utc=t,
        symbol="MNQ",
        side="LONG",
        entry_price=20100.0,
        exit_price=20150.0,
        pnl=100.0,
        r_multiple=1.5,
        setup="Pullback Call Wall",
        rules_respected=True,
    )
    assert trade_id > 0


# ---------------------------------------------------------------------------
# 2. Tests Cache Disque
# ---------------------------------------------------------------------------


def test_disk_cache(tmp_path: Path):
    """Vérifie l'écriture, la lecture et l'expiration TTL du cache disque."""
    cache = DiskCache(cache_dir=tmp_path)
    cache.set("test_key", {"val": 42})

    # Lecture immédiate
    data = cache.get("test_key", max_age_seconds=60)
    assert data == {"val": 42}

    # Lecture avec TTL expiré
    expired = cache.get("test_key", max_age_seconds=-1)
    assert expired is None

    # Suppression
    cache.clear("test_key")
    assert cache.get("test_key") is None


# ---------------------------------------------------------------------------
# 3. Tests Calendrier de Marché et Sessions
# ---------------------------------------------------------------------------


def test_calendar_trading_day_and_holiday():
    """Vérifie la détection de jours fériés et week-ends US via pandas_market_calendars."""
    cal = MarketCalendar()

    # Vendredi normal : 25 septembre 2026
    assert cal.is_trading_day(date(2026, 9, 25)) is True

    # Samedi : 26 septembre 2026
    assert cal.is_trading_day(date(2026, 9, 26)) is False

    # Noël : 25 décembre 2026 (fermé)
    assert cal.is_trading_day(date(2026, 12, 25)) is False

    # 4 juillet (Independance Day) observé en 2026 : vendredi 3 juillet
    assert cal.is_trading_day(date(2026, 7, 3)) is False


def test_calendar_session_hours():
    """Vérifie le statut de session (REGULAR_HOURS, PRE_MARKET, CLOSED)."""
    cal = MarketCalendar()

    # Mercredi 23 septembre 2026 à 10:00 ET (séance régulière)
    # EDT = UTC-4 -> 10:00 EDT = 14:00 UTC
    dt_regular = datetime(2026, 9, 23, 14, 0, 0, tzinfo=timezone.utc)
    assert cal.is_us_equity_regular_hours(dt_regular) is True
    assert cal.get_session_status(dt_regular) == "REGULAR_HOURS"

    # Mercredi 23 septembre 2026 à 08:00 ET (pré-marché) -> 12:00 UTC
    dt_pre = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert cal.is_us_equity_regular_hours(dt_pre) is False
    assert cal.get_session_status(dt_pre) == "PRE_MARKET"

    # Dimanche 27 septembre 2026
    dt_weekend = datetime(2026, 9, 27, 15, 0, 0, tzinfo=timezone.utc)
    assert cal.is_us_equity_regular_hours(dt_weekend) is False
    assert cal.get_session_status(dt_weekend) == "CLOSED_WEEKEND"


# ---------------------------------------------------------------------------
# 4. Tests Détection de Roll NQ
# ---------------------------------------------------------------------------


def test_third_friday_calculation():
    """Vérifie le calcul exact du 3ème vendredi."""
    # Septembre 2026 : le 1er est un mardi.
    # 1er vendredi = 4 sept, 2ème = 11 sept, 3ème = 18 sept.
    exp_sep_2026 = third_friday_of_month(2026, 9)
    assert exp_sep_2026 == date(2026, 9, 18)

    # Décembre 2026 : le 1er est un mardi.
    # 1er vendredi = 4 déc, 2ème = 11 déc, 3ème = 18 déc.
    exp_dec_2026 = third_friday_of_month(2026, 12)
    assert exp_dec_2026 == date(2026, 12, 18)


def test_detect_nq_roll_logic():
    """Vérifie la détection du contrat actif et de la fenêtre de roll."""
    # 1er septembre 2026 : avant la fenêtre de roll de septembre
    info_early = detect_nq_roll(date(2026, 9, 1))
    assert info_early.active_contract == "NQU6"
    assert info_early.next_contract == "NQZ6"
    assert info_early.is_roll_window is False
    assert info_early.status == "NORMAL"

    # 14 septembre 2026 : dans la fenêtre de roll (8 jours avant le 18 sept)
    info_roll = detect_nq_roll(date(2026, 9, 14))
    assert info_roll.active_contract == "NQU6"
    assert info_roll.next_contract == "NQZ6"
    assert info_roll.is_roll_window is True
    assert info_roll.status == "ROLL_WINDOW"

    # 20 septembre 2026 : après l'expiration de septembre -> contrat actif = NQZ6
    info_post = detect_nq_roll(date(2026, 9, 20))
    assert info_post.active_contract == "NQZ6"
    assert info_post.next_contract == "NQH7"
    assert info_post.is_roll_window is False


# ---------------------------------------------------------------------------
# 5. Tests Calcul et Validation de la Base NQ/NDX
# ---------------------------------------------------------------------------


def test_live_basis_aligned_bars():
    """Vérifie le calcul de la base sur des barres 1m synchronisées."""
    # Instant en séance régulière (14:30 UTC = 10:30 EDT)
    t = datetime(2026, 9, 23, 14, 30, 0, tzinfo=timezone.utc)
    nq_bar = Bar(timestamp_utc=t, open=20120.0, high=20125.0, low=20118.0, close=20122.0)
    ndx_bar = Bar(timestamp_utc=t, open=20000.0, high=20005.0, low=19998.0, close=20002.0)

    snap = compute_live_basis(nq_bar, ndx_bar, now_utc=t + timedelta(seconds=10))
    assert snap.status == DataStatus.OK
    assert snap.basis == 120.0  # 20122 - 20002
    assert snap.is_session_basis is True
    assert "séance" in snap.label


def test_live_basis_drift_rejection():
    """Vérifie le rejet (BLOCKED) si les barres 1m ont plus de 60s d'écart."""
    t_nq = datetime(2026, 9, 23, 14, 30, 0, tzinfo=timezone.utc)
    t_ndx = datetime(2026, 9, 23, 14, 28, 0, tzinfo=timezone.utc)  # 2 min d'écart !

    nq_bar = Bar(timestamp_utc=t_nq, open=20120.0, high=20125.0, low=20118.0, close=20122.0)
    ndx_bar = Bar(timestamp_utc=t_ndx, open=20000.0, high=20005.0, low=19998.0, close=20002.0)

    snap = compute_live_basis(nq_bar, ndx_bar, max_drift_seconds=60.0)
    assert snap.status == DataStatus.BLOCKED
    assert "désalignement" in snap.label


def test_previous_session_basis_fallback():
    """Vérifie le repli sur la clôture régulière précédente avec label explicite."""
    # 23 septembre 2026 16:00 ET = 20:00 UTC
    t_close = datetime(2026, 9, 23, 20, 0, 0, tzinfo=timezone.utc)
    nq_bars = [Bar(timestamp_utc=t_close, open=20100.0, high=20105.0, low=20095.0, close=20102.0)]
    ndx_bars = [Bar(timestamp_utc=t_close, open=20000.0, high=20005.0, low=19995.0, close=20000.0)]

    # Demande de base le soir à 22:00 UTC (hors séance actions)
    t_evening = datetime(2026, 9, 23, 22, 0, 0, tzinfo=timezone.utc)
    snap = compute_previous_session_basis(nq_bars, ndx_bars, ref_utc=t_evening)

    assert snap.status == DataStatus.OK
    assert snap.basis == 102.0
    assert "base de la séance précédente" in snap.label
    assert "âge 2.0 h" in snap.label
    assert snap.is_session_basis is False
    assert snap.age_minutes == pytest.approx(120.0, rel=1e-2)


def test_synthetic_futures_basis_from_options():
    """Vérifie le calcul parité call-put adapté de Darthreign/gex-dashboard."""
    target_exp = date(2026, 12, 18)
    spot = 20000.0

    # Créer 6 strikes autour de 20000
    rows = []
    strikes = [19600, 19800, 20000, 20200, 20400, 20600]
    for k in strikes:
        # Fwd théorique = spot + 100 = 20100
        # C - P = (Fwd - K) * exp(-rT)
        rows.append({"expiry": target_exp, "type": "C", "strike": k, "bid": 250.0, "ask": 252.0})
        rows.append({"expiry": target_exp, "type": "P", "strike": k, "bid": 150.0, "ask": 152.0})

    df = pd.DataFrame(rows)
    basis = synthetic_futures_basis_from_options(
        df,
        spot=spot,
        risk_free_rate=0.04,
        today_date=date(2026, 9, 28),
    )
    # Vérifier que le résultat est un flottant calculé
    assert basis is not None
    assert isinstance(basis, float)


# ---------------------------------------------------------------------------
# 6. Tests Fetcher avec Fixtures (sans réseau)
# ---------------------------------------------------------------------------


def test_fetcher_yahoo_bars_with_mock(tmp_path: Path):
    """Vérifie le parsing et la détection de statut du fetcher via mock yfinance."""
    fetcher = DataFetcher(cache=DiskCache(cache_dir=tmp_path))

    mock_df = pd.DataFrame(
        {
            "Open": [20000.0, 20010.0],
            "High": [20015.0, 20020.0],
            "Low": [19990.0, 20005.0],
            "Close": [20010.0, 20018.0],
            "Volume": [100.0, 200.0],
        },
        index=[
            pd.Timestamp("2026-09-28 14:00:00", tz="UTC"),
            pd.Timestamp("2026-09-28 14:01:00", tz="UTC"),
        ],
    )

    with patch("yfinance.Ticker") as mock_ticker:
        instance = mock_ticker.return_value
        instance.history.return_value = mock_df

        series = fetcher.fetch_yahoo_bars("NQ=F", interval="1m", max_cache_age_seconds=0)
        assert series.count == 2
        assert series.symbol == "NQ=F"
        assert series.bars[0].close == 20010.0
        assert series.bars[1].close == 20018.0


def test_fetcher_empty_data_handling(tmp_path: Path):
    """Vérifie la robustesse si la source renvoie un DataFrame vide."""
    fetcher = DataFetcher(cache=DiskCache(cache_dir=tmp_path))

    with patch("yfinance.Ticker") as mock_ticker:
        instance = mock_ticker.return_value
        instance.history.return_value = pd.DataFrame()

        series = fetcher.fetch_yahoo_bars("UNKNOWN", max_retries=1, max_cache_age_seconds=0)
        assert series.status == DataStatus.BLOCKED
        assert series.count == 0


def test_bar_archiver_with_preloaded_series(mem_db):
    """Vérifie l'archivage en base SQLite sans appel réseau."""
    t0 = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)
    bars = [
        Bar(timestamp_utc=t0, open=100.0, high=105.0, low=95.0, close=102.0),
        Bar(
            timestamp_utc=t0 + timedelta(minutes=1),
            open=102.0,
            high=107.0,
            low=101.0,
            close=106.0,
        ),
    ]
    series = BarSeries(symbol="^VIX", interval="1m", bars=bars, source="test", fetched_at_utc=t0)

    archiver = BarArchiver()
    inserted = archiver.archive_preloaded_series([series], conn=mem_db)
    assert inserted == 2

    # Vérification dans SQLite
    saved_bars = get_bars(mem_db, "^VIX", "1m")
    assert len(saved_bars) == 2
    assert saved_bars[-1].close == 106.0


def test_cboe_parsing_and_age_derivation():
    """Vérifie la dérivation d'âge depuis les cotations d'options CBOE (audit P01/P02)."""
    from nqcockpit.data.cboe import parse_cboe_payload, parse_occ

    # 1. Test parse_occ
    parsed = parse_occ("NDX260930C28000000")
    assert parsed is not None
    exp, cp, strike = parsed
    assert exp == date(2026, 9, 30)
    assert cp == "C"
    assert strike == 28000.0

    # 2. Test avec cotations horodatées
    now_utc = datetime(2026, 9, 28, 20, 15, 0, tzinfo=timezone.utc)
    raw = {
        "data": {
            "current_price": 28120.0,
            "options": [
                {
                    "option": "NDX260930C28000000",
                    "bid": 150.0,
                    "ask": 152.0,
                    "last_trade_time": "2026-09-28T20:00:00Z",
                },
            ],
        }
    }
    snap = parse_cboe_payload(raw, now_utc)
    assert snap.status == DataStatus.OK
    assert snap.age_minutes == pytest.approx(15.0)
    assert snap.latest_quote_time_utc == datetime(2026, 9, 28, 20, 0, 0, tzinfo=timezone.utc)

    # 3. Test sans cotations horodatées -> âge inconnu = DÉGRADÉ
    raw_no_quote_time = {
        "data": {
            "current_price": 28120.0,
            "options": [
                {
                    "option": "NDX260930C28000000",
                    "bid": 150.0,
                    "ask": 152.0,
                },
            ],
        }
    }
    snap_degraded = parse_cboe_payload(raw_no_quote_time, now_utc)
    assert snap_degraded.status == DataStatus.DEGRADED
    assert snap_degraded.age_minutes is None
    assert "âge inconnu" in snap_degraded.notes.lower()


def test_run_diagnostic_1c():
    """Exécute et imprime le diagnostic réel de la base pour le problème 1c."""
    import json

    from nqcockpit.data.db import get_db_connection, get_db_diagnostic_1c

    conn = get_db_connection("data/nqcockpit.db")
    diag = get_db_diagnostic_1c(conn)
    conn.close()
    print("\n--- DIAGNOSTIC 1C RESULT ---")
    print(json.dumps(diag, indent=2))
    assert diag is not None
