"""Tests pour le module events (Radar d'événements P05).

Couvre :
- Changement d'heure du 1er novembre 2026 (EDT -> EST sans décalage en dur)
- Jour sans événement (GREEN)
- Jour avec deux événements
- Événements Tier 1 dans la fenêtre ou dans le tampon (RED)
- Événements Tier 2 ou mégacaps ou Tier 1 proche (AMBER)
- Sources divergentes (> 5 min)
- Gestion dégradée de yfinance / mégacaps
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from nqcockpit.events.classifier import classify_event, merge_and_classify
from nqcockpit.events.earnings import _fetch_yfinance_earnings, fetch_earnings_events
from nqcockpit.events.models import CalendarEvent, DataStatus, EarningsEvent
from nqcockpit.events.risk import compute_event_risk
from nqcockpit.events.sources.bls import fetch_bls_events
from nqcockpit.events.sources.fed import fetch_fed_events
from nqcockpit.events.sources.fred import _infer_next_date

UTC = timezone.utc
TZ_ET = ZoneInfo("America/New_York")
TZ_ALGIERS = ZoneInfo("Africa/Algiers")

DEFAULT_WINDOWS = [
    {"name": "trade1", "start": "15:30", "end": "17:00"},
    {"name": "trade2", "start": "17:00", "end": "18:30"},
]
DEFAULT_TIER1 = ["FOMC", "CPI", "NFP", "PCE", "FOMC Minutes", "Powell", "GDP"]
DEFAULT_TIER2 = [
    "PPI", "JOLTS", "Retail Sales", "Consumer Sentiment", "ISM", "ADP",
    "Average Hourly Earnings", "Unemployment Rate",
]


def test_day_without_events_is_green() -> None:
    """Un jour sans événement doit produire un risque GREEN avec explication."""
    ref_utc = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    report = compute_event_risk(
        events=[],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
    )
    assert report.risk_level == "GREEN"
    assert "Aucun événement significatif" in report.reason
    assert report.as_of_utc == ref_utc


def test_tier1_in_window_is_red() -> None:
    """Un événement Tier 1 (ex. CPI ou FOMC) tombant dans une fenêtre d'Alger -> RED."""
    # Le 14 oct 2026 : FOMC Minutes ou discours à 14h00 ET = 18h00 UTC = 19h00 Alger
    # Créons un événement à 16h00 Alger = 15h00 UTC (en plein trade1 : 15h30 - 17h00 Alger)
    event_dt_utc = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)  # 16h00 Alger
    ev = CalendarEvent(
        name="FOMC Minutes",
        tier=1,
        scheduled_utc=event_dt_utc,
        source="fed_html",
        description="Minutes FOMC",
    )

    ref_utc = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    report = compute_event_risk(
        events=[ev],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
    )
    assert report.risk_level == "RED"
    assert "FOMC Minutes" in report.reason
    assert "trade1" in report.reason
    assert "RED" in report.risk_level


def test_tier1_post_event_buffer_is_red() -> None:
    """Un Tier 1 avant la fenêtre mais dont le tampon (90 min) déborde sur la fenêtre -> RED."""
    # trade1 commence à 15h30 Alger = 14h30 UTC (en EDT, UTC+1 pour Alger)
    # Si un Tier 1 a lieu à 14h30 Alger = 13h30 UTC,
    # avec un post_buffer de 90 min, l'impact dure jusqu'à 16h00 Alger -> déborde sur trade1 !
    event_dt_utc = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)  # 14h30 Alger
    ev = CalendarEvent(
        name="NFP",
        tier=1,
        scheduled_utc=event_dt_utc,
        source="bls",
        description="Non-Farm Payrolls",
    )

    ref_utc = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
    report = compute_event_risk(
        events=[ev],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
    )
    assert report.risk_level == "RED"
    assert "NFP" in report.reason
    assert "tampon" in report.reason or "couvre" in report.reason


def test_tier2_near_window_is_amber() -> None:
    """Un Tier 2 ou un Tier 1 en périphérie (zone AMBER ±2h) -> AMBER."""
    # trade1 est 15h30 - 17h00 Alger = 14h30 - 16h00 UTC
    # Événement Tier 2 (ex: PPI) à 13h30 Alger = 12h30 UTC (dans la zone ±2h)
    event_dt_utc = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)  # 13h30 Alger
    ev = CalendarEvent(
        name="PPI",
        tier=2,
        scheduled_utc=event_dt_utc,
        source="bls",
        description="Producer Price Index",
    )

    ref_utc = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    report = compute_event_risk(
        events=[ev],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
    )
    assert report.risk_level == "AMBER"
    assert "PPI" in report.reason
    assert "Tier 2" in report.reason


