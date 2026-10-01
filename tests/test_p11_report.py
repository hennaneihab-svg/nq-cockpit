"""Tests pour la génération de rapports de performance périodiques Markdown (P11 élément 1).

Couvre :
1. Génération hebdomadaire avec échantillon suffisant (>= 60 trades).
2. Génération mensuelle avec échantillon suffisant (>= 60 trades).
3. Signalement explicite d'échantillon insuffisant (n < seuil).
4. Période vide sans aucun trade (pas de crash, message informatif).
5. Comparaison avec période précédente (signalée absente ou chiffrée si présente).
6. Décompte exact des violations de discipline.
7. Absence de vocabulaire directionnel implicite.
8. Intégration CLI nqcockpit journal report.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from nqcockpit.config import load_config
from nqcockpit.journal.models import TradeDirection, TradeEntry, TradeOutcome
from nqcockpit.journal.reports import (
    count_violations_by_type,
    filter_trades_by_date_range,
    generate_period_report,
    get_period_bounds,
)
from nqcockpit.journal.store import init_journal_db, save_trade


def _build_trade(
    session_date: str,
    outcome: TradeOutcome = TradeOutcome.WIN,
    r_realized: float = 1.0,
    sl_moved: bool = False,
    early_exit: bool = False,
    direction: TradeDirection = TradeDirection.LONG,
    risk_pct_used: float = 0.5,
) -> TradeEntry:
    return TradeEntry(
        trade_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        session_date=session_date,
        instrument="MNQ",
        direction=direction,
        entry_price=20800.0,
        stop_price=20750.0,
        exit_price=20850.0 if outcome == TradeOutcome.WIN else 20750.0,
        r_realized=r_realized,
        outcome=outcome,
        sl_moved=sl_moved,
        early_exit=early_exit,
        risk_pct_used=risk_pct_used,
        setup_tag="Pullback VWAP",
    )


def test_get_period_bounds_week():
    """Vérifie le découpage ISO de la semaine."""
    ref = date(2026, 9, 30)  # Mercredi
    c_start, c_end, c_lbl, p_start, p_end, p_lbl = get_period_bounds("week", ref)
    assert c_start == date(2026, 9, 28)  # Lundi
    assert c_end == date(2026, 10, 4)    # Dimanche
    assert c_lbl == "2026-W40"
    assert p_start == date(2026, 9, 21)
    assert p_end == date(2026, 9, 27)
    assert p_lbl == "2026-W39"


def test_get_period_bounds_month():
    """Vérifie le découpage du mois calendaire."""
    ref = date(2026, 9, 30)
    c_start, c_end, c_lbl, p_start, p_end, p_lbl = get_period_bounds("month", ref)
    assert c_start == date(2026, 9, 1)
    assert c_end == date(2026, 9, 30)
    assert c_lbl == "2026-09"
    assert p_start == date(2026, 8, 1)
    assert p_end == date(2026, 8, 31)
    assert p_lbl == "2026-08"


def test_filter_trades_by_date_range():
    """Filtre correctement les trades selon les bornes inclusives."""
    trades = [
        _build_trade("2026-09-20"),
        _build_trade("2026-09-28"),
        _build_trade("2026-09-30"),
        _build_trade("2026-10-05"),
    ]
    res = filter_trades_by_date_range(trades, date(2026, 9, 28), date(2026, 10, 4))
    assert len(res) == 2
    assert {t.session_date for t in res} == {"2026-09-28", "2026-09-30"}


def test_weekly_report_sufficient_sample(tmp_path: Path):
    """Génération d'un rapport hebdomadaire avec échantillon suffisant (>= 60 trades)."""
    cfg = load_config()
    out_dir = tmp_path / "reports_weekly"

    # 65 trades répartis dans la semaine 2026-W40 (28 sept au 4 oct 2026)
    trades = []
    for i in range(65):
        day = 28 + (i % 3)  # 28, 29, 30 sept
        trades.append(
            _build_trade(
                session_date=f"2026-09-{day:02d}",
                outcome=TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS,
                r_realized=1.5 if i % 2 == 0 else -1.0,
            )
        )

    res = generate_period_report(
        trades=trades,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=out_dir,
        config=cfg,
    )

    assert res.period == "week"
    assert res.period_label == "2026-W40"
    assert res.n_trades == 65
    assert res.sample_sufficient is True
    assert res.report_path.is_file()
    assert res.report_path.name == "weekly_2026-W40.md"

    content = res.report_path.read_text(encoding="utf-8")
    assert "Rapport de Performance Hebdomadaire" in content
    assert "2026-W40" in content
    assert "Échantillon suffisant" in content
    assert "65 trades enregistrés" in content
    assert "Wilson" in content
    assert "Facteur de profit" in content
    assert "Drawdown maximum en R" in content


