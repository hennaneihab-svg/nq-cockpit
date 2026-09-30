"""Tests pour les patterns de tilt étendus (P11 élément 2).

Vérifie :
1. Sur-trading : cas positif (> max_trades_per_day) et négatif (<= max_trades_per_day).
2. Vengeance trading : cas positif (< vengeance_minutes après perte) et négatif.
3. Taille de position anormale : cas positif (>= multiplier * moyenne) et négatif.
4. Accélération de fréquence : cas positif (> N trades en <= M minutes glissantes) et négatif.
5. Pertes consécutives : cas positif (2 pertes consécutives) et négatif (gains/alternance).
6. Absence stricte de vocabulaire émotionnel, de diagnostic ou de jugement moral.
7. Intégration dans le rapport de performance périodique Markdown (section Patterns de tilt).
"""

from __future__ import annotations

import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from nqcockpit.config import load_config
from nqcockpit.journal.engine import detect_period_tilt_alerts, detect_tilt_alerts
from nqcockpit.journal.importer import import_trades_from_csv
from nqcockpit.journal.models import (
    TradeDirection,
    TradeEntry,
    TradeOutcome,
)
from nqcockpit.journal.reports import generate_period_report
from nqcockpit.journal.store import init_journal_db, load_trades


def _make_trade(
    session_date: str = "2026-09-30",
    outcome: TradeOutcome = TradeOutcome.WIN,
    contracts: int = 1,
    minutes_after_last_sl: float | None = None,
    entry_time: datetime | None = None,
    exit_time: datetime | None = None,
    r_realized: float = 1.0,
    trade_id: str | None = None,
) -> TradeEntry:
    t_id = trade_id or str(uuid.uuid4())
    rec_time = entry_time or datetime.now(timezone.utc)
    return TradeEntry(
        trade_id=t_id,
        recorded_at=rec_time,
        session_date=session_date,
        instrument="MNQ",
        direction=TradeDirection.LONG,
        entry_price=20800.0,
        stop_price=20750.0,
        exit_price=20850.0 if outcome == TradeOutcome.WIN else 20750.0,
        outcome=outcome,
        r_realized=r_realized if outcome == TradeOutcome.WIN else -1.0,
        contracts=contracts,
        minutes_after_last_sl=minutes_after_last_sl,
        entry_time_ny=entry_time,
        exit_time_ny=exit_time,
        setup_tag="VWAP Pullback",
    )


# ---------------------------------------------------------------------------
# 1. Sur-trading
# ---------------------------------------------------------------------------


def test_tilt_overtrading_positive():
    """3 trades sur la même séance (seuil max = 2) → alerte sur-trading."""
    cfg = load_config()
    t1 = _make_trade(session_date="2026-09-30")
    t2 = _make_trade(session_date="2026-09-30")
    t3 = _make_trade(session_date="2026-09-30")

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2, t3], cfg)
    types = [a.pattern_type for a in alerts]
    assert "surtrading" in types
    over_alert = next(a for a in alerts if a.pattern_type == "surtrading")
    assert "3 trades enregistrés" in over_alert.reason
    assert "2 trades/jour max" in over_alert.reason
    assert len(over_alert.trades_involved) == 3


def test_tilt_overtrading_negative():
    """2 trades sur la même séance (seuil max = 2) → aucune alerte sur-trading."""
    cfg = load_config()
    t1 = _make_trade(session_date="2026-09-30")
    t2 = _make_trade(session_date="2026-09-30")

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], cfg)
    types = [a.pattern_type for a in alerts]
    assert "surtrading" not in types


# ---------------------------------------------------------------------------
# 2. Vengeance trading
# ---------------------------------------------------------------------------


def test_tilt_vengeance_trading_positive():
    """Nouveau trade pris 10 minutes après une perte (seuil configuré = 30 min) → alerte."""
    cfg = load_config()
    t_base = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    t1 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.LOSS,
        entry_time=t_base,
        exit_time=t_base + timedelta(minutes=15),
    )
    t2 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.WIN,
        entry_time=t_base + timedelta(minutes=25),  # 10 min après sortie t1
    )

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], cfg)
    types = [a.pattern_type for a in alerts]
    assert "vengeance_trading" in types
    v_alert = next(a for a in alerts if a.pattern_type == "vengeance_trading")
    assert "10.0 min après une perte" in v_alert.reason
    assert "< 30 min" in v_alert.reason
    assert v_alert.trades_involved == [t1.trade_id, t2.trade_id]