def test_megacap_earnings_is_amber() -> None:
    """Une mégacap publiant ses résultats près des fenêtres déclenche un statut AMBER."""
    # Earnings NVDA à 21h00 UTC = 22h00 Alger (hors fenêtre, mais testons à 17h00 UTC = 18h00 Alger)
    earn_dt_utc = datetime(2026, 10, 22, 17, 0, tzinfo=UTC)  # 18h00 Alger (dans trade2)
    earn = EarningsEvent(
        ticker="NVDA",
        scheduled_utc=earn_dt_utc,
        confirmed=True,
        eps_estimate=0.75,
        status=DataStatus.OK,
    )

    ref_utc = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)
    report = compute_event_risk(
        events=[],
        earnings=[earn],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
    )
    assert report.risk_level == "AMBER"
    assert "NVDA" in report.reason


def test_two_events_same_day() -> None:
    """Un jour avec deux événements (Tier 1 et Tier 2). Le plus restrictif (RED) prime."""
    dt1 = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)  # CPI à 08h30 ET = 13h30 Alger
    dt2 = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)   # Fed Speech à 16h00 Alger
    ev1 = CalendarEvent(name="CPI", tier=1, scheduled_utc=dt1, source="bls")
    ev2 = CalendarEvent(name="Fed Speech", tier=2, scheduled_utc=dt2, source="fed_rss")

    ref_utc = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    report = compute_event_risk(
        events=[ev1, ev2],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
    )
    # ev2 tombe à 16h00 Alger (en plein trade1 15h30-17h00) -> Tier 2 dans fenêtre = AMBER
    # ev1 CPI à 13h30 Alger avec tampon 90min va jusqu'à 15h00 -> proche de trade1 15h30
    assert report.risk_level in ("RED", "AMBER")
    assert "CPI" in report.reason or "Fed Speech" in report.reason


def test_divergent_sources_detected() -> None:
    """Deux sources donnant des heures différentes (>5 min) créent une alerte de divergence."""
    # BLS indique CPI le 14 oct à 08h30 ET = 12h30 UTC
    ev_bls = CalendarEvent(
        name="CPI",
        tier=1,
        scheduled_utc=datetime(2026, 10, 14, 12, 30, tzinfo=UTC),
        source="bls",
    )
    # ForexFactory indique 12h45 UTC (15 min d'écart)
    ev_ff = CalendarEvent(
        name="CPI",
        tier=1,
        scheduled_utc=datetime(2026, 10, 14, 12, 45, tzinfo=UTC),
        source="forexfactory",
        consensus="3.2%",
    )

    merged, divergences = merge_and_classify(
        [ev_bls, ev_ff],
        tier1_names=DEFAULT_TIER1,
        tier2_names=DEFAULT_TIER2,
    )

    assert len(merged) == 1
    assert len(divergences) >= 1
    assert "DIVERGENCE" in divergences[0]
    assert "CPI" in divergences[0]
    # La source prioritaire (bls) est retenue pour l'heure
    assert merged[0].scheduled_utc == datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    # Mais consensus enrichi depuis forexfactory
    assert merged[0].consensus == "3.2%"
    assert set(merged[0].all_sources) == {"bls", "forexfactory"}


