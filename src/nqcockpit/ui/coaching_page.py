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
from nqcockpit.ui.i18n import t, tr_text

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
            text=t(
                "Aucun trade disponible pour cette période",
                "No trades available for this period",
            ),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#787B86"},
        )
        fig.update_layout(
            **PLOTLY_LAYOUT_DEFAULTS,
            title=t(
                "Courbe d'équité (R cumulé)",
                "Equity Curve (Cumulative R)",
            ),
        )
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
    for i, tr in enumerate(sorted_trades, 1):
        current_r += tr.r_realized
        label = f"#{i} ({tr.session_date})"
        x_labels.append(label)
        cum_r.append(round(current_r, 4))
        trade_id_to_point[tr.trade_id] = (label, round(current_r, 4))

        contracts_str = f"{tr.contracts}" if tr.contracts is not None else "N/A"
        conforme_str = (
            t("Oui", "Yes")
            if not (tr.sl_moved or tr.early_exit)
            else t("Non", "No")
        )
        color_res = "#10B981" if tr.r_realized >= 0 else "#EF4444"
        txt = (
            f"<b>Trade #{i} [{tr.trade_id[:8]}]</b><br>"
            f"Date : {tr.session_date} {tr.entry_time_ny or ''}<br>"
            f"Direction : {tr.direction.value} | {t('Contrats', 'Contracts')} : {contracts_str}<br>"
            f"Setup : {tr.setup_tag or 'N/A'}<br>"
            f"{t('Résultat', 'Outcome')} : <b style='color:{color_res}'>{tr.r_realized:+.3f}R</b> "
            f"({tr.outcome.value})<br>"
            f"{t('R cumulé', 'Cumul. R')} : <b>{current_r:+.3f}R</b><br>"
            f"{t('Conforme aux règles', 'Rule compliant')} : {conforme_str}"
        )
        hover_texts.append(txt)

    # Courbe d'équité principale (Bleu laser Swetrix avec zone de remplissage dégradée)
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=cum_r,
            mode="lines+markers",
            name=t("R Cumulé", "Cumulative R"),
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
        annotation_text=t("Point d'équilibre (0.0 R)", "Breakeven (0.0 R)"),
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
                    tilt_lbl = t("Alerte Tilt", "Tilt Alert")
                    tilt_texts.append(
                        f"<b>{tilt_lbl} : {tr_text(alert.pattern_type)}</b><br>"
                        f"{t('Séance', 'Session')} : {alert.session_date}<br>"
                        f"{t('Motif', 'Reason')} : {tr_text(alert.reason)}"
                    )

        if tilt_x:
            fig.add_trace(
                go.Scatter(
                    x=tilt_x,
                    y=tilt_y,
                    mode="markers",
                    name=t("Alertes de Tilt", "Tilt Alerts"),
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
        title=t(
            "Courbe d'équité en R cumulé chronologique & Alertes de tilt",
            "Chronological Cumulative R Equity Curve & Tilt Alerts",
        ),
        xaxis_title=t("Séquence des Trades", "Trade Sequence"),
        yaxis_title=t("Performance R Cumulée", "Cumulative R Performance"),
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
            text=t("Aucun segment disponible", "No segments available"),
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
        val = stats.expectancy_r if stats.expectancy_r is not None else (stats.raw_mean_r or 0.0)
        exp_r.append(round(val, 3))

        sig_tag = "" if stats.sample_sufficient else t(" (n < seuil)", " (n < threshold)")
        disp_name = tr_text(name)
        labels.append(f"{disp_name}{sig_tag}")

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
            else t("Non significatif (n < seuil)", "Not significant (n < threshold)")
        )
        val_label = (
            t("Espérance confirmée", "Confirmed Expectancy")
            if stats.sample_sufficient
            else t("Moyenne empirique (n < seuil)", "Empirical Mean (n < threshold)")
        )
        suf_yes_no = (
            t("Oui", "Yes") if stats.sample_sufficient else t("Non", "No")
        )

        hover_texts.append(
            f"<b>{by_label} : {disp_name}</b><br>"
            f"Trades : {stats.n_trades}<br>"
            f"{val_label} : <b>{val:+.3f}R</b><br>"
            f"IC 95% : {exp_ci_str}<br>"
            f"Win Rate : <b>{wr_str}</b> (IC Wilson : {ci_str})<br>"
            f"{t('Wins / Pertes', 'Wins / Losses')} : {stats.n_wins} / {stats.n_losses}<br>"
            f"{t('Échantillon suffisant', 'Sufficient sample')} : {suf_yes_no}"
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
        xaxis_title=t("Gain moyen par trade (R)", "Average Return per Trade (R)"),
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
            text=t(
                "Aucun trade disponible pour cette période",
                "No trades available for this period",
            ),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#787B86"},
        )
        fig.update_layout(
            **PLOTLY_LAYOUT_DEFAULTS,
            title=t(
                "Conformité aux règles dans le temps",
                "Rule Compliance Over Time",
            ),
        )
        return fig

    # Regrouper par session_date
    sessions: dict[str, list[TradeEntry]] = {}
    for tr in sorted(trades, key=lambda x: x.session_date):
        sessions.setdefault(tr.session_date, []).append(tr)

    session_dates: list[str] = []
    comp_rates: list[float] = []
    bar_colors: list[str] = []
    hover_texts: list[str] = []

    for s_date, s_trades in sessions.items():
        session_dates.append(s_date)
        n_total = len(s_trades)
        viol_trades_count = 0
        for tr in s_trades:
            if detect_violations(tr, s_trades, config):
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
            f"<b>{t('Séance', 'Session')} : {s_date}</b><br>"
            f"{t('Trades totaux', 'Total trades')} : {n_total}<br>"
            f"{t('Trades conformes', 'Compliant trades')} : {n_compliant} / {n_total}<br>"
            f"{t('Conformité', 'Compliance')} : <b>{rate:.1f}%</b>"
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
            name=t("Conformité (%)", "Compliance (%)"),
        )
    )

    # Ligne cible 100%
    fig.add_hline(
        y=100.0,
        line_dash="dot",
        line_color="#10B981",
        line_width=1.5,
        annotation_text=t("Objectif Discipline 100%", "100% Discipline Target"),
        annotation_position="top right",
        annotation_font_color="#10B981",
    )

    fig.update_layout(
        **PLOTLY_LAYOUT_DEFAULTS,
        title=t(
            "Taux de conformité aux règles par séance (%)",
            "Rule Compliance Rate per Session (%)",
        ),
        xaxis_title=t("Séance de Trading", "Trading Session"),
        yaxis_title=t("Discipline (%)", "Discipline (%)"),
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
    st.sidebar.markdown(
        f"**{t('Heure Alger', 'Algiers Time')}** : `{now_algiers.strftime('%Y-%m-%d %H:%M')}`"
    )
    st.sidebar.markdown(
        f"**{t('Base', 'Database')}** : `{Path(db_path_str).name}` ({len(all_trades)} trades)"
    )
    st.sidebar.markdown("---")

    period_options = [
        ("Toutes les données", "All data"),
        ("Cette semaine", "This week"),
        ("Semaine précédente", "Previous week"),
        ("Ce mois", "This month"),
        ("Mois précédent", "Previous month"),
        ("Plage personnalisée", "Custom range"),
    ]
    period_idx = st.sidebar.selectbox(
        t("Période d'analyse", "Analysis period"),
        options=list(range(len(period_options))),
        format_func=lambda idx: t(period_options[idx][0], period_options[idx][1]),
        index=0,
        key="coaching_period_idx",
    )

    filtered_trades: list[TradeEntry] = []
    period_title = t("Historique complet", "Full history")
    period_type = "hebdo"
    period_label = "global"

    if period_idx == 0:
        filtered_trades = all_trades
        period_title = t(
            f"Historique complet ({len(all_trades)} trades)",
            f"Full history ({len(all_trades)} trades)",
        )
        period_label = "complet"
    elif period_idx == 1:
        c_start, c_end, c_lbl, _, _, _ = get_period_bounds("week", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, c_start, c_end)
        period_title = t(
            f"Semaine en cours : {c_lbl} ({c_start} au {c_end})",
            f"Current week: {c_lbl} ({c_start} to {c_end})",
        )
        period_type = "hebdo"
        period_label = c_lbl
    elif period_idx == 2:
        _, _, _, p_start, p_end, p_lbl = get_period_bounds("week", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, p_start, p_end)
        period_title = t(
            f"Semaine précédente : {p_lbl} ({p_start} au {p_end})",
            f"Previous week: {p_lbl} ({p_start} to {p_end})",
        )
        period_type = "hebdo"
        period_label = p_lbl
    elif period_idx == 3:
        c_start, c_end, c_lbl, _, _, _ = get_period_bounds("month", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, c_start, c_end)
        period_title = t(
            f"Mois en cours : {c_lbl} ({c_start} au {c_end})",
            f"Current month: {c_lbl} ({c_start} to {c_end})",
        )
        period_type = "mensuel"
        period_label = c_lbl
    elif period_idx == 4:
        _, _, _, p_start, p_end, p_lbl = get_period_bounds("month", today_ny)
        filtered_trades = filter_trades_by_date_range(all_trades, p_start, p_end)
        period_title = t(
            f"Mois précédent : {p_lbl} ({p_start} au {p_end})",
            f"Previous month: {p_lbl} ({p_start} to {p_end})",
        )
        period_type = "mensuel"
        period_label = p_lbl
    elif period_idx == 5:
        col_d1, col_d2 = st.sidebar.columns(2)
        default_start = today_ny - timedelta(days=30)
        start_input = col_d1.date_input(t("Début", "Start"), default_start)
        end_input = col_d2.date_input(t("Fin", "End"), today_ny)
        if isinstance(start_input, date) and isinstance(end_input, date):
            filtered_trades = filter_trades_by_date_range(all_trades, start_input, end_input)
            period_title = t(
                f"Plage personnalisée ({start_input} au {end_input})",
                f"Custom range ({start_input} to {end_input})",
            )
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
            t(
                f"**Échantillon insuffisant** : {stats.n_trades} / {stats.min_trades_required} "
                "trades requis pour la validité statistique. Les métriques ci-dessous sont "
                "purement descriptives et n'ont pas de significativité statistique confirmée.",
                f"**Insufficient sample**: {stats.n_trades} / {stats.min_trades_required} "
                "trades required for statistical validity. The metrics below are purely "
                "descriptive and have no confirmed statistical significance.",
            )
        )
    else:
        st.success(
            t(
                f"**Échantillon statistiquement représentatif** : {stats.n_trades} trades "
                f"(seuil minimal {stats.min_trades_required} atteint).",
                f"**Statistically representative sample**: {stats.n_trades} trades "
                f"(minimum threshold of {stats.min_trades_required} reached).",
            )
        )

    # -----------------------------------------------------------------------
    # Cartes de Métriques Clés (KPI)
    # -----------------------------------------------------------------------
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    total_r = sum(t_item.r_realized for t_item in filtered_trades)

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
            <div class="metric-sub">{t('IC Wilson', 'Wilson CI')} : {ci_str}</div>
        </div>""",
            unsafe_allow_html=True,
        )

    with c2:
        exp_str = f"{stats.expectancy_r:+.3f}R" if stats.sample_sufficient else "—"
        exp_sub = (
            f"{t('IC', 'CI')} : [{stats.expectancy_ci_low:+.2f}, {stats.expectancy_ci_high:+.2f}]"
            if stats.sample_sufficient
            and stats.expectancy_ci_low is not None
            and stats.expectancy_ci_high is not None
            else t("Non significatif", "Not significant")
        )
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">{t('Espérance de gain', 'Expectancy')}</div>
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
            t(
                f"Série max : {stats.max_loss_streak} pertes",
                f"Max streak: {stats.max_loss_streak} losses",
            )
            if stats.sample_sufficient
            else t("Non significatif", "Not significant")
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
            <div class="metric-label">{t('Conformité', 'Compliance')}</div>
            <div class="metric-val">{comp_str}</div>
            <div class="metric-sub">{n_comp} / {stats.n_trades} trades</div>
        </div>""",
            unsafe_allow_html=True,
        )

    with c6:
        n_tilt = len(tilt_alerts)
        tilt_color = "ok" if n_tilt == 0 else "err"
        n_tilt_sess = len(set(a.session_date for a in tilt_alerts))
        sess_lbl = t("séance(s)", "session(s)")
        st.markdown(
            f"""<div class="metric-card">
            <div class="metric-label">{t('Alertes Tilt', 'Tilt Alerts')}</div>
            <div class="metric-val {tilt_color}">{n_tilt}</div>
            <div class="metric-sub">{n_tilt_sess} {sess_lbl}</div>
        </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # -----------------------------------------------------------------------
    # Visualisation 1 : Courbe d'équité & Timeline des alertes de tilt
    # -----------------------------------------------------------------------
    st.subheader(
        t(
            "EQUITY // Courbe d'équité en R cumulé & Alertes tilt",
            "EQUITY // Cumulative R Equity Curve & Tilt Alerts",
        )
    )
    fig_equity = build_equity_curve_figure(filtered_trades, tilt_alerts)
    st.plotly_chart(fig_equity, use_container_width=True)

    # -----------------------------------------------------------------------
    # Visualisation 2 : Segmentation (Setup Tags & Régime Gamma)
    # -----------------------------------------------------------------------
    st.subheader(
        t(
            "SEGMENTATION // Performance par segment",
            "SEGMENTATION // Performance by Segment",
        )
    )
    col_seg1, col_seg2 = st.columns(2)

    with col_seg1:
        setup_segments = segment_by_setup_tag(filtered_trades)
        fig_setup = build_segmentation_figure(
            setup_segments,
            title=t("Espérance par Setup Tag", "Expectancy by Setup Tag"),
            by_label="Setup Tag",
        )
        st.plotly_chart(fig_setup, use_container_width=True)

    with col_seg2:
        gamma_segments = segment_by_gamma_regime(filtered_trades)
        fig_gamma = build_segmentation_figure(
            gamma_segments,
            title=t("Espérance par Régime Gamma", "Expectancy by Gamma Regime"),
            by_label=t("Régime Gamma", "Gamma Regime"),
        )
        st.plotly_chart(fig_gamma, use_container_width=True)

    # -----------------------------------------------------------------------
    # Visualisation 3 : Évolution temporelle de la conformité
    # -----------------------------------------------------------------------
    st.subheader(
        t(
            "COMPLIANCE // Taux de conformité par séance",
            "COMPLIANCE // Compliance Rate by Session",
        )
    )
    fig_compliance = build_compliance_timeline_figure(filtered_trades, config)
    st.plotly_chart(fig_compliance, use_container_width=True)

    # -----------------------------------------------------------------------
    # Section Coaching : Fuites chiffrées, forces & règles
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader(
        t(
            "COACHING // Rapport & Analyse qualitative",
            "COACHING // Qualitative Report & Analysis",
        )
    )

    coaching = generate_coaching_report(
        trades=filtered_trades,
        period=period_type,
        period_label=period_label,
        config=config,
    )

    col_coach1, col_coach2 = st.columns(2)

    with col_coach1:
        st.markdown(f"#### {t('TOP FUITES IDENTIFIÉES', 'TOP IDENTIFIED LEAKS')}")
        if coaching.top_leaks:
            for i, leak in enumerate(coaching.top_leaks, 1):
                st.markdown(f"**{i}.** {tr_text(leak)}")
        else:
            st.info(
                t(
                    "Aucune fuite majeure identifiée sur cette sélection.",
                    "No major leak identified on this selection.",
                )
            )

        st.markdown(f"#### {t('RÈGLE PRIORITAIRE À RENFORCER', 'PRIORITY RULE TO REINFORCE')}")
        if coaching.rule_to_reinforce:
            st.warning(f"**{tr_text(coaching.rule_to_reinforce)}**")
        else:
            n_flt = len(filtered_trades)
            min_s = config.validation.min_sessions
            st.info(
                t(
                    f"Échantillon insuffisant ({n_flt}/{min_s} trades) "
                    "— aucune violation récurrente confirmée statistiquement.",
                    f"Insufficient sample ({n_flt}/{min_s} trades) "
                    "— no statistically confirmed recurring violation.",
                )
            )

    with col_coach2:
        st.markdown(f"#### {t('FORCE À CONSERVER', 'STRENGTH TO KEEP')}")
        if coaching.strength_to_keep:
            st.success(f"**{tr_text(coaching.strength_to_keep)}**")
        else:
            n_flt = len(filtered_trades)
            min_s = config.validation.min_sessions
            st.info(
                t(
                    f"Échantillon en cours de constitution ({n_flt}/{min_s} trades) "
                    "— maintenir la documentation rigoureuse de chaque trade.",
                    f"Sample being built ({n_flt}/{min_s} trades) "
                    "— maintain rigorous documentation of each trade.",
                )
            )

        st.markdown(f"#### {t('OBJECTIFS MESURABLES', 'MEASURABLE GOALS')}")
        if coaching.measurable_goals:
            for goal in coaching.measurable_goals:
                st.markdown(f"- {tr_text(goal)}")
        else:
            st.info(
                t(
                    f"Atteindre le seuil de {config.validation.min_sessions} trades documentés "
                    "avant d'établir des cibles quantitatives d'amélioration.",
                    f"Reach the threshold of {config.validation.min_sessions} documented trades "
                    "before setting quantitative improvement targets.",
                )
            )

    # -----------------------------------------------------------------------
    # Détail des Alertes de Tilt Détectées
    # -----------------------------------------------------------------------
    if tilt_alerts:
        st.markdown("---")
        st.subheader(
            f"TILT // {t('Détail des alertes', 'Alert Details')} ({len(tilt_alerts)})"
        )
        alert_rows = []
        for a in tilt_alerts:
            alert_rows.append(
                {
                    t("Séance", "Session"): a.session_date,
                    "Pattern": a.pattern_type,
                    t("Motif", "Reason"): tr_text(a.reason),
                    t("Trades impliqués", "Trades involved"): ", ".join(a.trades_involved),
                }
            )
        st.table(alert_rows)


if __name__ == "__main__":
    render_coaching_app()