def test_tilt_vengeance_trading_negative_sufficient_pause():
    """Nouveau trade pris 45 minutes après une perte (>= 30 min) → pas d'alerte."""
    cfg = load_config()
    t_base = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    t1 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.LOSS,
        entry_time=t_base,
        exit_time=t_base + timedelta(minutes=15),
    )
    t2 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.WIN,
        entry_time=t_base + timedelta(minutes=60),  # 45 min après sortie t1
    )

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], cfg)
    types = [a.pattern_type for a in alerts]
    assert "vengeance_trading" not in types


def test_tilt_vengeance_trading_negative_after_win():
    """Nouveau trade pris 5 minutes après un WIN → pas d'alerte vengeance trading."""
    cfg = load_config()
    t_base = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    t1 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.WIN,
        entry_time=t_base,
        exit_time=t_base + timedelta(minutes=15),
    )
    t2 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.WIN,
        entry_time=t_base + timedelta(minutes=20),
    )

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], cfg)
    types = [a.pattern_type for a in alerts]
    assert "vengeance_trading" not in types


# ---------------------------------------------------------------------------
# 3. Taille de position anormale
# ---------------------------------------------------------------------------


def test_tilt_abnormal_size_positive():
    """Trade de 3 contrats avec moyenne période à 1.4 contrat (seuil 1.5x) → alerte."""
    cfg = load_config()
    # 4 trades de 1 contrat et 1 trade de 3 contrats → moyenne = 7/5 = 1.40.
    # 1.40 * 1.5 = 2.10. 3 >= 2.10 → alerte.
    trades = [
        _make_trade(session_date="2026-09-28", contracts=1),
        _make_trade(session_date="2026-09-29", contracts=1),
        _make_trade(session_date="2026-09-29", contracts=1),
        _make_trade(session_date="2026-09-30", contracts=1),
        _make_trade(session_date="2026-09-30", contracts=3),
    ]

    alerts = detect_period_tilt_alerts(trades, cfg)
    types = [a.pattern_type for a in alerts]
    assert "taille_anormale" in types
    size_alert = next(a for a in alerts if a.pattern_type == "taille_anormale")
    assert "3 contrat(s) exécuté(s)" in size_alert.reason
    assert "1.40 contrat(s)" in size_alert.reason
    assert ">= 1.5x" in size_alert.reason
    assert size_alert.trades_involved == [trades[-1].trade_id]


def test_tilt_abnormal_size_negative():
    """Tous les trades ont la même taille (1 contrat) → pas d'alerte."""
    cfg = load_config()
    trades = [
        _make_trade(session_date="2026-09-28", contracts=1),
        _make_trade(session_date="2026-09-29", contracts=1),
        _make_trade(session_date="2026-09-30", contracts=1),
    ]

    alerts = detect_period_tilt_alerts(trades, cfg)
    types = [a.pattern_type for a in alerts]
    assert "taille_anormale" not in types


# ---------------------------------------------------------------------------
# 4. Accélération de fréquence
# ---------------------------------------------------------------------------


def test_tilt_frequency_acceleration_positive():
    """4 trades en 20 minutes (seuil configuré : > 3 trades en 45 min) → alerte."""
    cfg = load_config()
    t_base = datetime(2026, 9, 30, 15, 30, tzinfo=timezone.utc)
    t1 = _make_trade(session_date="2026-09-30", entry_time=t_base)
    t2 = _make_trade(session_date="2026-09-30", entry_time=t_base + timedelta(minutes=5))
    t3 = _make_trade(session_date="2026-09-30", entry_time=t_base + timedelta(minutes=12))
    t4 = _make_trade(session_date="2026-09-30", entry_time=t_base + timedelta(minutes=20))

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2, t3, t4], cfg)
    types = [a.pattern_type for a in alerts]
    assert "accélération_fréquence" in types
    freq_alert = next(a for a in alerts if a.pattern_type == "accélération_fréquence")
    assert "4 trades exécutés en 20.0 min" in freq_alert.reason
    assert "> 3 trades en 45 min" in freq_alert.reason
    assert len(freq_alert.trades_involved) == 4


def test_tilt_frequency_acceleration_negative():
    """2 trades espacés de 30 minutes → pas d'alerte d'accélération."""
    cfg = load_config()
    t_base = datetime(2026, 9, 30, 15, 30, tzinfo=timezone.utc)
    t1 = _make_trade(session_date="2026-09-30", entry_time=t_base)
    t2 = _make_trade(session_date="2026-09-30", entry_time=t_base + timedelta(minutes=30))

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], cfg)
    types = [a.pattern_type for a in alerts]
    assert "accélération_fréquence" not in types