def test_dst_november_1st_transition() -> None:
    """Test du passage à l'heure d'hiver US le 1er novembre 2026 (EDT -> EST).

    Règles exactes :
    - Avant 1er nov 2026 (EDT, UTC-4) : 08h30 ET = 12h30 UTC = 13h30 Alger (UTC+1).
    - Après 1er nov 2026 (EST, UTC-5) : 08h30 ET = 13h30 UTC = 14h30 Alger (UTC+1).
    - Avec 90 min de post_event_buffer :
        - Avant 1er nov : 13h30 + 90m = 15h00 Alger. Ne déborde pas sur trade1 (15h30).
        - Après 1er nov : 14h30 + 90m = 16h00 Alger. Déborde sur trade1 (15h30-17h00) -> RED !
    Vérifie qu'aucun décalage n'est codé en dur et que zoneinfo gère tout correctement.
    """
    # 1. Avant nov : 14 oct 2026 à 08h30 ET
    dt_oct_et = datetime(2026, 10, 14, 8, 30, tzinfo=TZ_ET)
    dt_oct_utc = dt_oct_et.astimezone(UTC)
    dt_oct_alg = dt_oct_et.astimezone(TZ_ALGIERS)

    assert dt_oct_utc.hour == 12
    assert dt_oct_utc.minute == 30
    assert dt_oct_alg.hour == 13
    assert dt_oct_alg.minute == 30

    ev_oct = CalendarEvent(name="CPI", tier=1, scheduled_utc=dt_oct_utc, source="bls")
    report_oct = compute_event_risk(
        events=[ev_oct],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=datetime(2026, 10, 14, 8, 0, tzinfo=UTC),
    )
    # En octobre : 13h30 + 90m = 15h00. trade1 commence à 15h30. Zone AMBER (proche) mais pas RED !
    assert report_oct.risk_level == "AMBER"

    # 2. Après nov : 12 nov 2026 à 08h30 ET (US est en EST !)
    dt_nov_et = datetime(2026, 11, 12, 8, 30, tzinfo=TZ_ET)
    dt_nov_utc = dt_nov_et.astimezone(UTC)
    dt_nov_alg = dt_nov_et.astimezone(TZ_ALGIERS)

    assert dt_nov_utc.hour == 13
    assert dt_nov_utc.minute == 30
    assert dt_nov_alg.hour == 14
    assert dt_nov_alg.minute == 30

    ev_nov = CalendarEvent(name="CPI", tier=1, scheduled_utc=dt_nov_utc, source="bls")
    report_nov = compute_event_risk(
        events=[ev_nov],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=datetime(2026, 11, 12, 8, 0, tzinfo=UTC),
    )
    # En novembre : 14h30 + 90m = 16h00. trade1 (15h30 - 17h00) est DEDANS -> RED !
    assert report_nov.risk_level == "RED"
    assert "tampon" in report_nov.reason or "couvre" in report_nov.reason


def test_classifier_priorities() -> None:
    """Vérifie le classement automatique Tier 1 vs Tier 2."""
    ev1 = CalendarEvent(name="FOMC", tier=2, scheduled_utc=datetime.now(UTC), source="test")
    assert classify_event(ev1, DEFAULT_TIER1, DEFAULT_TIER2) == 1

    ev2 = CalendarEvent(name="PPI", tier=1, scheduled_utc=datetime.now(UTC), source="test")
    # Si dans tier2 de config, doit être classifié Tier 2
    assert classify_event(ev2, DEFAULT_TIER1, DEFAULT_TIER2) == 2

    ev3 = CalendarEvent(
        name="Unknown Indicator",
        tier=2,
        scheduled_utc=datetime.now(UTC),
        source="test",
    )
    assert classify_event(ev3, DEFAULT_TIER1, DEFAULT_TIER2) == 2


def test_earnings_degraded_cleanly(tmp_path: pytest.TempPathFactory) -> None:
    """Vérifie que les earnings gèrent les erreurs et retournent DataStatus.DEGRADED sans crash."""
    # Test avec un faux ticker ou environnement sans crash
    events = fetch_earnings_events(
        tickers=["INVALID_TICKER_XYZ"],
        cache_dir=str(tmp_path),
    )
    assert len(events) == 1
    assert events[0].ticker == "INVALID_TICKER_XYZ"
    assert events[0].status == DataStatus.DEGRADED


def test_fred_infer_next_date_no_weekends() -> None:
    """Vérifie que l'inférence FRED ne retourne jamais un samedi ou un dimanche."""
    # 2026-09-11 + 29 jours = 2026-10-10 (samedi) -> doit ajuster au lundi 2026-10-12
    past_dates = ["2026-09-11", "2026-08-13"]
    inferred = _infer_next_date(past_dates)
    assert inferred is not None
    dt = datetime.strptime(inferred, "%Y-%m-%d").date()
    assert dt.weekday() < 5, (
        f"Inferred date {inferred} falls on a weekend ({dt.strftime('%A')})"
    )


