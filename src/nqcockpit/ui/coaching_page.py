"""Page Streamlit P11 — Coaching & Analytics de performance (Port 8504).

Visualisations Plotly interactives pour le journal de trading :
- Courbe d'équité en R cumulé chronologique
- Timeline des alertes de tilt superposée à la courbe d'équité
- Répartition des R par segment (setup_tag et gamma_regime)
- Taux de conformité aux règles dans le temps (séance / semaine / mois)
- Rapport de coaching et fuites chiffrées

Réutilise exclusivement les fonctions existantes :
- `compute_performance_stats`
- `segment_by_setup_tag` / `segment_by_gamma_regime`
- `detect_period_tilt_alerts`
- `detect_violations`
- `generate_coaching_report`
- `get_period_bounds` / `filter_trades_by_date_range`
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.config import AppConfig, load_config
from nqcockpit.journal.engine import (
    compute_performance_stats,
    detect_period_tilt_alerts,
    detect_violations,
    generate_coaching_report,
    segment_by_gamma_regime,
    segment_by_setup_tag,
)
from nqcockpit.journal.models import PerformanceStats, TiltAlert, TradeEntry
from nqcockpit.journal.reports import (
    filter_trades_by_date_range,
    get_period_bounds,
)
from nqcockpit.journal.store import load_trades
from nqcockpit.ui.db import get_ui_db

# ---------------------------------------------------------------------------
# Thème et Configuration Plotly
# ---------------------------------------------------------------------------

PLOTLY_LAYOUT_DEFAULTS: dict[str, Any] = {
    "template": "plotly_dark",
    "paper_bgcolor": "#0F172A",
    "plot_bgcolor": "#020617",
    "font": {
        "color": "#F8FAFC",
        "family": "-apple-system, system-ui, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
    },
    "title_font": {
        "size": 15,
        "color": "#F8FAFC",
        "family": "ui-monospace, SFMono-Regular, monospace",
    },
    "title_x": 0.02,
    "title_xanchor": "left",
    "title_y": 0.94,
    "title_yanchor": "top",
    "margin": {"l": 55, "r": 35, "t": 65, "b": 45},
    "xaxis_gridcolor": "rgba(51, 65, 85, 0.4)",
    "xaxis_gridwidth": 1,
    "xaxis_zerolinecolor": "rgba(71, 85, 105, 0.6)",
    "xaxis_zerolinewidth": 1,
    "yaxis_gridcolor": "rgba(51, 65, 85, 0.4)",
    "yaxis_gridwidth": 1,
    "yaxis_zerolinecolor": "rgba(71, 85, 105, 0.6)",
    "yaxis_zerolinewidth": 1,
    "hoverlabel": {
        "bgcolor": "#0F172A",
        "bordercolor": "rgba(100, 116, 139, 0.5)",
        "font": {
            "family": "ui-monospace, SFMono-Regular, monospace",
            "size": 12,
            "color": "#F8FAFC",
        },
    },
    "transition": {
        "duration": 500,
        "easing": "cubic-in-out",
    },
}


def build_equity_curve_figure(
    trades: list[TradeEntry],
    tilt_alerts: list[TiltAlert] | None = None,
) -> go.Figure:
    """Construit la figure Plotly de la courbe d'équité en R cumulé.

    Superpose les marqueurs d'alerte tilt sur les trades concernés.
    Design desk haute performance avec halo dynamique.
    """
    fig = go.Figure()

    if not trades:
        fig.add_annotation(
            text="Aucun trade disponible pour cette période",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#787B86"},
        )
        fig.update_layout(**PLOTLY_LAYOUT_DEFAULTS, title="Courbe d'équité (R cumulé)")
        return fig

    # Chronologie stricte
    sorted_trades = sorted(
        trades,
        key=lambda x: (x.session_date, x.entry_time_ny or x.recorded_at),
    )

    x_labels: list[str] = []
    cum_r: list[float] = []
    hover_texts: list[str] = []
    trade_id_to_point: dict[str, tuple[str, float]] = {}

    current_r = 0.0
    for i, t in enumerate(sorted_trades, 1):
        current_r += t.r_realized
        label = f"#{i} ({t.session_date})"
        x_labels.append(label)
        cum_r.append(round(current_r, 4))
        trade_id_to_point[t.trade_id] = (label, round(current_r, 4))

        contracts_str = f"{t.contracts}" if t.contracts is not None else "N/A"
        conforme_str = "Oui" if not (t.sl_moved or t.early_exit) else "Non"
        color_res = "#10B981" if t.r_realized >= 0 else "#EF4444"
        txt = (
            f"<b>Trade #{i} [{t.trade_id[:8]}]</b><br>"
            f"Date : {t.session_date} {t.entry_time_ny or ''}<br>"
            f"Direction : {t.direction.value} | Contrats : {contracts_str}<br>"
            f"Setup : {t.setup_tag or 'N/A'}<br>"
            f"Résultat : <b style='color:{color_res}'>{t.r_realized:+.3f}R</b> "
            f"({t.outcome.value})<br>"
            f"R cumulé : <b>{current_r:+.3f}R</b><br>"
            f"Conforme aux règles : {conforme_str}"
        )
        hover_texts.append(txt)

    # Courbe d'équité principale (Bleu laser Swetrix avec zone de remplissage dégradée)
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=cum_r,
            mode="lines+markers",
            name="R Cumulé",
            line={"color": "#6366F1", "width": 3, "shape": "spline"},
            marker={
                "size": 7,
                "color": "#818CF8",
                "line": {"color": "#FFFFFF", "width": 1.5},
            },
            fill="tozeroy",
            fillcolor="rgba(99, 102, 241, 0.12)",
            hovertext=hover_texts,
            hoverinfo="text",
        )
    )

    # Ligne de référence à 0 R (neutre et discrète)
    fig.add_hline(
        y=0.0,
        line_dash="dot",
        line_color="rgba(148, 163, 184, 0.4)",
        line_width=1.5,
        annotation_text="Point d'équilibre (0.0 R)",
        annotation_position="bottom right",
        annotation_font_color="#94A3B8",
        annotation_font_size=11,
    )

    # Superposition des alertes de tilt (Triangles rouges d'avertissement)
    if tilt_alerts:
        tilt_x: list[str] = []
        tilt_y: list[float] = []
        tilt_texts: list[str] = []

        for alert in tilt_alerts:
            for tid in alert.trades_involved:
                if tid in trade_id_to_point:
                    pt_x, pt_y = trade_id_to_point[tid]
                    tilt_x.append(pt_x)
                    tilt_y.append(pt_y)
                    tilt_texts.append(
                        f"<b>Alerte Tilt : {alert.pattern_type}</b><br>"
                        f"Séance : {alert.session_date}<br>"
                        f"Motif : {alert.reason}"
                    )

        if tilt_x:
            fig.add_trace(
                go.Scatter(
                    x=tilt_x,
                    y=tilt_y,
                    mode="markers",
                    name="Alertes de Tilt",
                    marker={
                        "symbol": "triangle-up",
                        "size": 14,
                        "color": "#EF4444",
                        "line": {"color": "#FFFFFF", "width": 1.5},
                    },
                    hovertext=tilt_texts,
                    hoverinfo="text",
                )
            )

    fig.update_layout(
        **PLOTLY_LAYOUT_DEFAULTS,
        title="Courbe d'équité en R cumulé chronologique & Alertes de tilt",
        xaxis_title="Séquence des Trades",
        yaxis_title="Performance R Cumulée",
        hovermode="closest",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"size": 11, "color": "#94A3B8"},
        },
    )
    return fig


def build_segmentation_figure(
    segments: dict[str, PerformanceStats],
    title: str,
    by_label: str,
) -> go.Figure:
    """Construit un graphique en barres horizontales pour une segmentation."""
    fig = go.Figure()

    if not segments:
        fig.add_annotation(
            text="Aucun segment disponible",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#787B86"},
        )
        fig.update_layout(**PLOTLY_LAYOUT_DEFAULTS, title=title)
        return fig

    labels: list[str] = []
    exp_r: list[float] = []
    colors: list[str] = []
    hover_texts: list[str] = []

    for name, stats in segments.items():
        val = stats.expectancy_r if stats.expectancy_r is not None else 0.0
        exp_r.append(round(val, 3))

        sig_tag = "" if stats.sample_sufficient else " (n < seuil)"
        labels.append(f"{name}{sig_tag}")

        colors.append("#10B981" if val >= 0 else "#EF4444")

        wr_str = f"{stats.win_rate:.1%}" if stats.win_rate is not None else "—"
        ci_str = (
            f"[{stats.win_rate_ci_low:.1%}, {stats.win_rate_ci_high:.1%}]"
            if stats.win_rate_ci_low is not None and stats.win_rate_ci_high is not None
            else "—"
        )
        exp_ci_str = (
            f"[{stats.expectancy_ci_low:+.3f}R, {stats.expectancy_ci_high:+.3f}R]"
            if stats.expectancy_ci_low is not None and stats.expectancy_ci_high is not None
            else "—"
        )

        hover_texts.append(
            f"<b>{by_label} : {name}</b><br>"
            f"Trades : {stats.n_trades}<br>"
            f"Espérance : <b>{val:+.3f}R</b> (IC 95% : {exp_ci_str})<br>"
            f"Win Rate : <b>{wr_str}</b> (IC Wilson : {ci_str})<br>"
            f"Wins / Pertes : {stats.n_wins} / {stats.n_losses}<br>"
            f"Échantillon suffisant : {'Oui' if stats.sample_sufficient else 'Non'}"
        )

    fig.add_trace(
        go.Bar(
            y=labels,
            x=exp_r,
            orientation="h",
            marker={
                "color": colors,
                "line": {"color": "rgba(255, 255, 255, 0.2)", "width": 1.2},
            },
            hovertext=hover_texts,
            hoverinfo="text",
        )
    )

    fig.add_vline(
        x=0.0,
        line_dash="dot",
        line_color="rgba(148, 163, 184, 0.5)",
        line_width=1.5,
    )

    fig.update_layout(
        **PLOTLY_LAYOUT_DEFAULTS,
        title=title,
        xaxis_title="Espérance de gain par trade (R)",
        yaxis_title=by_label,
        yaxis={"autorange": "reversed"},
    )
    return fig


def build_compliance_timeline_figure(
    trades: list[TradeEntry],
    config: AppConfig,
) -> go.Figure:
    """Construit le graphique d'évolution temporelle de la conformité aux règles."""
    fig = go.Figure()

    if not trades:
        fig.add_annotation(
            text="Aucun trade disponible pour cette période",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#787B86"},
        )
        fig.update_layout(**PLOTLY_LAYOUT_DEFAULTS, title="Conformité aux règles dans le temps")
        return fig

    # Regrouper par session_date
    sessions: dict[str, list[TradeEntry]] = {}
    for t in sorted(trades, key=lambda x: x.session_date):
        sessions.setdefault(t.session_date, []).append(t)

    session_dates: list[str] = []
    comp_rates: list[float] = []
    bar_colors: list[str] = []
    hover_texts: list[str] = []

    for s_date, s_trades in sessions.items():
        session_dates.append(s_date)
        n_total = len(s_trades)
        viol_trades_count = 0
        for t in s_trades:
            if detect_violations(t, s_trades, config):
                viol_trades_count += 1
        n_compliant = n_total - viol_trades_count
        rate = (n_compliant / n_total) * 100.0 if n_total > 0 else 0.0
        comp_rates.append(round(rate, 1))

        if rate >= 100.0:
            bar_colors.append("#089981")
        elif rate >= 80.0:
            bar_colors.append("#D29922")
        else:
            bar_colors.append("#F23645")

        hover_texts.append(
            f"<b>Séance : {s_date}</b><br>"
            f"Trades totaux : {n_total}<br>"
            f"Trades conformes : {n_compliant} / {n_total}<br>"
            f"Conformité : <b>{rate:.1f}%</b>"
        )

    fig.add_trace(
        go.Bar(
            x=session_dates,
            y=comp_rates,
            marker={
                "color": bar_colors,
                "line": {"color": "rgba(255, 255, 255, 0.2)", "width": 1.2},
            },
            hovertext=hover_texts,
            hoverinfo="text",
            name="Conformité (%)",
        )
    )

    # Ligne cible 100%
    fig.add_hline(
        y=100.0,
        line_dash="dot",
        line_color="#10B981",
        line_width=1.5,
        annotation_text="Objectif Discipline 100%",
        annotation_position="top right",
        annotation_font_color="#10B981",
    )

    fig.update_layout(
        **PLOTLY_LAYOUT_DEFAULTS,
        title="Taux de conformité aux règles par séance (%)",
        xaxis_title="Séance de Trading",
        yaxis_title="Discipline (%)",
        yaxis={"range": [0, 105]},
    )
    return fig