# ---------------------------------------------------------------------------
# 5. Pertes consécutives (rétention de la couverture existante)
# ---------------------------------------------------------------------------


def test_tilt_consecutive_losses_positive():
    """2 pertes consécutives → alerte factuelle."""
    cfg = load_config()
    t1 = _make_trade(session_date="2026-09-30", outcome=TradeOutcome.LOSS)
    t2 = _make_trade(session_date="2026-09-30", outcome=TradeOutcome.LOSS)

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], cfg)
    types = [a.pattern_type for a in alerts]
    assert "pertes_consécutives" in types
    loss_alert = next(a for a in alerts if a.pattern_type == "pertes_consécutives")
    assert "2 pertes consécutives détectées sur la séance" in loss_alert.reason


def test_tilt_consecutive_losses_negative():
    """1 gain et 1 perte → pas d'alerte pertes consécutives."""
    cfg = load_config()
    t1 = _make_trade(session_date="2026-09-30", outcome=TradeOutcome.WIN)
    t2 = _make_trade(session_date="2026-09-30", outcome=TradeOutcome.LOSS)

    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], cfg)
    types = [a.pattern_type for a in alerts]
    assert "pertes_consécutives" not in types


# ---------------------------------------------------------------------------
# 6. Absence de vocabulaire de jugement ou diagnostic
# ---------------------------------------------------------------------------


def test_neutrality_of_tilt_alert_messages():
    """Vérifie qu'aucun message d'alerte ne comporte de vocabulaire émotionnel ou accusateur."""
    cfg = load_config()
    t_base = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)

    # Déclencher tous les patterns simultanément
    trades = [
        _make_trade(
            session_date="2026-09-30",
            outcome=TradeOutcome.LOSS,
            contracts=1,
            entry_time=t_base,
            exit_time=t_base + timedelta(minutes=5),
        ),
        _make_trade(
            session_date="2026-09-30",
            outcome=TradeOutcome.LOSS,
            contracts=1,
            entry_time=t_base + timedelta(minutes=10),
            exit_time=t_base + timedelta(minutes=15),
        ),
        _make_trade(
            session_date="2026-09-30",
            outcome=TradeOutcome.WIN,
            contracts=1,
            entry_time=t_base + timedelta(minutes=18),
        ),
        _make_trade(
            session_date="2026-09-30",
            outcome=TradeOutcome.WIN,
            contracts=4,  # taille anormale
            entry_time=t_base + timedelta(minutes=22),
        ),
    ]

    alerts = detect_period_tilt_alerts(trades, cfg)
    assert len(alerts) >= 4  # Pertes consécutives, Sur-trading, Vengeance, Taille, Fréquence

    # Mots proscrits (jugement moral, suppositions émotionnelles)
    forbidden_terms = [
        "impulsif", "impulsive", "impulsivité", "émotionnel", "émotionnelle",
        "indiscipliné", "indiscipline", "panique", "colère", "rage",
        "danger", "faute", "grave", "incontrôlé", "incontrôlée", "mauvais",
        "mauvaise", "comportement anormal", "psychologique",
    ]

    for alert in alerts:
        reason_lower = alert.reason.lower()
        for term in forbidden_terms:
            pattern = rf"\b{term}\b"
            assert not re.search(pattern, reason_lower), (
                f"Terme de jugement interdit '{term}' détecté dans : '{alert.reason}'"
            )


# ---------------------------------------------------------------------------
# 7. Intégration dans le rapport Markdown périodique
# ---------------------------------------------------------------------------


def test_markdown_report_with_and_without_tilt(tmp_path: Path):
    """Vérifie la présence de la section Patterns de tilt dans le rapport Markdown."""
    cfg = load_config()

    # Cas A : aucun pattern de tilt
    trades_clean = [
        _make_trade(session_date="2026-09-28", outcome=TradeOutcome.WIN, contracts=1),
        _make_trade(session_date="2026-09-29", outcome=TradeOutcome.WIN, contracts=1),
    ]
    res_clean = generate_period_report(
        trades=trades_clean,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=tmp_path / "clean",
        config=cfg,
    )
    content_clean = res_clean.report_path.read_text(encoding="utf-8")
    assert "## 5. Patterns de Tilt Détectés" in content_clean
    assert "Aucun pattern de tilt détecté" in content_clean

    # Cas B : sur-trading détecté
    trades_tilt = [
        _make_trade(session_date="2026-09-28", outcome=TradeOutcome.WIN),
        _make_trade(session_date="2026-09-28", outcome=TradeOutcome.WIN),
        _make_trade(session_date="2026-09-28", outcome=TradeOutcome.WIN),
    ]
    res_tilt = generate_period_report(
        trades=trades_tilt,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=tmp_path / "tilt",
        config=cfg,
    )
    content_tilt = res_tilt.report_path.read_text(encoding="utf-8")
    assert "## 5. Patterns de Tilt Détectés" in content_tilt
    assert "pattern(s) de tilt détecté(s)" in content_tilt
    assert "surtrading" in content_tilt
    assert "Sur-trading : 3 trades enregistrés sur la séance" in content_tilt