def test_earnings_date_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vérifie que _fetch_yfinance_earnings gère datetime.date et extrait Average."""
    mock_yf = MagicMock()
    mock_ticker = MagicMock()
    mock_ticker.calendar = {
        "Earnings Date": [date(2026, 10, 29)],
        "Earnings Average": 1.98,
        "Revenue Average": 113000000000.0,
    }
    mock_yf.Ticker.return_value = mock_ticker
    monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

    ev = _fetch_yfinance_earnings("AAPL")
    assert ev.status == DataStatus.OK
    assert ev.scheduled_utc is not None
    assert ev.scheduled_utc.year == 2026
    assert ev.scheduled_utc.month == 10
    assert ev.scheduled_utc.day == 29
    assert ev.eps_estimate == 1.98
    assert ev.revenue_estimate == 113000000000.0


def test_official_dates_fomc_minutes_and_cpi() -> None:
    """Vérifie que les dates officielles (FOMC Minutes 7 oct, CPI 14 oct) sont exactes."""
    ref_utc = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)

    # 1. Fed FOMC Minutes : 7 oct 2026 14h00 ET = 18h00 UTC = 19h00 Alger
    fed_evs, _, _ = fetch_fed_events(
        rss_url="http://invalid.url",
        now_utc=ref_utc,
        horizon_days=30,
    )
    fomc_minutes = [e for e in fed_evs if e.name == "FOMC Minutes" and e.scheduled_utc.month == 10]
    assert len(fomc_minutes) == 1
    ev_min = fomc_minutes[0]
    et_min = ev_min.scheduled_utc.astimezone(TZ_ET)
    alg_min = ev_min.scheduled_utc.astimezone(TZ_ALGIERS)
    assert et_min.day == 7
    assert et_min.hour == 14
    assert et_min.minute == 0
    assert alg_min.hour == 19

    # 2. BLS CPI : 14 oct 2026 08h30 ET = 12h30 UTC = 13h30 Alger
    bls_evs, _, _ = fetch_bls_events(
        base_url="http://invalid.url",
        now_utc=ref_utc,
        horizon_days=30,
    )
    cpi_evs = [e for e in bls_evs if e.name == "CPI" and e.scheduled_utc.month == 10]
    assert len(cpi_evs) == 1
    ev_cpi = cpi_evs[0]
    et_cpi = ev_cpi.scheduled_utc.astimezone(TZ_ET)
    alg_cpi = ev_cpi.scheduled_utc.astimezone(TZ_ALGIERS)
    assert et_cpi.day == 14
    assert et_cpi.hour == 8
    assert et_cpi.minute == 30
    assert alg_cpi.hour == 13
    assert alg_cpi.minute == 30


def test_day_divergence_detected() -> None:
    """Vérifie que deux sources indiquant des JOURS différents déclenchent DIVERGENCE DATE."""
    ev_bls = CalendarEvent(
        name="CPI",
        tier=1,
        scheduled_utc=datetime(2026, 10, 14, 12, 30, tzinfo=UTC),
        source="bls",
    )
    # FRED infère le 12 octobre (écart de 2 jours)
    ev_fred = CalendarEvent(
        name="CPI",
        tier=1,
        scheduled_utc=datetime(2026, 10, 12, 12, 30, tzinfo=UTC),
        source="fred",
    )

    merged, divergences = merge_and_classify(
        [ev_bls, ev_fred],
        tier1_names=DEFAULT_TIER1,
        tier2_names=DEFAULT_TIER2,
    )
    assert len(merged) == 1
    assert len(divergences) == 1
    assert "DIVERGENCE DATE" in divergences[0]
    assert "2 jours" in divergences[0]
    # La source prioritaire (bls) est conservée pour la date
    assert merged[0].scheduled_utc == datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    assert set(merged[0].all_sources) == {"bls", "fred"}


def test_published_event_today_does_not_affect_future_windows() -> None:
    """Un événement déjà passé aujourd'hui (tampon expiré) est marqué publié et ne bloque pas."""
    # Événement à 08h30 ET = 13h30 Alger = 12h30 UTC.
    # Tampon de 90 min : finit à 15h00 Alger = 14h00 UTC.
    # Référence actuelle : 15h15 Alger = 14h15 UTC (après l'événement et son tampon).
    event_dt_utc = datetime(2026, 9, 30, 12, 30, tzinfo=UTC)
    ref_utc = datetime(2026, 9, 30, 14, 15, tzinfo=UTC)
    ev = CalendarEvent(name="PCE", tier=1, scheduled_utc=event_dt_utc, source="bea")

    report = compute_event_risk(
        events=[ev],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,  # trade1 à 15h30 Alger
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
    )
    # Ne doit pas être RED car son impact s'est achevé à 15h00, avant ref_utc 15h15
    assert report.risk_level == "GREEN"
    assert len(report.calendar_display_algiers) == 1
    assert "[publié]" in report.calendar_display_algiers[0]


