"""Tests for external sources health check, retry mechanism, and fallbacks."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import requests

from nqcockpit.sources.health import (
    SourceCheckResult,
    SourceHealthReport,
    check_bls,
    check_cboe_ndx,
    check_forexfactory,
    check_fred,
    check_gemini,
    check_telegram,
    evaluate_data_staleness,
    get_bls_contact_email,
    is_cme_futures_market_open,
    is_us_equity_market_open,
    request_with_retry,
)


def test_retry_on_simulated_failing_source():
    """Verify that requests retry with exponential backoff on failure and report BLOQUÉ.

    Acceptance criterion: 'un test avec source simulée en échec ; le rapport contient les plans B'.
    """
    mock_session = MagicMock()
    mock_session.request.side_effect = requests.exceptions.ConnectTimeout(
        "Connection timed out after 10s"
    )

    resp, latency, err = request_with_retry(
        url="https://simulated-failing-endpoint.example.com",
        max_retries=3,
        backoff_factor=0.01,  # fast test
        session=mock_session,
    )

    assert resp is None
    assert err is not None
    assert "Connection timed out" in str(err)
    # Must have attempted exactly 3 times
    assert mock_session.request.call_count == 3


def test_cboe_check_simulated_failure():
    """Verify CBOE check handles connection error with BLOQUÉ status and concrete plan B."""
    with patch("nqcockpit.sources.health.request_with_retry") as mock_req:
        mock_req.return_value = (
            None,
            1250.0,
            requests.exceptions.ConnectionError("Connection refused by CDN"),
        )

        res = check_cboe_ndx(timeout=1.0, max_retries=1)

        assert res.status == "BLOQUÉ"
        assert "Connection refused" in res.message
        assert res.fallback_plan != ""
        assert "saisie manuelle" in res.fallback_plan.lower()
        assert res.measured_at_algiers != ""
        assert res.measured_at_ny != ""


def test_cboe_check_simulated_success():
    """Verify CBOE check parses valid response correctly."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "timestamp": "2026-09-28 23:38:47",
        "data": {
            "current_price": 28120.5,
            "options": [{"strike": 28000, "option_type": "C"}],
        },
    }

    with patch("nqcockpit.sources.health.request_with_retry") as mock_req:
        mock_req.return_value = (mock_resp, 140.0, None)

        res = check_cboe_ndx()
        assert res.status == "OK"
        assert res.http_status == 200
        assert "28120.5" in res.message
        assert res.data_timestamp == "2026-09-28 23:38:47"
        assert res.data_age_minutes is not None
        assert res.measured_at_algiers != ""
        assert res.measured_at_ny != ""


def test_fred_missing_key_dgs2_indisponible_dgs10_substitut():
    """Verify FRED reports DÉGRADÉ with DGS2=INDISPONIBLE and DGS10=substitut yfinance."""
    res_list = check_fred(api_key="")
    assert len(res_list) == 2

    # DGS2
    dgs2 = next(r for r in res_list if "DGS2" in r.name)
    assert dgs2.status == "DÉGRADÉ"
    assert "DGS2 = INDISPONIBLE" in dgs2.message
    assert "aucune approximation" in dgs2.fallback_plan.lower()
    assert dgs2.measured_at_algiers != ""
    assert dgs2.measured_at_ny != ""

    # DGS10
    dgs10 = next(r for r in res_list if "DGS10" in r.name)
    assert dgs10.status == "DÉGRADÉ"
    assert "substitut yfinance" in dgs10.message.lower()
    assert "^TNX" in dgs10.fallback_plan
    assert dgs10.measured_at_algiers != ""
    assert dgs10.measured_at_ny != ""


def test_stale_data_evaluation_market_open_vs_closed():
    """Verify distinction between open market (stale=DÉGRADÉ) and closed market (OK)."""
    # 1. Market is open, data is 120 min old (> 60 min threshold) -> DÉGRADÉ
    status, msg = evaluate_data_staleness(
        data_age_minutes=120.0,
        market_is_open=True,
        market_state_desc="Session régulière ouverte",
        stale_threshold_minutes=60,
    )
    assert status == "DÉGRADÉ"
    assert "Donnée périmée" in msg

    # 2. Market is closed (e.g. weekend), data is 120 min old -> OK (last close)
    status_closed, msg_closed = evaluate_data_staleness(
        data_age_minutes=120.0,
        market_is_open=False,
        market_state_desc="Week-end (marché fermé)",
        stale_threshold_minutes=60,
    )
    assert status_closed == "OK"
    assert "Marché fermé" in msg_closed