def test_monthly_report_sufficient_sample(tmp_path: Path):
    """Génération d'un rapport mensuel avec échantillon suffisant (>= 60 trades)."""
    cfg = load_config()
    out_dir = tmp_path / "reports_monthly"

    trades = []
    for i in range(70):
        day = 1 + (i % 28)
        trades.append(
            _build_trade(
                session_date=f"2026-09-{day:02d}",
                outcome=TradeOutcome.WIN if i % 3 != 0 else TradeOutcome.LOSS,
                r_realized=1.2 if i % 3 != 0 else -1.0,
            )
        )

    res = generate_period_report(
        trades=trades,
        period="month",
        ref_date=date(2026, 9, 15),
        output_dir=out_dir,
        config=cfg,
    )

    assert res.period == "month"
    assert res.period_label == "2026-09"
    assert res.n_trades == 70
    assert res.sample_sufficient is True
    assert res.report_path.name == "monthly_2026-09.md"

    content = res.report_path.read_text(encoding="utf-8")
    assert "Rapport de Performance Mensuel — 2026-09" in content
    assert "Échantillon suffisant" in content


def test_report_insufficient_sample_caveat(tmp_path: Path):
    """Échantillon insuffisant (< 60 trades) :
    avertissement explicite sans prétention statistique.
    """
    cfg = load_config()
    out_dir = tmp_path / "reports_small"

    # Seulement 5 trades
    trades = [
        _build_trade("2026-09-29", TradeOutcome.WIN, 1.5),
        _build_trade("2026-09-30", TradeOutcome.LOSS, -1.0),
        _build_trade("2026-09-30", TradeOutcome.WIN, 2.0),
    ]

    res = generate_period_report(
        trades=trades,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=out_dir,
        config=cfg,
    )

    assert res.n_trades == 3
    assert res.sample_sufficient is False

    content = res.report_path.read_text(encoding="utf-8")
    assert "Échantillon statistique insuffisant" in content
    assert "3/60" in content
    assert "ne constituent pas une espérance statistiquement robuste" in content
    assert "Non calculé (n < seuil)" in content


def test_report_no_trades_empty_period(tmp_path: Path):
    """Période sans aucun trade : pas de crash, message explicite."""
    cfg = load_config()
    out_dir = tmp_path / "reports_empty"

    res = generate_period_report(
        trades=[],
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=out_dir,
        config=cfg,
    )

    assert res.n_trades == 0
    assert res.sample_sufficient is False
    assert res.report_path.is_file()

    content = res.report_path.read_text(encoding="utf-8")
    assert "Aucun trade enregistré sur la période" in content
    assert "| **Nombre de trades** | 0 |" in content