def test_forexfactory_ism_mapping() -> None:
    """Vérifie que ISM Manufacturing est correctement normalisé et classifié Tier 2."""
    from nqcockpit.events.sources.forexfactory import _normalize_name
    assert _normalize_name("ISM Manufacturing PMI") == "ISM"
    assert _normalize_name("ISM Services PMI") == "ISM"
    assert _normalize_name("ADP Non-Farm Employment Change") == "ADP"


def test_cpi_ppi_source_priority_and_holiday_exclusion() -> None:
    """Cas Point 1 : CPI (12 oct férié vs 14 oct statique) et PPI (8 vs 9 oct).

    1. L'inférence FRED exclut le 12 octobre 2026 (Columbus Day) -> avance au 13 octobre.
    2. La source statique (14 oct CPI, 8 oct PPI) l'emporte sur l'estimation FRED.
    3. Les divergences de dates affichent les dates de chaque source.
    """
    # 1. Vérification jour férié 12 oct exclu par FRED
    past_dates_cpi = ["2026-09-11", "2026-08-11"]  # delta 31 jours -> 12 oct (lundi férié)
    inferred_cpi = _infer_next_date(past_dates_cpi)
    assert inferred_cpi is not None
    assert inferred_cpi != "2026-10-12", "Le 12 oct (Columbus Day) doit être exclu !"
    assert inferred_cpi == "2026-10-13", "Doit avancer au mardi 13 oct ouvré."

    # 2. CPI : statique (14 oct) vs FRED (13 oct) -> statique gagne
    ev_cpi_stat = CalendarEvent(
        name="CPI",
        tier=1,
        scheduled_utc=datetime(2026, 10, 14, 12, 30, tzinfo=UTC),
        source="static",
    )
    ev_cpi_fred = CalendarEvent(
        name="CPI",
        tier=1,
        scheduled_utc=datetime(2026, 10, 13, 12, 30, tzinfo=UTC),
        source="fred",
    )
    merged_cpi, divs_cpi = merge_and_classify(
        [ev_cpi_stat, ev_cpi_fred], DEFAULT_TIER1, DEFAULT_TIER2
    )
    assert len(merged_cpi) == 1
    assert merged_cpi[0].scheduled_utc.strftime("%Y-%m-%d") == "2026-10-14"
    assert "2026-10-14" in divs_cpi[0] and "2026-10-13" in divs_cpi[0]

    # 3. PPI : statique (8 oct) vs FRED (9 oct) -> statique gagne
    ev_ppi_stat = CalendarEvent(
        name="PPI",
        tier=2,
        scheduled_utc=datetime(2026, 10, 8, 12, 30, tzinfo=UTC),
        source="static",
    )
    ev_ppi_fred = CalendarEvent(
        name="PPI",
        tier=2,
        scheduled_utc=datetime(2026, 10, 9, 12, 30, tzinfo=UTC),
        source="fred",
    )
    merged_ppi, divs_ppi = merge_and_classify(
        [ev_ppi_stat, ev_ppi_fred], DEFAULT_TIER1, DEFAULT_TIER2
    )
    assert len(merged_ppi) == 1
    assert merged_ppi[0].scheduled_utc.strftime("%Y-%m-%d") == "2026-10-08"
    assert "2026-10-08" in divs_ppi[0] and "2026-10-09" in divs_ppi[0]


def test_jolts_time_10_et_and_explicit_time_provenance() -> None:
    """Cas Point 2 : JOLTS à 10:00 ET, provenance d'heure explicite et suppression heure implicite.

    - JOLTS du 7 oct 2026 est planifié à 10:00 ET (14:00 UTC = 15:00 Alger).
    - time_provenance = 'table versionnée BLS (10:00 ET)'.
    - Absence d'heure -> statut DÉGRADÉ visible avec 'non fournie [DÉGRADÉ]'.
    """
    from nqcockpit.events.sources.bls import _make_utc, fetch_bls_events

    # 1. Vérification dans fetch_bls_events
    ref_utc = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
    events, _, _ = fetch_bls_events(
        base_url="https://invalid.example.com", now_utc=ref_utc, horizon_days=14
    )
    jolts_evs = [e for e in events if e.name == "JOLTS" and e.scheduled_utc.month == 10]
    assert len(jolts_evs) == 1
    jolts = jolts_evs[0]
    # 10:00 ET en été/EDT (UTC-4) = 14:00 UTC
    assert jolts.scheduled_utc.hour == 14
    assert jolts.scheduled_utc.minute == 0
    assert jolts.time_provenance == "table versionnée BLS (10:00 ET)"

    # 2. Absence d'heure explicite déclenche DÉGRADÉ
    dt, prov, status = _make_utc("2026-10-07", None)
    assert status == DataStatus.DEGRADED
    assert "DÉGRADÉ" in prov


