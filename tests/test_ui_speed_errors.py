"""Tests Étape 4 — vitesse UI, timeouts sources et robustesse du rendu.

Couvre :
- Profil de séance mis en cache (pas de recalcul dans le TTL de 60 s).
- Timeout d'une source réseau => statut DÉGRADÉ, jamais d'exception.
- Wrapper de page : exception interceptée, message court, traceback dans les logs.
- Export CSV des niveaux : horodatage snapshot (UTC + Alger), âge, basis NDX→NQ.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from nqcockpit.data.cache import DiskCache
from nqcockpit.data.models import DataStatus
from nqcockpit.events.sources.bls import fetch_bls_events
from nqcockpit.macro.fetcher import CFTC_COT_URL, fetch_cftc_cot, parse_cftc_report
from nqcockpit.profile.engine import export_levels_to_csv
from nqcockpit.profile.models import KeyLevel
from nqcockpit.ui.components import render_page_safely

UTC = timezone.utc
NOW_UTC = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 1. Cache du profil de séance
# ---------------------------------------------------------------------------


def test_cached_profile_is_not_recomputed_within_ttl(monkeypatch, tmp_path):
    """Deux appels dans le TTL ne doivent déclencher qu'un seul build_day_profile."""
    import nqcockpit.ui.cockpit_page as cockpit_page

    calls = {"count": 0}

    def _fake_build(*, conn, config, now_utc):
        calls["count"] += 1
        return f"profile-{calls['count']}"

    monkeypatch.setattr(cockpit_page, "build_day_profile", _fake_build)
    cockpit_page.load_day_profile_cached.clear()
    try:
        first = cockpit_page.load_day_profile_cached(str(tmp_path / "cache_test.db"))
        second = cockpit_page.load_day_profile_cached(str(tmp_path / "cache_test.db"))
    finally:
        cockpit_page.load_day_profile_cached.clear()

    assert calls["count"] == 1
    assert first == second == "profile-1"


# ---------------------------------------------------------------------------
# 2. Timeouts réseaux => DÉGRADÉ (aucune exception)
# ---------------------------------------------------------------------------


def _raise_timeout(*args, **kwargs):
    raise TimeoutError("simulated timeout")


def test_cftc_timeout_returns_degraded_without_exception(monkeypatch, tmp_path):
    """Un timeout CFTC (<= 5 s) retourne un CotPositioning DÉGRADÉ, sans données inventées."""
    seen = {}

    def _timed_out(req, timeout=None):
        seen["timeout"] = timeout
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("nqcockpit.macro.fetcher.urllib.request.urlopen", _timed_out)
    cot = fetch_cftc_cot(cache=DiskCache(tmp_path / "cache"))

    assert seen["timeout"] is not None and seen["timeout"] <= 5
    assert cot.status.startswith("DÉGRADÉ")
    assert cot.non_commercial_long is None
    assert cot.non_commercial_short is None
    assert cot.non_commercial_net is None
    assert CFTC_COT_URL == "https://www.cftc.gov/dea/futures/financial_lf.htm"


def test_bls_timeout_degrades_instead_of_raising(monkeypatch):
    """Un timeout BLS bascule la source en DÉGRADÉ au lieu de propager l'exception."""
    monkeypatch.setattr(
        "nqcockpit.events.sources.bls.urllib.request.urlopen", _raise_timeout
    )
    events, status, error = fetch_bls_events("https://www.bls.gov", now_utc=NOW_UTC)

    assert status == DataStatus.DEGRADED
    assert "inaccessible" in error
    assert isinstance(events, list)


def test_cftc_parser_reads_official_html_report():
    """Le parseur lit le format officiel « Traders in Financial Futures »."""
    content = (
        "Traders in Financial Futures - Futures Only Positions as of "
        "October 20, 2026\n"
        "-----------------------------------------------------------------\n"
        "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE\n"
        "Positions\n"
        "39,302 129,243 8,154 110,983 32,216 4,977 "
        "48,053 55,741 13,764 13,173 10,623 0 47,477 31,164\n"
    )
    parsed = parse_cftc_report(content, "NASDAQ-100")

    assert parsed is not None
    report_date, contract, nc_long, nc_short = parsed
    assert report_date == "2026-10-20"
    assert "NASDAQ-100 Consolidated" in contract
    assert (nc_long, nc_short) == (48053, 55741)


# ---------------------------------------------------------------------------
# 3. Wrapper de page
# ---------------------------------------------------------------------------


def test_page_wrapper_catches_injected_exception(monkeypatch, caplog):
    """Une exception de page devient un st.error court ; la traceback va dans les logs."""
    messages = {}
    monkeypatch.setattr(
        "nqcockpit.ui.components.st.error",
        lambda msg, *args, **kwargs: messages.setdefault("msg", msg),
    )

    def _boom():
        raise RuntimeError("boom injected")

    with caplog.at_level(logging.ERROR, logger="nqcockpit.ui.components"):
        rendered = render_page_safely(_boom, "Cockpit")

    assert rendered is False
    assert "Erreur interne" in messages["msg"]
    assert "boom injected" not in messages["msg"]
    assert "RuntimeError" in caplog.text
    assert "Traceback" in caplog.text


def test_page_wrapper_returns_true_on_success(monkeypatch):
    """Un rendu normal retourne True et n'affiche aucune erreur."""
    called = {"ok": False}
    monkeypatch.setattr(
        "nqcockpit.ui.components.st.error",
        lambda *args, **kwargs: called.__setitem__("ok", True),
    )

    assert render_page_safely(lambda: None, "Cockpit") is True
    assert called["ok"] is False


# ---------------------------------------------------------------------------
# 4. Export CSV : traçabilité du snapshot
# ---------------------------------------------------------------------------


def test_levels_csv_contains_snapshot_metadata():
    """Le CSV porte l'horodatage UTC/Alger, l'âge en minutes et le basis NDX→NQ."""
    levels = [
        KeyLevel(
            name="Call Wall",
            symbol="NQ=F",
            price=20500.0,
            level_type="GAMMA",
            distance_pts=200.0,
            distance_pct=1.0,
            source="CBOE NDX (P04)",
            description="test",
        )
    ]
    csv_text = export_levels_to_csv(
        levels,
        now_utc=NOW_UTC,
        snapshot_timestamp_utc="2026-10-20T13:48:00+00:00",
        snapshot_age_minutes=12.4,
        basis_ndx_nq=287.5,
    )
    header, row = csv_text.strip().split("\n")

    assert "Snapshot_UTC" in header
    assert "Snapshot_Algiers" in header
    assert "Snapshot_Age_Min" in header
    assert "Basis_NDX_to_NQ" in header
    assert "2026-10-20T13:48:00+00:00" in row
    assert "14:48:00" in row  # Alger = UTC+1
    assert "12" in row
    assert "287.50" in row