# ---------------------------------------------------------------------------
# Application Streamlit
# ---------------------------------------------------------------------------


def render_coaching_app() -> None:
    """Point d'entrée principal de l'interface Streamlit de coaching."""
    try:
        st.set_page_config(
            page_title="NQ Cockpit · Coaching & Analytics",
            layout="wide",
        )
    except StreamlitAPIException:
        pass

    # Thème sombre CSS Swetrix avec animations interactives fluides
    st.markdown(
        """
    <style>
    body, .main {
        background-color: #020617;
        color: #F8FAFC;
        font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .metric-card {
        background: linear-gradient(145deg, #0F172A 0%, #090D16 100%);
        border: 1px solid rgba(51, 65, 85, 0.7);
        border-radius: 10px;
        padding: 16px 18px;
        margin: 4px 0;
        box-shadow: 0 4px 14px 0 rgba(0, 0, 0, 0.25);
        transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1),
                    border-color 0.2s ease,
                    box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(99, 102, 241, 0.5);
        box-shadow: 0 6px 20px 0 rgba(99, 102, 241, 0.15);
    }
    .metric-label {
        font-size: 0.72rem;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 700;
        margin-bottom: 4px;
    }
    .metric-val {
        font-size: 1.55rem;
        font-weight: 700;
        color: #F8FAFC;
        font-family: ui-monospace, SFMono-Regular, monospace;
        letter-spacing: -0.02em;
    }
    .metric-sub {
        font-size: 0.75rem;
        color: #94A3B8;
        margin-top: 4px;
        font-family: -apple-system, sans-serif;
    }
    .ok { color: #10B981; font-weight: 700; }
    .warn { color: #F59E0B; font-weight: 700; }
    .err { color: #EF4444; font-weight: 700; }
    .insuf { color: #94A3B8; font-style: italic; }
    </style>
    """,
        unsafe_allow_html=True,
    )

    config = load_config()
    tz_display = ZoneInfo(config.timezones.display)
    tz_market = ZoneInfo(config.timezones.market)
    now_algiers = datetime.now(tz_display)
    today_ny = datetime.now(tz_market).date()

    db_path_str = os.getenv("NQ_DATA_DB_PATH", config.data.db_path)
    conn = get_ui_db(db_path_str)
    all_trades = load_trades(conn)

    # -----------------------------------------------------------------------
    # Sidebar : Contrôles & Filtres temporels
    # -----------------------------------------------------------------------
    st.sidebar.title("[04] COACHING & ANALYTICS")
    st.sidebar.markdown(f"**Heure Alger** : `{now_algiers.strftime('%Y-%m-%d %H:%M')}`")
    st.sidebar.markdown(f"**Base** : `{Path(db_path_str).name}` ({len(all_trades)} trades)")
    st.sidebar.markdown("---")

    period_choice = st.sidebar.selectbox(
        "Période d'analyse",
        [
            "Toutes les données",
            "Cette semaine",
            "Semaine précédente",
            "Ce mois",
            "Mois précédent",
            "Plage personnalisée",
        ],
        index=0,
    )

    filtered_trades: list[TradeEntry] = []
    period_title = "Historique complet"
    period_type = "hebdo"
    period_label = "global"

    if period_choice == "Toutes les données":
        filtered_trades = all_trades
        period_title = f"Historique complet ({len(all_trades)} trades)"
        period_label = "complet"
    elif period_choice == "Cette semaine":
        c_start, c_end, c_lbl, _, _, _ = get_period_bounds("week", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, c_start, c_end)
        period_title = f"Semaine en cours : {c_lbl} ({c_start} au {c_end})"
        period_type = "hebdo"
        period_label = c_lbl
    elif period_choice == "Semaine précédente":
        _, _, _, p_start, p_end, p_lbl = get_period_bounds("week", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, p_start, p_end)
        period_title = f"Semaine précédente : {p_lbl} ({p_start} au {p_end})"
        period_type = "hebdo"
        period_label = p_lbl
    elif period_choice == "Ce mois":
        c_start, c_end, c_lbl, _, _, _ = get_period_bounds("month", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, c_start, c_end)
        period_title = f"Mois en cours : {c_lbl} ({c_start} au {c_end})"
        period_type = "mensuel"
        period_label = c_lbl
    elif period_choice == "Mois précédent":
        _, _, _, p_start, p_end, p_lbl = get_period_bounds("month", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, p_start, p_end)
        period_title = f"Mois précédent : {p_lbl} ({p_start} au {p_end})"
        period_type = "mensuel"
        period_label = p_lbl
    elif period_choice == "Plage personnalisée":
        col_d1, col_d2 = st.sidebar.columns(2)
        default_start = today_ny - timedelta(days=30)
        start_input = col_d1.date_input("Début", default_start)
        end_input = col_d2.date_input("Fin", today_ny)
        if isinstance(start_input, date) and isinstance(end_input, date):
            filtered_trades = filter_trades_by_date_range(all_trades, start_input, end_input)
            period_title = f"Plage personnalisée ({start_input} au {end_input})"
            period_label = f"{start_input}_{end_input}"

    # -----------------------------------------------------------------------
    # Calcul des métriques & Détection du tilt (Sans duplication)
    # -----------------------------------------------------------------------
    min_required = config.validation.min_sessions
    stats = compute_performance_stats(
        filtered_trades,
        min_trades=min_required,
        config=config,
    )
    tilt_alerts = detect_period_tilt_alerts(filtered_trades, config)

    # -----------------------------------------------------------------------
    # En-tête & Bannière de significativité statistique
    # -----------------------------------------------------------------------
    st.header(f"ANALYSIS // {period_title.upper()}")

    if not stats.sample_sufficient:
        st.warning(
            f"**Échantillon insuffisant** : {stats.n_trades} / {stats.min_trades_required} "
            "trades requis pour la validité statistique. Les métriques ci-dessous sont purement "
            "descriptives et n'ont pas de significativité statistique confirmée."
        )
    else:
        st.success(
            f"**Échantillon statistiquement représentatif** : {stats.n_trades} trades "
            f"(seuil minimal {stats.min_trades_required} atteint)."
        )

    # -----------------------------------------------------------------------
    # Cartes de Métriques Clés (KPI)
    # -----------------------------------------------------------------------
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    total_r = sum(t.r_realized for t in filtered_trades)

    with c1:
        wr_str = f"{stats.win_rate:.1%}" if stats.win_rate is not None else "—"
        ci_str = (
            f"[{stats.win_rate_ci_low:.1%}, {stats.win_rate_ci_high:.1%}]"
            if stats.win_rate_ci_low is not None and stats.win_rate_ci_high is not None
            else "—"
        )
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">Win Rate</div>
            <div class="metric-val">{wr_str}</div>
            <div class="metric-sub">IC Wilson : {ci_str}</div>
        </div>""",
            unsafe_allow_html=True,
        )

    with c2:
        exp_str = f"{stats.expectancy_r:+.3f}R" if stats.sample_sufficient else "—"
        exp_sub = (
            f"IC : [{stats.expectancy_ci_low:+.2f}, {stats.expectancy_ci_high:+.2f}]"
            if stats.sample_sufficient
            and stats.expectancy_ci_low is not None
            and stats.expectancy_ci_high is not None
            else "Non significatif"
        )
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">Espérance de gain</div>
            <div class="metric-val">{exp_str}</div>
            <div class="metric-sub">{exp_sub}</div>
        </div>""",
            unsafe_allow_html=True,
        )

    with c3:
        pf_str = (
            f"{stats.profit_factor:.2f}"
            if stats.sample_sufficient and stats.profit_factor is not None
            else "—"
        )
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">Profit Factor</div>
            <div class="metric-val">{pf_str}</div>
            <div class="metric-sub">Total R : {total_r:+.2f}R</div>
        </div>""",
            unsafe_allow_html=True,
        )

    with c4:
        dd_str = f"-{stats.max_drawdown_r:.2f}R" if stats.sample_sufficient else "—"
        streak_sub = (
            f"Série max : {stats.max_loss_streak} pertes"
            if stats.sample_sufficient
            else "Non significatif"
        )
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">Max Drawdown</div>
            <div class="metric-val">{dd_str}</div>
            <div class="metric-sub">{streak_sub}</div>
        </div>""",
            unsafe_allow_html=True,
        )

    with c5:
        comp_str = f"{stats.compliance_rate:.1%}" if stats.compliance_rate is not None else "—"
        n_comp = getattr(stats, "n_compliant", 0)
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">Conformité</div>
            <div class="metric-val">{comp_str}</div>
            <div class="metric-sub">{n_comp} / {stats.n_trades} trades</div>
        </div>""",
            unsafe_allow_html=True,
        )

    with c6:
        n_tilt = len(tilt_alerts)
        tilt_color = "ok" if n_tilt == 0 else "err"
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">Alertes Tilt</div>
            <div class="metric-val {tilt_color}">{n_tilt}</div>
            <div class="metric-sub">{len(set(a.session_date for a in tilt_alerts))} séance(s)</div>
        </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # -----------------------------------------------------------------------
    # Visualisation 1 : Courbe d'équité & Timeline des alertes de tilt
    # -----------------------------------------------------------------------
    st.subheader("EQUITY // Courbe d'équité en R cumulé & Alertes tilt")
    fig_equity = build_equity_curve_figure(filtered_trades, tilt_alerts)
    st.plotly_chart(fig_equity, use_container_width=True)

    # -----------------------------------------------------------------------
    # Visualisation 2 : Segmentation (Setup Tags & Régime Gamma)
    # -----------------------------------------------------------------------
    st.subheader("SEGMENTATION // Performance par segment")
    col_seg1, col_seg2 = st.columns(2)

    with col_seg1:
        setup_segments = segment_by_setup_tag(filtered_trades)
        fig_setup = build_segmentation_figure(
            setup_segments,
            title="Espérance par Setup Tag",
            by_label="Setup Tag",
        )
        st.plotly_chart(fig_setup, use_container_width=True)

    with col_seg2:
        gamma_segments = segment_by_gamma_regime(filtered_trades)
        fig_gamma = build_segmentation_figure(
            gamma_segments,
            title="Espérance par Régime Gamma",
            by_label="Régime Gamma",
        )
        st.plotly_chart(fig_gamma, use_container_width=True)

    # -----------------------------------------------------------------------
    # Visualisation 3 : Évolution temporelle de la conformité
    # -----------------------------------------------------------------------
    st.subheader("COMPLIANCE // Taux de conformité par séance")
    fig_compliance = build_compliance_timeline_figure(filtered_trades, config)
    st.plotly_chart(fig_compliance, use_container_width=True)

    # -----------------------------------------------------------------------
    # Section Coaching : Fuites chiffrées, forces & règles
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("COACHING // Rapport & Analyse qualitative")

    coaching = generate_coaching_report(
        trades=filtered_trades,
        period=period_type,
        period_label=period_label,
        config=config,
    )

    col_coach1, col_coach2 = st.columns(2)

    with col_coach1:
        st.markdown("#### TOP FUITES IDENTIFIÉES")
        if coaching.top_leaks:
            for i, leak in enumerate(coaching.top_leaks, 1):
                st.markdown(f"**{i}.** {leak}")
        else:
            st.info("Aucune fuite majeure identifiée sur cette sélection.")

        st.markdown("#### RÈGLE PRIORITAIRE À RENFORCER")
        if coaching.rule_to_reinforce:
            st.warning(f"**{coaching.rule_to_reinforce}**")
        else:
            n_flt = len(filtered_trades)
            min_s = config.validation.min_sessions
            st.info(
                f"Échantillon insuffisant ({n_flt}/{min_s} trades) "
                "— aucune violation récurrente confirmée statistiquement."
            )

    with col_coach2:
        st.markdown("#### FORCE À CONSERVER")
        if coaching.strength_to_keep:
            st.success(f"**{coaching.strength_to_keep}**")
        else:
            n_flt = len(filtered_trades)
            min_s = config.validation.min_sessions
            st.info(
                f"Échantillon en cours de constitution ({n_flt}/{min_s} trades) "
                "— maintenir la documentation rigoureuse de chaque trade."
            )

        st.markdown("#### OBJECTIFS MESURABLES")
        if coaching.measurable_goals:
            for goal in coaching.measurable_goals:
                st.markdown(f"- {goal}")
        else:
            st.info(
                f"Atteindre le seuil de {config.validation.min_sessions} trades documentés "
                "avant d'établir des cibles quantitatives d'amélioration."
            )

    # -----------------------------------------------------------------------
    # Détail des Alertes de Tilt Détectées
    # -----------------------------------------------------------------------
    if tilt_alerts:
        st.markdown("---")
        st.subheader(f"TILT // Détail des alertes ({len(tilt_alerts)})")
        alert_rows = []
        for a in tilt_alerts:
            alert_rows.append(
                {
                    "Séance": a.session_date,
                    "Pattern": a.pattern_type,
                    "Motif": a.reason,
                    "Trades impliqués": ", ".join(a.trades_involved),
                }
            )
        st.table(alert_rows)



if __name__ == "__main__":
    render_coaching_app()