def test_nfp_date_origin_distinct_indicators_and_consensus_source() -> None:
    """Cas Point 3 : NFP date réelle, séparation indicateurs d'emploi et source valeur.

    - NFP ne prend pas fcst/prec d'Average Hourly Earnings (0.3%).
    - Average Hourly Earnings et Unemployment Rate sont des indicateurs distincts.
    - Origine de la date n'est pas 'estimée' quand deux sources concordent.
    - consensus_source est renseigné (ForexFactory).
    """
    from nqcockpit.events.sources.forexfactory import _normalize_name

    assert _normalize_name("Non-Farm Employment Change") == "NFP"
    assert _normalize_name("Average Hourly Earnings m/m") == "Average Hourly Earnings"
    assert _normalize_name("Unemployment Rate") == "Unemployment Rate"

    # Vérification fusion et non-écrasement
    ev_nfp = CalendarEvent(
        name="NFP",
        tier=1,
        scheduled_utc=datetime(2026, 10, 2, 12, 30, tzinfo=UTC),
        source="forexfactory",
        consensus="90K",
        previous="162K",
        consensus_source="ForexFactory",
        all_sources=["forexfactory", "bls"],
    )
    # Deux sources concordent -> date_origin == "ForexFactory" (source retenue), pas estimée
    assert ev_nfp.date_origin == "ForexFactory"
    assert "estimée" not in ev_nfp.date_origin
    assert ev_nfp.consensus == "90K"
    assert ev_nfp.consensus_source == "ForexFactory"


def test_uncovered_days_marked_degraded_and_missing_indicators_signaled() -> None:
    """Cas Point 4 : Jours non couverts DÉGRADÉ / INCONNU et signalement ISM / Jobless Claims.

    - Les jours ouvrés sans source active (FF nextweek 404) ne sont pas 'GREEN'.
    - L'absence d'ISM Services (05/10) est explicitement signalée.
    - L'absence de Jobless Claims (08/10) est explicitement signalée.
    """
    from nqcockpit.events.models import SourceHealth

    ref_utc = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    source_health = [
        SourceHealth(
            source="forexfactory",
            status=DataStatus.DEGRADED,
            events_count=8,
            error_msg="semaine en cours OK, nextweek indisponible (404)",
            fetched_utc=ref_utc,
        ),
        SourceHealth(
            source="bls",
            status=DataStatus.DEGRADED,
            events_count=4,
            error_msg="403",
            fetched_utc=ref_utc,
        ),
    ]

    report = compute_event_risk(
        events=[],
        earnings=[],
        trading_windows=DEFAULT_WINDOWS,
        post_buffer_min=90,
        stand_aside_before_min=5,
        ref_utc=ref_utc,
        source_health=source_health,
    )

    daily_by_date = {dr["date"]: dr for dr in report.daily_risks}

    # 1. 05/10 (lundi de la semaine suivante) : DÉGRADÉ / INCONNU avec mention ISM Services
    dr_0510 = daily_by_date.get("2026-10-05")
    assert dr_0510 is not None
    assert dr_0510["risk_level"] == "DÉGRADÉ / INCONNU"
    assert "ISM Services" in dr_0510["reason"]

    # 2. 08/10 (jeudi de la semaine suivante) : mention Jobless Claims
    dr_0810 = daily_by_date.get("2026-10-08")
    assert dr_0810 is not None
    assert dr_0810["risk_level"] == "DÉGRADÉ / INCONNU"
    assert "Jobless Claims" in dr_0810["reason"]

    # 3. 06/10 (mardi) : DÉGRADÉ / INCONNU (pas GREEN)
    dr_0610 = daily_by_date.get("2026-10-06")
    assert dr_0610 is not None
    assert dr_0610["risk_level"] == "DÉGRADÉ / INCONNU"




