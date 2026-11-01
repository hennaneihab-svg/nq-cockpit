"""Tests de l'alerteur Telegram autonome (HTTP et données mockés, sans réseau)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nqcockpit.alerts import run
from nqcockpit.briefing.models import TelegramResult
from nqcockpit.discipline.models import SessionDisciplineStatus
from nqcockpit.events.models import CalendarEvent, DataStatus, SourceHealth

UTC = timezone.utc


def _ok_send(record: list):
    def _send(msg):
        record.append(msg)
        return TelegramResult(status="OK", sent=True)

    return _send


def _discipline_fake(status: SessionDisciplineStatus):
    return SimpleNamespace(status=status, can_trade=status == SessionDisciplineStatus.READY)


# --- Règle événement -------------------------------------------------------


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
    assert "Scheduled event" in msgs[0]


def test_rule_event_french_text():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    report = SimpleNamespace(
        events=[CalendarEvent(name="CPI", tier=1, scheduled_utc=now + timedelta(minutes=5),
                              source="x", status=DataStatus.OK)],
        source_health=[],
    )
    msgs = run._rule_event({"event_window_min": 15}, report, now, fr=True)
    assert "Événement programmé" in msgs[0]


def test_rule_event_missing_source_skips():
    report = SimpleNamespace(events=None, source_health=[])
    assert run._rule_event({"event_window_min": 15}, report, datetime.now(UTC), fr=False) == []


# --- Règle source ----------------------------------------------------------


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
    assert msgs == ["Source fed: DEGRADED → OK"]
    # état stocké en code, pas en libellé français
    assert state["source_state"]["fed"] == "OK"


def test_rule_source_french_labels_and_legacy_state():
    state = {"source_state": {"fed": "DÉGRADÉ"}}
    report = SimpleNamespace(
        events=[], source_health=[SourceHealth(source="fed", status=DataStatus.OK)]
    )
    msgs = run._rule_source(state, report, datetime.now(UTC), fr=True)
    assert msgs == ["Source fed : DÉGRADÉ → OK"]


def test_rule_source_blocked_label():
    state = {"source_state": {"bls": "OK"}}
    report = SimpleNamespace(
        events=[], source_health=[SourceHealth(source="bls", status=DataStatus.BLOCKED)]
    )
    assert run._rule_source(state, report, datetime.now(UTC), fr=False) == [
        "Source bls: OK → DOWN"
    ]
    state = {"source_state": {"bls": "OK"}}
    assert run._rule_source(state, report, datetime.now(UTC), fr=True) == [
        "Source bls : OK → HORS LIGNE"
    ]


# --- Règle MT5 -------------------------------------------------------------


def _patch_mt5(monkeypatch, is_ok: bool):
    class _FakeStatus:
        pass

    status = _FakeStatus()
    status.is_ok = is_ok

    class _FakeClient:
        def get_status(self):
            return status

    monkeypatch.setattr("nqcockpit.broker.mt5_client.MT5Client", lambda: _FakeClient())


def test_rule_mt5_alerts_on_change_only(monkeypatch):
    _patch_mt5(monkeypatch, False)
    state = {"mt5_connected": True}
    assert run._rule_mt5(state, datetime.now(UTC), fr=False) == ["MT5 disconnected"]
    # pas de changement -> pas d'alerte
    assert run._rule_mt5(state, datetime.now(UTC), fr=False) == []


def test_rule_mt5_french(monkeypatch):
    _patch_mt5(monkeypatch, True)
    state = {"mt5_connected": False}
    assert run._rule_mt5(state, datetime.now(UTC), fr=True) == ["MT5 connecté"]


# --- Règle discipline ------------------------------------------------------


def _patch_discipline(monkeypatch, status: SessionDisciplineStatus):
    fake = _discipline_fake(status)
    monkeypatch.setattr(
        "nqcockpit.discipline.engine.evaluate_session_state", lambda t, n, c: fake
    )
    monkeypatch.setattr("nqcockpit.journal.store.init_journal_db", lambda p: MagicMock())
    monkeypatch.setattr("nqcockpit.journal.store.load_trades", lambda c: [])


@pytest.mark.parametrize(
    "status, en, fr",
    [
        (
            SessionDisciplineStatus.LOCKED_DAILY_LOSS,
            "Discipline lock active: daily loss limit reached.",
            "Verrou discipline actif : limite de perte journalière atteinte.",
        ),
        (
            SessionDisciplineStatus.LOCKED_TRADE1_LOSS,
            "Discipline lock active: first-trade loss / tilt lock.",
            "Verrou discipline actif : tilt / premier trade perdant.",
        ),
        (
            SessionDisciplineStatus.LOCKED_MAX_TRADES,
            "Discipline lock active: max trades reached.",
            "Verrou discipline actif : nombre maximal de trades atteint.",
        ),
    ],
)
def test_rule_discipline_real_locks(monkeypatch, status, en, fr):
    _patch_discipline(monkeypatch, status)
    state = {"discipline_locked": False}
    assert run._rule_discipline(state, datetime.now(UTC), None, "db", fr=False) == [en]
    state = {"discipline_locked": False}
    assert run._rule_discipline(state, datetime.now(UTC), None, "db", fr=True) == [fr]


def test_rule_discipline_out_of_window_never_alerts(monkeypatch):
    _patch_discipline(monkeypatch, SessionDisciplineStatus.OUT_OF_WINDOW)
    state = {"discipline_locked": False}
    assert run._rule_discipline(state, datetime.now(UTC), None, "db", fr=False) == []
    # un ancien verrou déjà levé ne produit pas de message hors fenêtre
    state = {"discipline_locked": True}
    assert run._rule_discipline(state, datetime.now(UTC), None, "db", fr=False) == []


def test_rule_discipline_cooldown_does_not_alert(monkeypatch):
    _patch_discipline(monkeypatch, SessionDisciplineStatus.COOLDOWN_ACTIVE)
    state = {"discipline_locked": False}
    assert run._rule_discipline(state, datetime.now(UTC), None, "db", fr=False) == []


def test_rule_discipline_clear_message(monkeypatch):
    _patch_discipline(monkeypatch, SessionDisciplineStatus.READY)
    state = {"discipline_locked": True}
    assert run._rule_discipline(state, datetime.now(UTC), None, "db", fr=False) == [
        "Discipline lock cleared"
    ]
    state = {"discipline_locked": True}
    assert run._rule_discipline(state, datetime.now(UTC), None, "db", fr=True) == [
        "Verrou discipline levé"
    ]


def test_rule_discipline_no_engine_french_text(monkeypatch):
    _patch_discipline(monkeypatch, SessionDisciplineStatus.LOCKED_DAILY_LOSS)
    msg = run._rule_discipline({}, datetime.now(UTC), None, "db", fr=False)[0]
    assert "Limite de perte" not in msg
    assert "Séance verrouillée" not in msg


# --- Règle niveau ----------------------------------------------------------


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
    assert msgs == ["Price 5 pts from Call Wall 20,800"]
    # une fois par niveau par jour -> rien au second passage
    assert run._rule_level({"level_touch_pts": 10}, state, now, "db", fr=False) == []


def test_rule_level_french(monkeypatch):
    monkeypatch.setattr("nqcockpit.data.db.get_db_connection", lambda p: MagicMock())
    monkeypatch.setattr(
        "nqcockpit.data.db.get_latest_snapshot",
        lambda c: {"call_wall": 20800.0, "gamma_flip": None, "put_support": None},
    )
    monkeypatch.setattr(run, "_last_nq_price", lambda now: 20795.0)
    msgs = run._rule_level({"level_touch_pts": 10}, {}, datetime.now(UTC), "db", fr=True)
    assert msgs == ["Prix à 5 pts de Call Wall 20,800"]


def test_rule_level_missing_snapshot_skips(monkeypatch):
    monkeypatch.setattr("nqcockpit.data.db.get_db_connection", lambda p: MagicMock())
    monkeypatch.setattr("nqcockpit.data.db.get_latest_snapshot", lambda c: None)
    assert run._rule_level({"level_touch_pts": 10}, {}, datetime.now(UTC), "db", fr=False) == []


# --- Langue ----------------------------------------------------------------


def test_lang_env_default_en_and_fallback(monkeypatch):
    monkeypatch.delenv("ALERT_LANG", raising=False)
    assert run._lang() == "EN"
    monkeypatch.setenv("ALERT_LANG", "fr")
    assert run._lang() == "FR"
    monkeypatch.setenv("ALERT_LANG", "de")
    assert run._lang() == "EN"


def test_no_french_text_in_en_mode():
    now = datetime.now(UTC)
    event_msg = run._rule_event(
        {"event_window_min": 15},
        SimpleNamespace(
            events=[CalendarEvent(name="CPI", tier=1,
                                  scheduled_utc=now + timedelta(minutes=5),
                                  source="x", status=DataStatus.OK)]
        ),
        now,
        fr=False,
    )[0]
    joined = " ".join(
        [
            event_msg,
            "MT5 disconnected",
            run._t("EN", "discipline.reason.LOCKED_DAILY_LOSS"),
            run._t("EN", "status.DEGRADED"),
        ]
    )
    for word in ("Événement", "Verrou", "DÉGRADÉ", "connecté", "journalière"):
        assert word not in joined


# --- Déduplication ---------------------------------------------------------


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


# --- Heures calmes / fuseau ------------------------------------------------


def test_tz_algiers_utc_plus_one():
    assert run.TZ_ALGIERS.utcoffset(datetime(2026, 11, 1, 0, 0)).total_seconds() == 3600


def test_quiet_hours_algiers():
    cfg = {"quiet_start": "00:30", "quiet_end": "08:00"}
    # 01:30 heure d'Alger = 00:30 UTC -> supprimé
    assert run._in_quiet_hours(cfg, datetime(2026, 11, 1, 0, 30, tzinfo=UTC)) is True
    assert run._in_quiet_hours(cfg, datetime(2026, 11, 1, 1, 0, tzinfo=UTC)) is True
    # 08:00 heure d'Alger = 07:00 UTC -> borne de fin exclusive = envoyé
    assert run._in_quiet_hours(cfg, datetime(2026, 11, 1, 7, 0, tzinfo=UTC)) is False
    # 09:00 heure d'Alger = 08:00 UTC -> envoyé
    assert run._in_quiet_hours(cfg, datetime(2026, 11, 1, 8, 0, tzinfo=UTC)) is False


def test_quiet_hours_overnight_window():
    cfg = {"quiet_start": "22:00", "quiet_end": "06:00"}
    assert run._in_quiet_hours(cfg, datetime(2026, 11, 1, 23, 0, tzinfo=UTC)) is True
    assert run._in_quiet_hours(cfg, datetime(2026, 11, 1, 10, 0, tzinfo=UTC)) is False


class _FixedDateTime(datetime):
    fixed: datetime = datetime(2026, 11, 1, 0, 30, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls.fixed.astimezone(tz)
        return cls.fixed.replace(tzinfo=None)


def _patch_evaluate(monkeypatch, sent: list, fixed: datetime):
    class _DT(_FixedDateTime):
        pass

    _DT.fixed = fixed
    monkeypatch.setattr(run, "datetime", _DT)
    monkeypatch.setattr(run, "_setup_logging", lambda: None)
    monkeypatch.setattr(
        run,
        "load_config",
        lambda: SimpleNamespace(
            data=SimpleNamespace(db_path="db"), ui=SimpleNamespace(language="FR")
        ),
    )
    monkeypatch.setattr(run, "_load_state", lambda p: {})
    monkeypatch.setattr(run, "_save_state", lambda p, s: None)
    monkeypatch.setattr(run, "_rule_mt5", lambda state, now, fr: ["MT5 disconnected"])
    monkeypatch.setattr(run, "send_telegram_message", _ok_send(sent))
    monkeypatch.setenv("ALERT_ENABLED_RULES", "mt5")
    monkeypatch.delenv("ALERT_LANG", raising=False)
    monkeypatch.delenv("ALERT_QUIET_START", raising=False)
    monkeypatch.delenv("ALERT_QUIET_END", raising=False)


def test_evaluate_suppresses_message_at_0130_algiers(monkeypatch):
    sent: list = []
    _patch_evaluate(monkeypatch, sent, datetime(2026, 11, 1, 0, 30, tzinfo=UTC))  # 01:30 Alger
    assert run.evaluate() == 0
    assert sent == []


def test_evaluate_sends_message_at_0900_algiers(monkeypatch):
    sent: list = []
    _patch_evaluate(monkeypatch, sent, datetime(2026, 11, 1, 8, 0, tzinfo=UTC))  # 09:00 Alger
    assert run.evaluate() == 0
    assert sent == ["MT5 disconnected"]


# --- Secrets ---------------------------------------------------------------


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