# ---------------------------------------------------------------------------
# 8. Gestion stricte de contracts: Optional[int] = None (aucun chiffre inventé)
# ---------------------------------------------------------------------------


def test_tilt_abnormal_size_ignored_when_contracts_none():
    """Un trade avec contracts is None est purement ignoré par le pattern (pas d'alerte)."""
    cfg = load_config()
    trades = [
        _make_trade(session_date="2026-09-28", contracts=None),
        _make_trade(session_date="2026-09-29", contracts=None),
        _make_trade(session_date="2026-09-30", contracts=None),
    ]
    alerts = detect_period_tilt_alerts(trades, cfg)
    types = [a.pattern_type for a in alerts]
    assert "taille_anormale" not in types


def test_tilt_abnormal_size_mean_computed_only_on_specified_trades():
    """Moyenne calculée uniquement sur les trades avec contracts renseigné."""
    cfg = load_config()
    # 2 trades à 1 contrat, 1 trade sans contracts (None), 1 trade à 3 contrats
    # Échantillon valide : [1, 1, 3] -> moyenne = 5/3 = 1.67.
    # 1.67 * 1.5 = 2.50. 3 >= 2.50 -> alerte sur le trade à 3 contrats.
    # Le trade avec contracts=None est ignoré (ne fausse pas la moyenne).
    trades = [
        _make_trade(session_date="2026-09-28", contracts=1),
        _make_trade(session_date="2026-09-29", contracts=1),
        _make_trade(session_date="2026-09-29", contracts=None),
        _make_trade(session_date="2026-09-30", contracts=3),
    ]
    alerts = detect_period_tilt_alerts(trades, cfg)
    types = [a.pattern_type for a in alerts]
    assert "taille_anormale" in types
    size_alert = next(a for a in alerts if a.pattern_type == "taille_anormale")
    assert "3 contrat(s) exécuté(s)" in size_alert.reason
    assert "1.67 contrat(s)" in size_alert.reason
    assert size_alert.trades_involved == [trades[-1].trade_id]


def test_csv_import_without_contracts_column_emits_warning(tmp_path: Path):
    """Import CSV sans colonne contracts : contracts=None en base + warning explicite."""
    db_path = tmp_path / "test_import_no_contracts.db"
    conn = init_journal_db(db_path)

    csv_data = io.StringIO(
        "session_date,instrument,direction,entry_price,stop_price,exit_price\n"
        "2026-09-28,MNQ,LONG,20800.0,20750.0,20850.0\n"
        "2026-09-29,MNQ,SHORT,20900.0,20950.0,20800.0\n"
    )

    summary = import_trades_from_csv(csv_data, conn)
    assert summary.imported == 2
    assert "contracts" in summary.missing_optional_columns
    assert any("contracts" in w.lower() for w in summary.warnings)

    loaded = load_trades(conn)
    assert len(loaded) == 2
    assert loaded[0].contracts is None
    assert loaded[1].contracts is None
    conn.close()


def test_csv_import_with_contracts_column_preserves_values(tmp_path: Path):
    """Import CSV avec colonne contracts : valeurs entières préservées en base."""
    db_path = tmp_path / "test_import_with_contracts.db"
    conn = init_journal_db(db_path)

    csv_data = io.StringIO(
        "session_date,instrument,direction,entry_price,stop_price,exit_price,contracts\n"
        "2026-09-28,MNQ,LONG,20800.0,20750.0,20850.0,2\n"
        "2026-09-29,MNQ,SHORT,20900.0,20950.0,20800.0,5\n"
    )

    summary = import_trades_from_csv(csv_data, conn)
    assert summary.imported == 2
    assert "contracts" not in summary.missing_optional_columns

    loaded = load_trades(conn)
    assert len(loaded) == 2
    assert loaded[0].contracts == 2
    assert loaded[1].contracts == 5
    conn.close()

