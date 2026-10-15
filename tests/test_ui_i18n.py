"""Tests unitaires pour l'internationalisation (FR / EN) de l'interface NQ Cockpit."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import streamlit as st

from nqcockpit.config import load_config
from nqcockpit.journal.engine import segment_by_setup_tag
from nqcockpit.journal.models import (
    GammaRegime,
    TiltAlert,
    TradeDirection,
    TradeEntry,
    TradeOutcome,
)
from nqcockpit.ui.coaching_page import (
    build_compliance_timeline_figure,
    build_equity_curve_figure,
    build_segmentation_figure,
)
from nqcockpit.ui.components import render_degraded_banner, render_status_badge
from nqcockpit.ui.i18n import (
    LANG_SESSION_KEY,
    get_lang,
    set_lang,
    t,
    toggle_lang,
    tr_text,
)


def _sample_trade(idx: int = 1, r_val: float = 1.5, compliant: bool = True) -> TradeEntry:
    now = datetime(2026, 4, 9, 14, 0, tzinfo=UTC)
    return TradeEntry(
        trade_id=f"T-{idx:03d}",
        recorded_at=now,
        session_date="2026-04-09",
        instrument="MNQ",
        direction=TradeDirection.LONG,
        entry_price=20000.0,
        stop_price=19980.0,
        exit_price=20030.0 if r_val > 0 else 19980.0,
        r_realized=r_val,
        outcome=TradeOutcome.WIN if r_val > 0 else TradeOutcome.LOSS,
        window_name="trade1" if compliant else "",
        gamma_regime=GammaRegime.POSITIVE,
        sl_moved=not compliant,
        setup_tag="ORB",
        notes="Test trade",
    )


def test_lang_state_and_toggle() -> None:
    """Vérifie le basculement FR <-> EN et la fonction t(fr, en)."""
    st.session_state.pop(LANG_SESSION_KEY, None)
    assert get_lang() == "FR"
    assert t("Bonjour", "Hello") == "Bonjour"

    toggle_lang()
    assert get_lang() == "EN"
    assert t("Bonjour", "Hello") == "Hello"

    toggle_lang()
    assert get_lang() == "FR"
    assert t("Bonjour", "Hello") == "Bonjour"

    set_lang("en")
    assert get_lang() == "EN"
    set_lang("INVALID")
    assert get_lang() == "FR"


def test_tr_text_preserves_french_when_lang_is_fr() -> None:
    """En mode FR, tr_text ne modifie jamais la chaîne d'origine."""
    set_lang("FR")
    sample = "Attendre le franchissement de 20100 puis retest."
    assert tr_text(sample) == sample


def test_tr_text_translates_macro_radar_and_scenarios_in_en() -> None:
    """En mode EN, tr_text traduit les cartes radar, scénarios et verrous."""
    set_lang("EN")
    try:
        # Scénario conditionnel réel issu de profile/engine.py
        scen = (
            "Si le prix s'établit au-dessus du Gamma Flip (20000) et s'y maintient, "
            "alors régime d'amortissement dealer (Mean Reversion) : observer les replis "
            "vers la VWAP et éviter les poursuites impulsives tardives."
        )
        translated_scen = tr_text(scen)
        assert "If price establishes above the Gamma Flip" in translated_scen
        assert "then dealer dampening regime (Mean Reversion)" in translated_scen

        # Verrou de discipline réel issu de discipline/engine.py
        lock_msg = "Limite de perte journalière atteinte (-2.50R <= -2.00R). Séance verrouillée."
        assert "Daily loss limit reached" in tr_text(lock_msg)
        assert "Session locked." in tr_text(lock_msg)

        # Checklist
        chk_msg = "Hors fenêtre d'exécution autorisée (heure actuelle : 12:15 NY)."
        assert "Outside authorized execution window" in tr_text(chk_msg)

        # Coaching leak
        leak_msg = (
            "Trades non conformes (SL déplacé / sortie anticipée) : "
            "-4.50R, espérance=-1.50R vs conformes +0.80R"
        )
        translated_leak = tr_text(leak_msg)
        assert "Non-compliant trades (SL moved / early exit)" in translated_leak
        assert "vs compliant" in translated_leak

        # Briefing markdown
        brief_md = "# BRIEFING PRÉ-SESSION NQ — 2026-04-09\n## 1. Statut de Séance & Risque"
        translated_md = tr_text(brief_md)
        assert "# NQ PRE-SESSION BRIEFING — 2026-04-09" in translated_md
        assert "## 1. Session Status & Risk" in translated_md
    finally:
        set_lang("FR")


def test_components_bilingual_rendering() -> None:
    """Vérifie le rendu bilingue des bannières et badges dans components.py."""
    with patch("streamlit.markdown") as mock_md:
        set_lang("EN")
        try:
            render_status_badge("DEGRADED", "CBOE delayed")
            html_call = mock_md.call_args[0][0]
            assert "DEGRADED" in html_call

            render_degraded_banner(["gex: DEGRADED (CBOE error)"])
            banner_call = mock_md.call_args[0][0]
            assert "[SOURCE HEALTH WARNING — DEGRADED STATUS]" in banner_call
        finally:
            set_lang("FR")


def test_coaching_figures_bilingual_labels() -> None:
    """Vérifie que les graphiques Plotly basculent leurs titres et axes en anglais."""
    config = load_config()
    trades = [_sample_trade(1, 1.5, True), _sample_trade(2, -1.0, False)]
    alerts = [
        TiltAlert(
            session_date="2026-04-09",
            pattern_type="REVENGE_TRADING",
            trades_involved=["T-002"],
            reason="Entrée précipitée après perte.",
        )
    ]
    segments = segment_by_setup_tag(trades)

    set_lang("EN")
    try:
        fig_eq = build_equity_curve_figure(trades, alerts)
        assert "Cumulative R" in fig_eq.layout.yaxis.title.text

        fig_seg = build_segmentation_figure(
            segments, title="Expectancy by Setup Tag", by_label="Setup Tag"
        )
        assert "Average Return per Trade (R)" in fig_seg.layout.xaxis.title.text

        fig_comp = build_compliance_timeline_figure(trades, config)
        assert "Rule Compliance Rate per Session (%)" in fig_comp.layout.title.text
        assert "Trading Session" in fig_comp.layout.xaxis.title.text
    finally:
        set_lang("FR")