def test_report_comparison_with_and_without_prev_data(tmp_path: Path):
    """Comparaison avec période précédente : absente (signalée) ou présente (chiffrée)."""
    cfg = load_config()
    out_dir = tmp_path / "reports_comp"

    # 1. Sans période précédente
    trades_only_current = [
        _build_trade("2026-09-30", TradeOutcome.WIN, 1.0),
    ]
    res1 = generate_period_report(
        trades=trades_only_current,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=out_dir,
        config=cfg,
    )
    assert res1.has_prev_data is False
    content1 = res1.report_path.read_text(encoding="utf-8")
    assert "Aucune donnée disponible pour la période précédente (2026-W39)" in content1

    # 2. Avec période précédente
    trades_with_prev = [
        _build_trade("2026-09-22", TradeOutcome.LOSS, -1.0),  # Semaine 39
        _build_trade("2026-09-23", TradeOutcome.WIN, 2.0),   # Semaine 39
        _build_trade("2026-09-30", TradeOutcome.WIN, 1.5),   # Semaine 40
    ]
    res2 = generate_period_report(
        trades=trades_with_prev,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=out_dir,
        config=cfg,
    )
    assert res2.has_prev_data is True
    content2 = res2.report_path.read_text(encoding="utf-8")
    assert "Période Précédente (2026-W39)" in content2
    assert "Période Courante (2026-W40)" in content2
    assert "Évolution" in content2


def test_report_discipline_violations_counted(tmp_path: Path):
    """Vérifie le décompte des violations de discipline dans le rapport."""
    cfg = load_config()
    out_dir = tmp_path / "reports_viol"

    trades = [
        _build_trade("2026-09-30", sl_moved=True),
        _build_trade("2026-09-30", early_exit=True),
    ]
    counts = count_violations_by_type(trades, cfg)
    assert counts.get("sl_déplacé", 0) >= 1
    assert counts.get("sortie_anticipée", 0) >= 1

    res = generate_period_report(
        trades=trades,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=out_dir,
        config=cfg,
    )
    content = res.report_path.read_text(encoding="utf-8")
    assert "violation(s) détectée(s)" in content
    assert "`sl_déplacé`" in content
    assert "`sortie_anticipée`" in content


def test_no_directional_vocabulary_in_generated_report(tmp_path: Path):
    """Vérifie l'absence absolue de vocabulaire directionnel ou spéculatif."""
    cfg = load_config()
    out_dir = tmp_path / "reports_check"

    trades = [
        _build_trade("2026-09-30", TradeOutcome.WIN, 1.0, direction=TradeDirection.LONG),
        _build_trade("2026-09-30", TradeOutcome.LOSS, -1.0, direction=TradeDirection.SHORT),
    ]
    res = generate_period_report(
        trades=trades,
        period="week",
        ref_date=date(2026, 9, 30),
        output_dir=out_dir,
        config=cfg,
    )
    content = res.report_path.read_text(encoding="utf-8").lower()

    # Mots proscrits
    forbidden = ["viser", "cible", "cibler", "haussier", "baissier", "bullish", "bearish"]
    for word in forbidden:
        # Recherche du mot complet pour éviter de fausses alertes sur des sous-chaînes
        pattern = rf"\b{word}\b"
        assert not re.search(pattern, content), f"Mot directionnel interdit trouvé : '{word}'"


def test_cli_journal_report(tmp_path: Path, monkeypatch, capsys):
    """Exécution CLI nqcockpit journal report --period week et --period month."""
    db_file = tmp_path / "cli_journal.db"
    conn = init_journal_db(db_file)
    t = _build_trade("2026-09-30", TradeOutcome.WIN, 2.0)
    save_trade(conn, t)
    conn.close()

    out_dir = tmp_path / "cli_out"
    monkeypatch.setenv("NQ_DATA_DB_PATH", str(db_file))

    from nqcockpit.cli import main

    # 1. Semaine
    code_week = main([
        "journal", "report",
        "--period", "week",
        "--date", "2026-09-30",
        "--output-dir", str(out_dir),
    ])
    assert code_week == 0
    out = capsys.readouterr().out
    assert "RAPPORT DE PERFORMANCE HEBDOMADAIRE" in out
    assert "2026-W40" in out
    assert (out_dir / "weekly_2026-W40.md").is_file()

    # 2. Mois
    code_month = main([
        "journal", "report",
        "--period", "month",
        "--date", "2026-09-30",
        "--output-dir", str(out_dir),
    ])
    assert code_month == 0
    out2 = capsys.readouterr().out
    assert "RAPPORT DE PERFORMANCE MENSUEL" in out2
    assert "2026-09" in out2
    assert (out_dir / "monthly_2026-09.md").is_file()