def test_market_session_calendar_logic():
    """Verify market open/closed determination for equity and futures."""
    tz_ny = ZoneInfo("America/New_York")

    # Tuesday at 11:00 AM ET -> Equity open
    t_open = datetime(2026, 9, 29, 11, 0, tzinfo=tz_ny)
    is_open, desc = is_us_equity_market_open(t_open)
    assert is_open is True

    # Tuesday at 20:00 PM ET -> Equity closed (post-market)
    t_closed = datetime(2026, 9, 29, 20, 0, tzinfo=tz_ny)
    is_open, desc = is_us_equity_market_open(t_closed)
    assert is_open is False
    assert "Post-marché" in desc

    # Saturday at 12:00 PM ET -> Weekend closed
    t_weekend = datetime(2026, 10, 3, 12, 0, tzinfo=tz_ny)
    is_open, desc = is_us_equity_market_open(t_weekend)
    assert is_open is False
    assert "Week-end" in desc

    # Sunday 19:00 ET -> CME Futures open
    t_futures_sun = datetime(2026, 10, 4, 19, 0, tzinfo=tz_ny)
    fut_open, _ = is_cme_futures_market_open(t_futures_sun)
    assert fut_open is True


def test_bls_contact_email_configuration(monkeypatch):
    """Verify BLS contact email resolution without hardcoded values."""
    monkeypatch.setenv("BLS_CONTACT_EMAIL", "test-analyst@example.org")
    email = get_bls_contact_email()
    assert email == "test-analyst@example.org"

    # From explicit config argument
    monkeypatch.delenv("BLS_CONTACT_EMAIL", raising=False)
    email_cfg = get_bls_contact_email(config_email="config-user@example.net")
    assert email_cfg == "config-user@example.net"


def test_gemini_missing_key_zero_network():
    """Verify Gemini makes zero network calls when key is missing."""
    res = check_gemini(api_key="")
    assert res.status == "DÉGRADÉ"
    assert res.latency_ms == 0.0
    assert "GEMINI_API_KEY non configurée" in res.message
    assert "sans LLM" in res.fallback_plan


def test_telegram_missing_token_zero_network():
    """Verify Telegram makes zero network calls when token is missing."""
    res = check_telegram(bot_token="")
    assert res.status == "DÉGRADÉ"
    assert res.latency_ms == 0.0
    assert "TELEGRAM_BOT_TOKEN non configuré" in res.message
    assert "notifications" in res.fallback_plan.lower()


def test_bls_403_simulated_blocked():
    """Verify BLS HTTP 403 reports BLOQUÉ with exact error message and plan B."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    with patch("nqcockpit.sources.health.request_with_retry") as mock_req:
        mock_req.return_value = (mock_resp, 200.0, None)
        res = check_bls(contact_email="test@example.com")
        assert res.status == "BLOQUÉ"
        assert "HTTP 403" in res.message
        assert res.fallback_plan != ""


def test_forexfactory_simulated_success():
    """Verify ForexFactory JSON parsing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "title": "Core PCE Price Index m/m",
            "country": "USD",
            "date": "2026-09-30T08:30:00-04:00",
        },
        {
            "title": "Non-Farm Employment Change",
            "country": "USD",
            "date": "2026-10-02T08:30:00-04:00",
        },
    ]

    with patch("nqcockpit.sources.health.request_with_retry") as mock_req:
        mock_req.return_value = (mock_resp, 85.0, None)
        res = check_forexfactory()
        assert res.status == "OK"
        assert "2 événements" in res.message


def test_source_health_report_generation(tmp_path):
    """Verify SourceHealthReport compiles, renders table, and serializes to JSON."""
    results = [
        SourceCheckResult(
            name="CBOE NDX",
            category="Options",
            status="OK",
            latency_ms=120.5,
            measured_at_algiers="2026-09-29 00:30:00 +01",
            measured_at_ny="2026-09-28 19:30:00 EDT",
            data_timestamp="2026-09-28 16:00:00",
            data_age_minutes=210.0,
            message="OK",
            fallback_plan="Plan B CBOE",
        ),
        SourceCheckResult(
            name="FRED DGS10",
            category="Macro",
            status="DÉGRADÉ",
            latency_ms=0.0,
            measured_at_algiers="2026-09-29 00:30:00 +01",
            measured_at_ny="2026-09-28 19:30:00 EDT",
            message="DGS10 remplaçable par ^TNX (substitut yfinance)",
            fallback_plan="Plan B FRED",
        ),
    ]
    report = SourceHealthReport(
        generated_at_algiers="2026-09-29T00:30:00+01:00",
        generated_at_ny="2026-09-28T19:30:00-04:00",
        generated_at_utc="2026-09-28T23:30:00Z",
        summary={"OK": 1, "DÉGRADÉ": 1, "BLOQUÉ": 0},
        results=results,
    )

    table = report.render_console_table()
    assert "CBOE NDX" in table
    assert "FRED DGS10" in table
    assert "1 OK" in table

    out_file = tmp_path / "source_check.json"
    report.save_json(out_file)
    assert out_file.is_file()
