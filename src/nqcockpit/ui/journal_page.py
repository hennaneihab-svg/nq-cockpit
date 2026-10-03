"""Page Streamlit P09 — Journal de bord et métriques de performance.

Design System Bloomberg x TradingView :
- Thème Slate #131722, bordures 1px #2A2E39, accents marque #FA7900
- Nombres et résultats au format tabulaire
- Statut "échantillon insuffisant" visible et non masqué
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.config import load_config
from nqcockpit.journal.engine import (
    compute_daily_stats,
    compute_performance_stats,
    finalize_trade,
    generate_coaching_report,
    segment_performance,
)
from nqcockpit.journal.models import (
    GammaRegime,
    TradeDirection,
    TradeEntry,
    VolRegime,
)
from nqcockpit.journal.store import delete_trade, load_trades, save_trade
from nqcockpit.ui.components import render_terminal_metric
from nqcockpit.ui.db import get_ui_db


@st.cache_resource
def _get_config():
    return load_config()


def render_journal_page() -> None:
    """Rendu complet du Journal de bord."""
    try:
        st.set_page_config(
            page_title="NQ Cockpit · Journal",
            layout="wide",
        )
    except StreamlitAPIException:
        pass

    # CSS Swetrix
    st.markdown("""
    <style>
    .stApp {
        background-color: #020617;
        color: #F8FAFC;
        font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .stDataFrame, .stTable {
        background-color: #0F172A;
        border: 1px solid rgba(51, 65, 85, 0.6);
        border-radius: 8px;
    }
    .insuf {
        color: #94A3B8;
        font-style: italic;
        font-family: ui-monospace, monospace;
    }
    .section-header {
        font-family: -apple-system, system-ui, sans-serif;
        color: #F8FAFC;
        font-size: 1.05rem;
        font-weight: 600;
        letter-spacing: -0.01em;
        margin-bottom: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

    config = _get_config()
    tz_market = ZoneInfo(config.timezones.market)
    db_path = Path(config.data.db_path)
    conn = get_ui_db(str(db_path))

    MIN_TRADES = config.validation.min_sessions

    # ---------------------------------------------------------------------------
    # Navigation interne du Journal (Onglets horizontaux)
    # ---------------------------------------------------------------------------

    st.markdown(
        '<div class="section-header">JOURNAL DE BORD // SECTIONS</div>',
        unsafe_allow_html=True,
    )
    page = st.radio(
        "Section Journal",
        ["Enregistrer un trade", "Journal du jour", "Performance globale", "Coaching"],
        index=0,
        horizontal=True,
        label_visibility="collapsed",
    )

    # ---------------------------------------------------------------------------
    # Page 1 — Enregistrer un trade
    # ---------------------------------------------------------------------------

    if page == "Enregistrer un trade":
        st.markdown(
            '<div class="section-header">SAISIE D\'UN NOUVEAU TRADE</div>',
            unsafe_allow_html=True,
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            session_date = st.date_input("Date séance (NY)", value=datetime.now(tz_market).date())
            instrument = st.selectbox("Instrument", ["MNQ", "NQ"], index=0)
            direction = st.selectbox("Direction", ["LONG", "SHORT", "NONE"], index=0)
            window_name = st.selectbox(
                "Fenêtre",
                ["trade1", "trade2", ""] + [w.name for w in config.trading_windows_algiers
                                             if w.name not in ("trade1", "trade2")],
                index=0,
            )

        with col2:
            entry_price = st.number_input("Prix d'entrée", value=0.0, step=0.25, format="%.2f")
            stop_price = st.number_input("Stop Loss (initial)", value=0.0, step=0.25, format="%.2f")
            tp1_price = st.number_input("TP1 (optionnel)", value=0.0, step=0.25, format="%.2f")
            exit_price = st.number_input("Prix de sortie", value=0.0, step=0.25, format="%.2f")
            exit_reason = st.selectbox("Raison sortie", ["SL", "TP1", "TP2", "Manuel", "Temps"])

        with col3:
            fees_points = st.number_input("Frais (points NQ)", value=0.0, step=0.01, format="%.2f")
            sl_moved = st.checkbox("SL déplacé après entrée")
            early_exit = st.checkbox("Sortie anticipée")
            risk_pct_used = st.number_input(
                "Risque utilisé (%)", value=0.5, step=0.1, format="%.2f"
            )
            minutes_after_last_sl = st.number_input(
                "Minutes après dernier SL", value=0.0, step=1.0, format="%.0f"
            )

        st.divider()
        col4, col5 = st.columns(2)
        with col4:
            setup_tag = st.text_input("Tag setup (ex. ICT_BOS, FVG, VWAP_rejet)")
            gamma_regime = st.selectbox("Régime gamma", [r.value for r in GammaRegime], index=2)
            vol_regime = st.selectbox("Régime volatilité", [r.value for r in VolRegime], index=2)

        with col5:
            event_risk_label = st.text_input("Contexte événement (ex. 'CPI Tier1 dans 2h')")
            notes = st.text_area("Notes", height=80)
            screenshot_path = st.text_input("Chemin capture (optionnel)")

        if st.button("Enregistrer le trade", type="primary"):
            if entry_price == 0 or stop_price == 0 or exit_price == 0:
                st.error("[ERREUR] Prix d'entrée, stop et sortie obligatoires.")
            elif abs(entry_price - stop_price) < 0.01:
                st.error("[ERREUR] Entrée et Stop identiques — risque initial nul.")
            else:
                last_sl_mins = (
                    minutes_after_last_sl if minutes_after_last_sl > 0 else None
                )
                trade = TradeEntry(
                    trade_id=str(uuid.uuid4()),
                    recorded_at=datetime.now(timezone.utc),
                    session_date=str(session_date),
                    instrument=instrument,
                    direction=TradeDirection(direction),
                    entry_price=entry_price,
                    stop_price=stop_price,
                    tp1_price=tp1_price if tp1_price != 0 else None,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    fees_points=fees_points,
                    window_name=window_name,
                    minutes_after_last_sl=last_sl_mins,
                    event_risk_label=event_risk_label,
                    gamma_regime=GammaRegime(gamma_regime),
                    vol_regime=VolRegime(vol_regime),
                    day_of_week=session_date.weekday(),
                    sl_moved=sl_moved,
                    early_exit=early_exit,
                    risk_pct_used=risk_pct_used,
                    setup_tag=setup_tag,
                    notes=notes,
                    screenshot_path=screenshot_path,
                )
                trade = finalize_trade(trade)
                save_trade(conn, trade)

                r_str = f"{trade.r_realized:+.3f}R"
                st.success(
                    f"[CONFIRMATION] Trade enregistré · "
                    f"R réalisé : **{r_str}** · Résultat : **{trade.outcome.value}**"
                )
                st.rerun()

    # ---------------------------------------------------------------------------
    # Page 2 — Journal du jour
    # ---------------------------------------------------------------------------

    elif page == "Journal du jour":
        st.markdown(
            '<div class="section-header">JOURNAL DE SÉANCE DÉTAILLÉ</div>',
            unsafe_allow_html=True,
        )

        today_ny = datetime.now(tz_market).date()
        selected_date = st.date_input("Date séance", value=today_ny)
        session_str = str(selected_date)

        trades = load_trades(conn, session_date=session_str)

        if not trades:
            st.info("Aucun trade enregistré pour cette date.")
        else:
            stats = compute_daily_stats(session_str, trades, config)

            # KPI cards
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                render_terminal_metric("Trades", str(stats.n_trades))
            with c2:
                render_terminal_metric("Wins / Losses", f"{stats.n_wins} / {stats.n_losses}")
            with c3:
                r_kind = "pos" if stats.r_total >= 0 else "neg"
                render_terminal_metric("R total", f"{stats.r_total:+.3f}R", status_kind=r_kind)
            with c4:
                render_terminal_metric("Conformité", f"{stats.compliance_rate:.0%}")

            if stats.limit_hit:
                limit_r = config.rules.daily_loss_limit_r
                st.error(
                    f"[VERROU] LIMITE JOURNALIÈRE ATTEINTE — "
                    f"{stats.r_total:+.3f}R (limite : -{limit_r}R)"
                )

            # Tableau des trades
            st.markdown("#### Liste des Trades")
            rows = []
            for t in sorted(trades, key=lambda x: x.recorded_at):
                rows.append({
                    "ID": t.trade_id[:8],
                    "Direction": t.direction.value,
                    "Entrée": t.entry_price,
                    "Stop": t.stop_price,
                    "Sortie": t.exit_price,
                    "R réalisé": f"{t.r_realized:+.3f}",
                    "Résultat": t.outcome.value,
                    "Fenêtre": t.window_name,
                    "Setup": t.setup_tag,
                })

            st.dataframe(rows, use_container_width=True)

            # Captures d'écran associées
            screenshot_trades = [
                t for t in trades if t.screenshot_path and t.screenshot_path.strip()
            ]
            if screenshot_trades:
                st.markdown("#### Captures d'écran associées")
                for t in screenshot_trades:
                    p_img = Path(t.screenshot_path)
                    st.write(
                        f"**Trade `{t.trade_id[:8]}`** "
                        f"({t.direction.value} @ {t.entry_price:.2f}) :"
                    )
                    if p_img.is_file():
                        st.image(
                            str(p_img),
                            caption=(
                                f"Capture Trade {t.trade_id[:8]} — "
                                f"{t.setup_tag or 'Setup'}"
                            ),
                        )
                    else:
                        st.warning(
                            f"[AVERTISSEMENT] Image introuvable : `{t.screenshot_path}`"
                        )

            # Violations
            if stats.violations:
                st.markdown(f"#### Violations de Règles ({len(stats.violations)})")
                for v in stats.violations:
                    st.warning(f"**[{v.violation.value}]** {v.detail}")

            # Tilt alerts
            if stats.tilt_alerts:
                st.markdown(f"#### Alertes de Tilt ({len(stats.tilt_alerts)})")
                for a in stats.tilt_alerts:
                    st.error(f"**[TILT]** {a.reason}")

            # Suppression
            st.markdown("#### Supprimer un trade")
            trade_ids = [t.trade_id for t in trades]
            to_delete = st.selectbox("Trade ID à supprimer", ["—"] + trade_ids)
            if to_delete != "—" and st.button("Supprimer le trade sélectionné"):
                n = delete_trade(conn, to_delete)
                if n:
                    st.success(f"Trade {to_delete[:8]}… supprimé.")
                    st.rerun()

    # ---------------------------------------------------------------------------
    # Page 3 — Performance globale
    # ---------------------------------------------------------------------------

    elif page == "Performance globale":
        st.markdown(
            '<div class="section-header">PERFORMANCE GLOBALE AGREGÉE</div>',
            unsafe_allow_html=True,
        )

        all_trades = load_trades(conn)
        if not all_trades:
            st.info("Aucun trade enregistré dans le journal.")
        else:
            stats = compute_performance_stats(all_trades, min_trades=MIN_TRADES)
            computed_str = (
                stats.computed_at.strftime("%Y-%m-%d %H:%M UTC")
                if stats.computed_at else "—"
            )
            st.caption(f"Calculé à {computed_str} · n = {stats.n_trades} trades")

            if not stats.sample_sufficient:
                msg = (
                    f'<p class="insuf">[STATUT ÉCHANTILLON] Échantillon insuffisant : '
                    f'{stats.n_trades}/{MIN_TRADES} trades. '
                    "Les statistiques avancées ne sont pas encore calculées.</p>"
                )
                st.markdown(msg, unsafe_allow_html=True)

            # Métriques de base (disponibles même sans seuil)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                render_terminal_metric("Trades totaux", str(stats.n_trades))
            with c2:
                wr_str = f"{stats.win_rate:.1%}" if stats.win_rate is not None else "—"
                render_terminal_metric("Win Rate", wr_str)
            with c3:
                compl_val = f"{stats.compliance_rate:.0%}" if stats.compliance_rate else "—"
                render_terminal_metric("Conformité", compl_val)
            with c4:
                streak_val = str(stats.max_loss_streak) if stats.sample_sufficient else "—"
                render_terminal_metric("Max Loss Streak", streak_val)

            if stats.sample_sufficient:
                st.divider()
                c5, c6, c7, c8 = st.columns(4)
                with c5:
                    exp_r_val = stats.expectancy_r
                    exp_r_str = f"{exp_r_val:+.3f}R" if exp_r_val is not None else "—"
                    exp_kind = "pos" if exp_r_val and exp_r_val >= 0 else "neg"
                    render_terminal_metric("Espérance (R)", exp_r_str, status_kind=exp_kind)
                with c6:
                    pf_val = f"{stats.profit_factor:.2f}" if stats.profit_factor else "—"
                    render_terminal_metric("Profit Factor", pf_val)
                with c7:
                    dd_str = f"-{stats.max_drawdown_r:.3f}R"
                    render_terminal_metric("Max DD (R)", dd_str, status_kind="neg")
                with c8:
                    exp_c_val = stats.expectancy_r_compliant
                    exp_c_str = (
                        f"{exp_c_val:+.3f}R"
                        if exp_c_val is not None
                        else "insuffisant"
                    )
                    render_terminal_metric("Espérance Conformes", exp_c_str)

            # Segmentation
            st.divider()
            st.markdown("#### Performance par Segment")
            seg_by = st.selectbox(
                "Segmenter par",
                ["setup_tag", "gamma_regime", "vol_regime", "day_of_week", "event_risk"],
            )
            seg = segment_performance(all_trades, by=seg_by)

            seg_rows = []
            for label, s in seg.items():
                suf = (
                    "OK" if s.sample_sufficient
                    else f"INSUFFISANT ({s.n_trades}/{s.min_trades_required})"
                )
                seg_rows.append({
                    "Segment": label,
                    "n": s.n_trades,
                    "Win Rate": f"{s.win_rate:.1%}" if s.win_rate is not None else "—",
                    "Espérance (R)": (
                        f"{s.expectancy_r:+.3f}" if s.expectancy_r is not None
                        else "insuf."
                    ),
                    "Profit Factor": f"{s.profit_factor:.2f}" if s.profit_factor else "—",
                    "Échantillon": suf,
                })

            st.dataframe(seg_rows, use_container_width=True)

    # ---------------------------------------------------------------------------
    # Page 4 — Coaching
    # ---------------------------------------------------------------------------

    elif page == "Coaching":
        st.markdown(
            '<div class="section-header">RAPPORT DE COACHING ET ANALYTICS</div>',
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns([1, 2])
        with col1:
            period_type = st.radio("Période", ["hebdo", "mensuel"])
            period_label = st.text_input("Label (ex. S39-2026, Oct-2026)", value="S39-2026")
            gen_btn = st.button("Générer le rapport", type="primary")

        if gen_btn:
            all_trades = load_trades(conn)
            report = generate_coaching_report(all_trades, period=period_type,
                                              period_label=period_label, config=config)

            if report.insufficient_data:
                st.warning(
                    f"[DONNÉES INSUFFISANTES] {period_label} : "
                    f"{report.stats.n_trades if report.stats else 0}/{MIN_TRADES} trades. "
                    "Rapport partiel."
                )

            st.markdown(f"#### Rapport {period_type.upper()} · {period_label}")
            st.caption(f"Généré à {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")

            # Top fuites
            st.markdown("#### Top 3 Fuites Chiffrées")
            for i, leak in enumerate(report.top_leaks, 1):
                st.markdown(f"**{i}.** {leak}")

            # Règle & force
            col3, col4 = st.columns(2)
            with col3:
                st.markdown("#### Règle à Renforcer")
                st.info(report.rule_to_reinforce or "—")
            with col4:
                st.markdown("#### Force à Conserver")
                st.success(report.strength_to_keep or "—")

            # Objectifs
            st.markdown("#### Objectifs Mesurables")
            for goal in report.measurable_goals:
                st.markdown(f"- {goal}")

            # Stats résumé
            if report.stats and report.stats.sample_sufficient:
                st.divider()
                st.markdown("#### Statistiques de la Période")
                d = report.stats.to_dict()
                st.json(d)


if __name__ == "__main__":
    render_journal_page()
