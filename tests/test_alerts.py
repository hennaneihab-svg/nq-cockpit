"""Tests de l'alerteur Telegram autonome (HTTP et données mockés, sans réseau)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from nqcockpit.alerts import run
from nqcockpit.briefing.models import TelegramResult
from nqcockpit.events.models import CalendarEvent, DataStatus, SourceHealth

UTC = timezone.utc


def _ok_send(record: list):
    def _send(msg):
        record.append(msg)
        return TelegramResult(status="OK", sent=True)

    return _send


def test_rule_event_fires_only_in_window():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    report = SimpleNamespace(
        events=[
            CalendarEvent(name="CPI", tier=1, scheduled_utc=now + timedelta(minutes=10),
                          source="x", status=DataStatus.OK),
            CalendarEvent(name="NFP", tier=1, scheduled_utc=now + timedelta(hours=3),
                          source="x", status=DataStatus.OK),
        ],
        source_health=[],
    )
    msgs = run._rule_event({"event_window_min": 15}, report, now, fr=False)
    assert len(msgs) == 1
    assert "CPI" in msgs[0]


def test_rule_event_missing_source_skips():
    report = SimpleNamespace(events=None, source_health=[])
    assert run._rule_event({"event_window_min": 15}, report, datetime.now(UTC), fr=False) == []


def test_rule_source_alerts_on_change_only():
    state: dict = {}
    report = SimpleNamespace(
        events=[],
        source_health=[SourceHealth(source="fed", status=DataStatus.DEGRADED)],
    )
    now = datetime.now(UTC)
    assert run._rule_source(state, report, now, fr=False) == []
    report.source_health[0].status = DataStatus.OK
    msgs = run._rule_source(state, report, now, fr=False)
    assert len(msgs) == 1
    assert "fed" in msgs[0]


def test_rule_mt5_alerts_on_change_only(monkeypatch):
    class _FakeStatus:
        is_ok = False

    class _FakeClient:
        def get_status(self):
            return _FakeStatus()

    monkeypatch.setattr("nqcockpit.broker.mt5_client.MT5Client", lambda: _FakeClient())
    state = {"mt5_connected": True}
    msgs = run._rule_mt5(state, datetime.now(UTC), fr=False)
    assert any("disconnected" in m for m in msgs)
    # pas de changement -> pas d'alerte
    assert run._rule_mt5(state, datetime.now(UTC), fr=False) == []


def test_rule_discipline_lock(monkeypatch):
    class _FakeState:
        can_trade = False
        lock_reasons = ["Limite de perte journalière atteinte"]

    monkeypatch.setattr(
        "nqcockpit.discipline.engine.evaluate_session_state", lambda t, n, c: _FakeState()
    )
    monkeypatch.setattr("nqcockpit.journal.store.init_journal_db", lambda p: MagicMock())
    monkeypatch.setattr("nqcockpit.journal.store.load_trades", lambda c: [])
    state = {"discipline_locked": False}
    msgs = run._rule_discipline(state, datetime.now(UTC), None, "db", fr=False)
    assert any("Discipline lock" in m for m in msgs)


def test_rule_level_touch_once_per_day(monkeypatch):
    monkeypatch.setattr("nqcockpit.data.db.get_db_connection", lambda p: MagicMock())
    monkeypatch.setattr(
        "nqcockpit.data.db.get_latest_snapshot",
        lambda c: {"call_wall": 20800.0, "gamma_flip": 20700.0, "put_support": 20600.0},
    )
    monkeypatch.setattr(run, "_last_nq_price", lambda now: 20795.0)
    state: dict = {}
    now = datetime.now(UTC)
    msgs = run._rule_level({"level_touch_pts": 10}, state, now, "db", fr=False)
    assert any("Call Wall" in m for m in msgs)
    # une fois par niveau par jour -> rien au second passage
    assert run._rule_level({"level_touch_pts": 10}, state, now, "db", fr=False) == []


def test_rule_level_missing_snapshot_skips(monkeypatch):
    monkeypatch.setattr("nqcockpit.data.db.get_db_connection", lambda p: MagicMock())
    monkeypatch.setattr("nqcockpit.data.db.get_latest_snapshot", lambda c: None)
    assert run._rule_level({"level_touch_pts": 10}, {}, datetime.now(UTC), "db", fr=False) == []


def test_dedupe_cooldown(monkeypatch):
    sent: list = []
    monkeypatch.setattr(run, "send_telegram_message", _ok_send(sent))
    state: dict = {}
    now = datetime.now(UTC)
    cfg = {"cooldown_min": 30, "max_per_hour": 100}
    run._dedupe_and_send(state, ["A"], cfg, now)
    run._dedupe_and_send(state, ["A"], cfg, now)
    assert sent == ["A"]


def test_dedupe_hourly_cap(monkeypatch):
    sent: list = []
    monkeypatch.setattr(run, "send_telegram_message", _ok_send(sent))
    state: dict = {}
    now = datetime.now(UTC)
    cfg = {"cooldown_min": 0, "max_per_hour": 1}
    run._dedupe_and_send(state, ["A", "B"], cfg, now)
    assert sent == ["A"]


def test_quiet_hours():
    cfg = {"quiet_start": "00:30", "quiet_end": "08:00"}
    assert run._in_quiet_hours(cfg, datetime(2026, 10, 31, 1, 0, tzinfo=UTC)) is True
    assert run._in_quiet_hours(cfg, datetime(2026, 10, 31, 12, 0, tzinfo=UTC)) is False


def test_no_secret_in_logs(monkeypatch, caplog):
    sent: list = []
    monkeypatch.setattr(run, "send_telegram_message", _ok_send(sent))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET_TOKEN_XYZ")
    state: dict = {}
    with caplog.at_level("INFO", logger="nqcockpit.alerts"):
        run._dedupe_and_send(
            state, ["Alerte neutre"], {"cooldown_min": 0, "max_per_hour": 10}, datetime.now(UTC)
        )
    assert all("SECRET_TOKEN_XYZ" not in r.getMessage() for r in caplog.records)