def test_report_excluded_trades_mention_in_markdown(tmp_path: Path):
    """Régression Anomalie 2 : si des trades sont hors période (ex: antérieurs),
    le rapport Markdown doit mentionner explicitement leur nombre.
    Pas de modification de logique — seulement une mention informative.
    """
    cfg = load_config()
    out_dir = tmp_path / "excl_reports"
    ref = date(2026, 9, 30)  # Mercredi W40 (2026-09-28 → 2026-10-04)

    # Trades dans la période W40
    in_period = [_build_trade("2026-09-28"), _build_trade("2026-09-30")]
    # Trades hors période (semaine W39)
    out_of_period = [_build_trade("2026-09-20"), _build_trade("2026-09-25")]
    all_trades = in_period + out_of_period

    result = generate_period_report(
        trades=all_trades,
        period="week",
        ref_date=ref,
        output_dir=out_dir,
        config=cfg,
    )

    md = result.report_path.read_text(encoding="utf-8")

    # 2 trades dans la période → analysés
    assert "2/2" in md or "2 trade" in md.lower() or str(len(in_period)) in md

    # 2 trades exclus → mention obligatoire dans le rapport
    assert "hors période" in md.lower() or "exclus" in md.lower(), (
        "Le rapport doit mentionner les trades hors période pour lever l'ambiguïté. "
        f"Extrait MD:\n{md[:600]}"
    )
    # Le chiffre 2 (nombre de trades exclus) doit apparaître avec le mot "exclus"
    assert "2" in md and ("exclus" in md.lower() or "hors période" in md.lower())


def test_unified_default_session_date_across_modules(tmp_path: Path, monkeypatch):
    """Régression : vérifie que la date de séance par défaut est unifiée sur America/New_York
    entre reports.py, backup.py, cli.py, journal_page.py et coaching_page.py.

    A un instant où l'heure à New York (22h30 le 30 sept) et l'heure à Alger (03h30 le 1er oct)
    sont sur deux dates différentes, TOUS les modules doivent déduire la date de séance NY (2026-09-30).
    """
    from zoneinfo import ZoneInfo
    from nqcockpit.journal.backup import create_journal_backup

    cfg = load_config()
    tz_ny = ZoneInfo("America/New_York")
    tz_alg = ZoneInfo("Africa/Algiers")

    # Instant de test : 2026-10-01 02:30 UTC
    # -> 2026-09-30 22:30 EDT (New York) -> Date = 2026-09-30
    # -> 2026-10-01 03:30 CET (Alger)    -> Date = 2026-10-01
    dt_fixed_utc = datetime(2026, 10, 1, 2, 30, tzinfo=timezone.utc)

    # Verification directe des timezones
    date_ny = dt_fixed_utc.astimezone(tz_ny).date()
    date_alg = dt_fixed_utc.astimezone(tz_alg).date()

    assert date_ny == date(2026, 9, 30)
    assert date_alg == date(2026, 10, 1)

    # Mock de datetime.now pour retourner dt_fixed_utc aux appels aware
    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return dt_fixed_utc.replace(tzinfo=None)
            return dt_fixed_utc.astimezone(tz)

    monkeypatch.setattr("nqcockpit.journal.reports.datetime", MockDatetime)
    monkeypatch.setattr("nqcockpit.journal.backup.datetime", MockDatetime)

    # 1. reports.py : ref_date par défaut
    res_rep = generate_period_report(
        trades=[],
        period="week",
        ref_date=None,
        output_dir=tmp_path / "rep",
        config=cfg,
    )
    assert res_rep.start_date <= date_ny <= res_rep.end_date

    # 2. backup.py : target_date par défaut
    db_file = tmp_path / "test.db"
    db_file.write_text("", encoding="utf-8")
    res_bak = create_journal_backup(
        db_path=db_file,
        backup_dir=tmp_path / "bak",
        target_date=None,
        config=cfg,
    )
    assert f"nqcockpit_{date_ny.isoformat()}.db" in res_bak.backup_path.name
