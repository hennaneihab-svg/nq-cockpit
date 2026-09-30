"""Page Streamlit P09 — Journal de bord et métriques de performance.

Thème sombre cohérent avec cockpit_page.py.
Toutes les valeurs affichées incluent leur horodatage / échantillon.
Sous les seuils : "échantillon insuffisant" visible, jamais masqué.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

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
from nqcockpit.journal.store import delete_trade, init_journal_db, load_trades, save_trade

# ---------------------------------------------------------------------------
# Config et DB
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="NQ Cockpit · Journal",
    page_icon="📓",
    layout="wide",
)

# Thème sombre inline
st.markdown("""
<style>
body, .main { background-color: #0d1117; color: #e6edf3; }
.stDataFrame, .stTable { background-color: #161b22; }
.metric-card {
    background-color: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 12px 16px; margin: 4px 0;
}
.ok { color: #3fb950; font-weight: bold; }
.warn { color: #d29922; font-weight: bold; }
.err { color: #f85149; font-weight: bold; }
.insuf { color: #8b949e; font-style: italic; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def _get_config():
    return load_config()


@st.cache_resource
def _get_db(db_path: str) -> sqlite3.Connection:
    return init_journal_db(db_path)


config = _get_config()
tz_display = ZoneInfo(config.timezones.display)
tz_market = ZoneInfo(config.timezones.market)
db_path = Path(config.data.db_path)
conn = _get_db(str(db_path))

MIN_TRADES = config.validation.min_sessions

# ---------------------------------------------------------------------------
# Sidebar — navigation
# ---------------------------------------------------------------------------

st.sidebar.title("📓 Journal P09")
page = st.sidebar.radio(
    "Section",
    ["Enregistrer un trade", "Journal du jour", "Performance globale", "Coaching"],
    index=0,
)

now_display = datetime.now(tz_display)
st.sidebar.markdown(f"**Heure Alger** : {now_display.strftime('%Y-%m-%d %H:%M')}")

# ---------------------------------------------------------------------------
# Page 1 — Enregistrer un trade
# ---------------------------------------------------------------------------

if page == "Enregistrer un trade":
    st.header("➕ Nouveau trade")

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
        risk_pct_used = st.number_input("Risque utilisé (%)", value=0.5, step=0.1, format="%.2f")
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

    if st.button("💾 Enregistrer le trade", type="primary"):
        if entry_price == 0 or stop_price == 0 or exit_price == 0:
            st.error("❌ Prix d'entrée, stop et sortie obligatoires.")
        elif abs(entry_price - stop_price) < 0.01:
            st.error("❌ Entrée et Stop identiques — risque initial nul.")
        else:
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
                minutes_after_last_sl=minutes_after_last_sl if minutes_after_last_sl > 0 else None,
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
            color = "ok" if trade.r_realized > 0 else ("err" if trade.r_realized < 0 else "warn")
            st.success(
                f"✅ Trade enregistré · "
                f"R réalisé : **{r_str}** · Résultat : **{trade.outcome.value}**"
            )
            st.rerun()

# ---------------------------------------------------------------------------
# Page 2 — Journal du jour
# ---------------------------------------------------------------------------

elif page == "Journal du jour":
    st.header("📅 Journal du jour")

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
        c1.metric("Trades", stats.n_trades)
        c2.metric("Wins / Losses", f"{stats.n_wins} / {stats.n_losses}")

        r_color = "normal" if stats.r_total >= 0 else "inverse"
        c3.metric("R total", f"{stats.r_total:+.3f}R", delta_color=r_color)
        c4.metric("Conformité", f"{stats.compliance_rate:.0%}")

        if stats.limit_hit:
            limit_r = config.rules.daily_loss_limit_r
            st.error(
                f"🔴 LIMITE JOURNALIÈRE ATTEINTE — "
                f"{stats.r_total:+.3f}R (limite : -{limit_r}R)"
            )

        # Tableau des trades
        st.subheader("Trades")
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

        # Violations
        if stats.violations:
            st.subheader(f"⚠️ Violations ({len(stats.violations)})")
            for v in stats.violations:
                st.warning(f"**[{v.violation.value}]** {v.detail}")

        # Tilt alerts
        if stats.tilt_alerts:
            st.subheader(f"🔔 Alertes Tilt ({len(stats.tilt_alerts)})")
            for a in stats.tilt_alerts:
                st.error(f"**Tilt** : {a.reason}")

        # Suppression
        st.subheader("🗑 Supprimer un trade")
        trade_ids = [t.trade_id for t in trades]
        to_delete = st.selectbox("Trade ID à supprimer", ["—"] + trade_ids)
        if to_delete != "—" and st.button("Supprimer", type="secondary"):
            n = delete_trade(conn, to_delete)
            if n:
                st.success(f"Trade {to_delete[:8]}… supprimé.")
                st.rerun()

# ---------------------------------------------------------------------------
# Page 3 — Performance globale
# ---------------------------------------------------------------------------

elif page == "Performance globale":
    st.header("📊 Performance globale")

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
                f'<p class="insuf">⚠️ Échantillon insuffisant : '
                f'{stats.n_trades}/{MIN_TRADES} trades. '
                "Les statistiques avancées (espérance, drawdown, profit factor) "
                "ne sont pas encore calculées.</p>"
            )
            st.markdown(msg, unsafe_allow_html=True)

        # Métriques de base (disponibles même sans seuil)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trades totaux", stats.n_trades)
        c2.metric(
            "Win rate",
            f"{stats.win_rate:.1%}" if stats.win_rate is not None else "—",
            help=f"IC 95% Wilson : [{stats.win_rate_ci_low:.1%}, {stats.win_rate_ci_high:.1%}]"
            if stats.win_rate_ci_low is not None else None,
        )
        c3.metric("Conformité", f"{stats.compliance_rate:.0%}" if stats.compliance_rate else "—")
        c4.metric("Max loss streak", stats.max_loss_streak if stats.sample_sufficient else "—")

        if stats.sample_sufficient:
            st.divider()
            c5, c6, c7, c8 = st.columns(4)
            c5.metric(
                "Espérance (R)",
                f"{stats.expectancy_r:+.3f}R" if stats.expectancy_r is not None else "—",
                help=f"IC 95% : [{stats.expectancy_ci_low:+.3f}, {stats.expectancy_ci_high:+.3f}]"
                if stats.expectancy_ci_low is not None else None,
            )
            c6.metric("Profit factor", f"{stats.profit_factor:.2f}" if stats.profit_factor else "—")
            c7.metric("Max DD (R)", f"-{stats.max_drawdown_r:.3f}R")
            c8.metric(
                "Espérance conformes",
                f"{stats.expectancy_r_compliant:+.3f}R"
                if stats.expectancy_r_compliant is not None else "insuffisant",
            )

        # Segmentation
        st.divider()
        st.subheader("Performance par segment")
        seg_by = st.selectbox(
            "Segmenter par",
            ["setup_tag", "gamma_regime", "vol_regime", "day_of_week", "event_risk"],
        )
        seg = segment_performance(all_trades, by=seg_by)

        seg_rows = []
        for label, s in seg.items():
            suf = (
                "✅" if s.sample_sufficient
                else f"❌ ({s.n_trades}/{s.min_trades_required})"
            )
            seg_rows.append({
                "Segment": label,
                "n": s.n_trades,
                "Win rate": f"{s.win_rate:.1%}" if s.win_rate is not None else "—",
                "Espérance (R)": (
                    f"{s.expectancy_r:+.3f}" if s.expectancy_r is not None
                    else "insuf."
                ),
                "Profit factor": f"{s.profit_factor:.2f}" if s.profit_factor else "—",
                "Suffisant": suf,
            })

        st.dataframe(seg_rows, use_container_width=True)

# ---------------------------------------------------------------------------
# Page 4 — Coaching
# ---------------------------------------------------------------------------

elif page == "Coaching":
    st.header("🎯 Rapport de coaching")

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
                f"⚠️ Données insuffisantes pour {period_label} : "
                f"{report.stats.n_trades if report.stats else 0}/{MIN_TRADES} trades. "
                "Rapport partiel."
            )

        st.subheader(f"Rapport {period_type} · {period_label}")
        st.caption(f"Généré à {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")

        # Top fuites
        st.markdown("#### 🔍 Top 3 fuites chiffrées")
        for i, leak in enumerate(report.top_leaks, 1):
            st.markdown(f"**{i}.** {leak}")

        # Règle & force
        col3, col4 = st.columns(2)
        with col3:
            st.markdown("#### 📌 Règle à renforcer")
            st.info(report.rule_to_reinforce or "—")
        with col4:
            st.markdown("#### 💪 Force à conserver")
            st.success(report.strength_to_keep or "—")

        # Objectifs
        st.markdown("#### 🎯 Objectifs mesurables")
        for goal in report.measurable_goals:
            st.markdown(f"- {goal}")

        # Stats résumé
        if report.stats and report.stats.sample_sufficient:
            st.divider()
            st.markdown("#### Statistiques de la période")
            d = report.stats.to_dict()
            st.json(d)
