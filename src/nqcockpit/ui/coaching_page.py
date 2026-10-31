"""Page Streamlit P11 — Coaching & Analytics de performance.

Refonte orientée « valeur » : chaque panneau lit uniquement les champs déjà
présents dans le schéma du journal (aucune colonne DB, aucune migration) et
affiche chaque statistique avec son échantillon et, le cas échéant, son
intervalle de confiance. Les chiffres sont exprimés en R (unités de risque) ;
aucun montant en devise n'est inventé.

Panneaux (dans l'ordre) :
1. Cartes KPI + badge de taille d'échantillon
2. Courbe d'équité (R cumulé chronologique, drawdown, marqueurs tilt/violation)
3. Heatmap heure (session NY) x jour de semaine + meilleure/pire heure
4. Table des setups + barres d'espérance par régime (gamma / volatilité / événement)
5. Coût des violations de règles
6. Timeline des séries de pertes et alertes de tilt
7. Constats chiffrés (insights)
8. Filtres en haut (période, instrument, setup)

Le rapport `generate_coaching_report` reste disponible dans un expander en bas,
sans duplication de son contenu dans les panneaux ci-dessus.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.coaching.analytics import (
    HEATMAP_MIN_CELL_SAMPLES,
    MIN_SEGMENT_SAMPLES,
    WEEKDAY_LABELS,
    aggregate_heatmap,
    compute_drawdown_series,
    compute_insights,
    compute_loss_streaks,
    compute_max_drawdown,
    compute_rule_break_cost,
    current_loss_streak,
    heatmap_grid,
    segment_table_rows,
    sort_trades_chronologically,
    split_by_stop,
)
from nqcockpit.config import AppConfig, load_config
from nqcockpit.journal.engine import (
    compute_performance_stats,
    detect_period_tilt_alerts,
    detect_violations,
    generate_coaching_report,
    segment_performance,
)
from nqcockpit.journal.models import TradeEntry
from nqcockpit.journal.reports import filter_trades_by_date_range
from nqcockpit.journal.store import load_trades
from nqcockpit.ui.db import get_ui_db
from nqcockpit.ui.i18n import t, tr_text
from nqcockpit.ui.journal_page import journal_segment_label

# ---------------------------------------------------------------------------
# Palette & thème sombre cohérent
# ---------------------------------------------------------------------------

BG = "#0B1220"
PANEL = "#111827"
BORDER = "#1F2937"
TEXT = "#F8FAFC"
MUTED = "#94A3B8"
GAIN = "#10B981"   # vert — gains
LOSS = "#EF4444"   # rouge — pertes
WARN = "#F59E0B"   # ambre — avertissements / faible échantillon
ACCENT = "#38BDF8"  # accent neutre (courbe d'équité)

_FONT_FAMILY = (
    "-apple-system, system-ui, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"
)
_MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

PLOTLY_LAYOUT_DEFAULTS: dict[str, Any] = {
    "template": "plotly_dark",
    "paper_bgcolor": BG,
    "plot_bgcolor": PANEL,
    "colorway": [ACCENT, GAIN, LOSS, WARN, "#A78BFA", "#F472B6"],
    "font": {"color": TEXT, "family": _FONT_FAMILY},
    "title_font": {"size": 15, "color": TEXT},
    "title_x": 0.02,
    "title_xanchor": "left",
    "title_y": 0.96,
    "title_yanchor": "top",
    "margin": {"l": 55, "r": 25, "t": 60, "b": 45},
    "xaxis_gridcolor": "rgba(31, 41, 55, 0.55)",
    "xaxis_linecolor": BORDER,
    "xaxis_zerolinecolor": "rgba(31, 41, 55, 0.9)",
    "yaxis_gridcolor": "rgba(31, 41, 55, 0.55)",
    "yaxis_linecolor": BORDER,
    "yaxis_zerolinecolor": "rgba(31, 41, 55, 0.9)",
    "hoverlabel": {
        "bgcolor": PANEL,
        "bordercolor": "rgba(148, 163, 184, 0.5)",
        "font": {"family": _MONO, "size": 12, "color": TEXT},
    },
}

COACHING_CSS = """
<style>
.coach-title {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #F8FAFC;
    margin-bottom: 2px;
}
.coach-sub { color: #94A3B8; font-size: 0.8rem; margin-bottom: 12px; }
.coach-title-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.coach-title-row .sample-badge { margin: 0; }
.scroll-box { max-height: 440px; overflow-y: auto; padding-right: 4px; }
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
    gap: 10px;
    margin: 8px 0 4px 0;
}
.kpi-card {
    background: #111827;
    border: 1px solid #1F2937;
    border-radius: 10px;
    padding: 13px 15px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.25);
}
.kpi-label {
    font-size: 0.66rem;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 700;
    margin-bottom: 5px;
}
.kpi-value {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 1.5rem;
    font-weight: 700;
    color: #F8FAFC;
    line-height: 1.1;
    letter-spacing: -0.02em;
}
.kpi-caption { font-size: 0.72rem; color: #94A3B8; margin-top: 5px; line-height: 1.35; }
.kpi-pos { color: #10B981; }
.kpi-neg { color: #EF4444; }
.kpi-warn { color: #F59E0B; }
.kpi-mut { color: #94A3B8; }
.sample-badge {
    display: inline-block;
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 999px;
    margin: 4px 4px 4px 0;
}
.sample-ok {
    background: rgba(16,185,129,0.12);
    border: 1px solid rgba(16,185,129,0.4);
    color: #6EE7B7;
}
.sample-warn {
    background: rgba(245,158,11,0.12);
    border: 1px solid rgba(245,158,11,0.4);
    color: #FCD34D;
}
.section-title {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    color: #E2E8F0;
    margin: 18px 0 4px 0;
    border-left: 3px solid #38BDF8;
    padding-left: 9px;
}
.section-note { color: #94A3B8; font-size: 0.76rem; margin-bottom: 8px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin: 6px 0 10px 0; }
.tbl th {
    text-align: left;
    color: #94A3B8;
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 7px 9px;
    border-bottom: 1px solid #1F2937;
}
.tbl td {
    padding: 7px 9px;
    border-bottom: 1px solid rgba(31,41,55,0.55);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    color: #E2E8F0;
}
.tbl tr.low-sample td { color: #64748B; opacity: 0.7; }
.tbl .num { text-align: right; }
.insight {
    background: #111827;
    border: 1px solid #1F2937;
    border-radius: 10px;
    padding: 13px 16px;
    margin: 8px 0;
}
.insight-body { color: #E2E8F0; font-size: 0.9rem; line-height: 1.5; }
.conf {
    display: inline-block;
    font-family: ui-monospace, monospace;
    font-size: 0.66rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 2px 8px;
    border-radius: 999px;
    margin-left: 8px;
    vertical-align: 1px;
}
.conf-high {
    background: rgba(16,185,129,0.12);
    color: #6EE7B7;
    border: 1px solid rgba(16,185,129,0.4);
}
.conf-medium {
    background: rgba(245,158,11,0.12);
    color: #FCD34D;
    border: 1px solid rgba(245,158,11,0.4);
}
.conf-low {
    background: rgba(148,163,184,0.12);
    color: #94A3B8;
    border: 1px solid rgba(148,163,184,0.35);
}
</style>
"""

_HEAT_COLORSCALE: list[list[Any]] = [
    [0.0, LOSS],
    [0.5, "#1F2937"],
    [1.0, GAIN],
]

_WEEKDAY_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven"]


def _fmt_r(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{decimals}f}R"


def _fmt_pct(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{decimals}f}%"


def _naive_dt(dt: datetime) -> datetime:
    """Strip timezone info so Plotly never mixes naive and aware datetimes."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _weekday_label(weekday: int) -> str:
    if 0 <= weekday <= 4:
        return t(_WEEKDAY_FR[weekday], WEEKDAY_LABELS[weekday])
    return "?"


def _section(fr: str, en: str, note_fr: str = "", note_en: str = "") -> None:
    """Section heading + optional note, localized."""
    html = f'<div class="section-title">{t(fr, en)}</div>'
    if note_fr:
        html += f'<div class="section-note">{t(note_fr, note_en)}</div>'
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Figures Plotly
# ---------------------------------------------------------------------------


def build_equity_curve_figure(
    trades: list[TradeEntry],
    tilt_alerts: list | None = None,
    config: AppConfig | None = None,
    show_violations: bool = True,
    show_tilt: bool = True,
) -> go.Figure:
    """Courbe d'équité en R cumulé chronologique avec drawdown et marqueurs."""
    fig = go.Figure()
    empty_text = t(
        "Aucun trade disponible pour cette période",
        "No trades available for this period",
    )
    if not trades:
        fig.add_annotation(
            text=empty_text,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": MUTED},
        )
        fig.update_layout(
            **PLOTLY_LAYOUT_DEFAULTS,
            title=t("Courbe d'équité (R cumulé)", "Equity Curve (Cumulative R)"),
        )
        return fig

    points = compute_drawdown_series(trades)
    xs = [_naive_dt(p.timestamp) for p in points]
    cum_r = [p.cum_r for p in points]
    underwater = [-p.underwater_r for p in points]

    violated_ids: set[str] = set()
    if config is not None:
        by_session: dict[str, list[TradeEntry]] = {}
        for trade in trades:
            by_session.setdefault(trade.session_date, []).append(trade)
        for session_trades in by_session.values():
            for trade in session_trades:
                if detect_violations(trade, session_trades, config):
                    violated_ids.add(trade.trade_id)
    else:
        violated_ids = {tr.trade_id for tr in trades if tr.sl_moved or tr.early_exit}

    tilt_ids: set[str] = set()
    for alert in tilt_alerts or []:
        tilt_ids.update(alert.trades_involved)

    # 1. Drawdown immergé (ombrage rouge sous l'axe).
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=underwater,
            mode="lines",
            name=t("Drawdown", "Drawdown"),
            line={"color": "rgba(239, 68, 68, 0)", "width": 0},
            fill="tozeroy",
            fillcolor="rgba(239, 68, 68, 0.16)",
            hoverinfo="skip",
            showlegend=False,
        )
    )

    hover_texts: list[str] = []
    for index, point in enumerate(points, 1):
        color = GAIN if point.r >= 0 else LOSS
        hover_texts.append(
            f"<b>#{index} · {point.session_date} {point.timestamp.strftime('%H:%M')}</b><br>"
            f"{t('Résultat', 'Outcome')} : <b style='color:{color}'>{point.r:+.2f}R</b><br>"
            f"{t('R cumulé', 'Cumulative R')} : <b>{point.cum_r:+.2f}R</b><br>"
            f"{t('Drawdown', 'Drawdown')} : {point.underwater_r:.2f}R"
        )

    # 2. Courbe d'équité cumulée.
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=cum_r,
            mode="lines+markers",
            name=t("R cumulé", "Cumulative R"),
            line={"color": ACCENT, "width": 2.6},
            marker={
                "size": 6,
                "color": [GAIN if p.r >= 0 else LOSS for p in points],
                "line": {"color": BG, "width": 0.8},
            },
            hovertext=hover_texts,
            hoverinfo="text",
        )
    )

    # 3. Pic de drawdown marqué (losange ambre).
    max_dd, trough_index = compute_max_drawdown(trades)
    if trough_index >= 0:
        trough = points[trough_index]
        fig.add_trace(
            go.Scatter(
                x=[_naive_dt(trough.timestamp)],
                y=[trough.cum_r],
                mode="markers",
                name=t("Drawdown max", "Max drawdown"),
                marker={
                    "symbol": "diamond",
                    "size": 13,
                    "color": WARN,
                    "line": {"color": BG, "width": 1},
                },
                hovertext=[
                    f"<b>{t('Drawdown max', 'Max drawdown')} : -{max_dd:.2f}R</b><br>"
                    f"{trough.session_date} {trough.timestamp.strftime('%H:%M')}"
                ],
                hoverinfo="text",
            )
        )

    # 4. Trades en violation de règle (ambre).
    if show_violations and violated_ids:
        vx = [xs[i] for i, p in enumerate(points) if p.trade_id in violated_ids]
        vy = [p.cum_r for p in points if p.trade_id in violated_ids]
        fig.add_trace(
            go.Scatter(
                x=vx,
                y=vy,
                mode="markers",
                name=t("Violation de règle", "Rule violation"),
                marker={
                    "symbol": "triangle-down",
                    "size": 12,
                    "color": WARN,
                    "line": {"color": BG, "width": 1},
                },
                hovertext=[t("Violation de règle", "Rule violation")] * len(vx),
                hoverinfo="text",
            )
        )

    # 5. Alertes de tilt (rouge).
    if show_tilt and tilt_ids:
        tx = [xs[i] for i, p in enumerate(points) if p.trade_id in tilt_ids]
        ty = [p.cum_r for p in points if p.trade_id in tilt_ids]
        fig.add_trace(
            go.Scatter(
                x=tx,
                y=ty,
                mode="markers",
                name=t("Alerte tilt", "Tilt alert"),
                marker={
                    "symbol": "x",
                    "size": 11,
                    "color": LOSS,
                    "line": {"color": BG, "width": 1.5},
                },
                hovertext=[t("Alerte tilt", "Tilt alert")] * len(tx),
                hoverinfo="text",
            )
        )

    fig.add_hline(
        y=0.0,
        line_dash="dot",
        line_color="rgba(148, 163, 184, 0.4)",
        line_width=1.2,
    )
    fig.update_layout(
        **PLOTLY_LAYOUT_DEFAULTS,
        title=t(
            "Courbe d'équité chronologique (R cumulé)",
            "Chronological Equity Curve (Cumulative R)",
        ),
        xaxis_title=t("Date / heure (NY)", "Date / time (NY)"),
        yaxis_title=t("R cumulé", "Cumulative R"),
        hovermode="closest",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"size": 11, "color": MUTED},
        },
    )
    return fig


def build_heatmap_figure(trades: list[TradeEntry]) -> go.Figure:
    """Heatmap espérance R par heure (NY) x jour de semaine."""
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
            font={"size": 14, "color": MUTED},
        )
        fig.update_layout(
            **PLOTLY_LAYOUT_DEFAULTS,
            title=t("Performance par heure x jour", "Performance by hour x weekday"),
        )
        return fig

    hours, z_exp, z_n, z_total = heatmap_grid(trades)
    z_display: list[list[float | None]] = []
    customdata: list[list[list[float]]] = []
    for weekday in range(5):
        row_z: list[float | None] = []
        row_cd: list[list[float]] = []
        for hour_index in range(len(hours)):
            n = z_n[weekday][hour_index]
            exp = z_exp[weekday][hour_index]
            total = z_total[weekday][hour_index]
            if n == 0:
                row_z.append(None)
                row_cd.append([0, 0.0])
            else:
                row_z.append(exp if n >= HEATMAP_MIN_CELL_SAMPLES else None)
                row_cd.append([float(n), total])
        z_display.append(row_z)
        customdata.append(row_cd)

    fig.add_trace(
        go.Heatmap(
            z=z_display,
            x=[f"{h:02d}:00" for h in hours],
            y=[_weekday_label(w) for w in range(5)],
            colorscale=_HEAT_COLORSCALE,
            zmid=0.0,
            customdata=customdata,
            hovertemplate=(
                "%{y} %{x}<br>"
                + t("Espérance", "Expectancy")
                + " : %{z:+.2f}R<br>"
                + t("Trades", "Trades")
                + " : %{customdata[0]:.0f}<br>"
                + t("R total", "Total R")
                + " : %{customdata[1]:+.2f}R<extra></extra>"
            ),
            colorbar={
                "title": {
                    "text": t("Espérance R", "Expectancy R"),
                    "font": {"color": MUTED, "size": 11},
                },
                "tickfont": {"color": MUTED, "size": 10},
                "outlinewidth": 0,
            },
        )
    )
    fig.update_layout(
        **PLOTLY_LAYOUT_DEFAULTS,
        title=t(
            "Espérance par heure (session NY) x jour de semaine",
            "Expectancy by hour (NY session) x weekday",
        ),
        xaxis_title=t("Heure (ET)", "Hour (ET)"),
        yaxis_title=t("Jour de semaine", "Weekday"),
    )
    return fig


def build_segmentation_figure(
    segments: dict,
    title: str,
    by_label: str,
) -> go.Figure:
    """Barres horizontales d'espérance pour un segment (régime gamma/vol/événement)."""
    fig = go.Figure()
    if not segments:
        fig.add_annotation(
            text=t("Aucun segment disponible", "No segments available"),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": MUTED},
        )
        fig.update_layout(**PLOTLY_LAYOUT_DEFAULTS, title=title)
        return fig

    labels: list[str] = []
    values: list[float] = []
    colors: list[str] = []
    hover_texts: list[str] = []
    for name, stats in segments.items():
        value = stats.expectancy_r if stats.expectancy_r is not None else (stats.raw_mean_r or 0.0)
        low = stats.n_trades < MIN_SEGMENT_SAMPLES
        suffix = t(" (n faible)", " (low sample)") if low else ""
        labels.append(f"{journal_segment_label(name)}{suffix}")
        values.append(round(value, 3))
        colors.append(MUTED if low else (GAIN if value >= 0 else LOSS))
        hover_texts.append(
            f"<b>{journal_segment_label(name)}</b><br>"
            f"{t('Trades', 'Trades')} : {stats.n_trades}<br>"
            f"{t('Espérance', 'Expectancy')} : <b>{value:+.3f}R</b><br>"
            f"{t('Win rate', 'Win rate')} : {_fmt_pct(stats.win_rate)}"
        )

    fig.add_trace(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker={"color": colors, "line": {"color": "rgba(255,255,255,0.12)", "width": 1}},
            hovertext=hover_texts,
            hoverinfo="text",
        )
    )
    fig.add_vline(x=0.0, line_dash="dot", line_color="rgba(148, 163, 184, 0.5)", line_width=1.2)
    fig.update_layout(
        **PLOTLY_LAYOUT_DEFAULTS,
        title=title,
        xaxis_title=t("Espérance par trade (R)", "Expectancy per trade (R)"),
        yaxis_title=by_label,
        yaxis={"autorange": "reversed"},
    )
    return fig


# ---------------------------------------------------------------------------
# Helpers de rendu
# ---------------------------------------------------------------------------


def _kpi_card(label: str, value: str, caption: str, value_class: str = "") -> str:
    return (
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value {value_class}">{value}</div>'
        f'<div class="kpi-caption">{caption}</div></div>'
    )


def _sample_badge(n: int, required: int) -> str:
    if n >= required:
        cls = "sample-ok"
        label = t(f"Échantillon fiable : {n}/{required}", f"Reliable sample: {n}/{required}")
    else:
        cls = "sample-warn"
        label = t(f"{n}/{required} — descriptif seulement", f"{n}/{required} — descriptive only")
    return f'<span class="sample-badge {cls}">{label}</span>'


def _render_setup_table(trades: list[TradeEntry]) -> None:
    segments = segment_performance(trades, by="setup_tag", min_samples=MIN_SEGMENT_SAMPLES)
    rows = segment_table_rows(segments)
    if not rows:
        st.info(t("Aucun setup enregistré.", "No setup recorded."))
        return

    head = (
        "<table class='tbl'><thead><tr>"
        f"<th>{t('Setup', 'Setup')}</th>"
        f"<th class='num'>{t('n', 'n')}</th>"
        f"<th class='num'>{t('Win rate', 'Win rate')}</th>"
        f"<th class='num'>{t('Espérance', 'Expectancy')} R</th>"
        f"<th class='num'>{t('PF', 'PF')}</th>"
        f"<th class='num'>{t('Gain moy.', 'Avg win')} R</th>"
        f"<th class='num'>{t('Perte moy.', 'Avg loss')} R</th>"
        f"<th>{t('Échantillon', 'Sample')}</th>"
        "</tr></thead><tbody>"
    )
    body: list[str] = []
    for row in rows:
        cls = "low-sample" if row.low_sample else ""
        flag = t("faible", "low sample") if row.low_sample else t("ok", "ok")
        expectancy_class = "kpi-pos" if row.expectancy_r >= 0 else "kpi-neg"
        pf = f"{row.profit_factor:.2f}" if row.profit_factor is not None else "—"
        body.append(
            f"<tr class='{cls}'>"
            f"<td>{journal_segment_label(row.label)}</td>"
            f"<td class='num'>{row.n}</td>"
            f"<td class='num'>{_fmt_pct(row.win_rate)}</td>"
            f"<td class='num'><span class='{expectancy_class}'>{row.expectancy_r:+.2f}</span></td>"
            f"<td class='num'>{pf}</td>"
            f"<td class='num'>{_fmt_r(row.avg_win_r)}</td>"
            f"<td class='num'>{_fmt_r(row.avg_loss_r)}</td>"
            f"<td>{flag}</td>"
            "</tr>"
        )
    st.markdown(head + "".join(body) + "</tbody></table>", unsafe_allow_html=True)


def _render_rule_break(trades: list[TradeEntry], config: AppConfig) -> None:
    cost = compute_rule_break_cost(trades, config)
    if cost.n_compliant + cost.n_noncompliant == 0:
        st.info(t("Aucun trade à analyser.", "No trade to analyse."))
        return

    gap_color = GAIN if (cost.gap_per_trade_r or 0) >= 0 else LOSS
    total_color = GAIN if cost.total_r_noncompliant >= 0 else LOSS

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            "<div class='insight'>"
            f"<div class='kpi-label'>"
            f"{t('Espérance conforme vs non conforme', 'Compliant vs non-compliant')}"
            "</div><div class='insight-body'>"
            f"{t('Conformes', 'Compliant')} ({cost.n_compliant}) : "
            f"<b>{_fmt_r(cost.expectancy_compliant)}</b><br>"
            f"{t('Non conformes', 'Non-compliant')} ({cost.n_noncompliant}) : "
            f"<b>{_fmt_r(cost.expectancy_noncompliant)}</b><br>"
            f"{t('Écart par trade', 'Gap per trade')} : "
            f"<b style='color:{gap_color}'>{_fmt_r(cost.gap_per_trade_r)}</b>"
            "</div></div>",
            unsafe_allow_html=True,
        )
    with c2:
        cost_label = t("Coût total des violations", "Total cost of rule breaks")
        st.markdown(
            "<div class='insight'>"
            f"<div class='kpi-label'>{cost_label}</div>"
            "<div class='insight-body'>"
            f"{t('R cumulé des trades non conformes', 'Cumulative R on non-compliant trades')} : "
            f"<b style='color:{total_color}'>{cost.total_r_noncompliant:+.2f}R</b><br>"
            f"{t('SL déplacé', 'SL moved')} ({cost.n_sl_moved}) : "
            f"{_fmt_r(cost.sl_moved_avg_r)} {t('vs', 'vs')} {_fmt_r(cost.no_sl_moved_avg_r)}<br>"
            f"{t('Sortie anticipée', 'Early exit')} ({cost.n_early_exit}) : "
            f"{_fmt_r(cost.early_exit_avg_r)} {t('vs', 'vs')} {_fmt_r(cost.no_early_exit_avg_r)}"
            "</div></div>",
            unsafe_allow_html=True,
        )


def _render_streak_tilt(trades: list[TradeEntry], config: AppConfig) -> None:
    if not trades:
        st.info(t("Aucun trade à analyser.", "No trade to analyse."))
        return

    streaks = compute_loss_streaks(trades)
    tilt_alerts = detect_period_tilt_alerts(trades, config)
    ordered = sort_trades_chronologically(trades)

    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.markdown(
            f"<div class='kpi-label'>{t('Séries de pertes', 'Loss streaks')}</div>",
            unsafe_allow_html=True,
        )
        if not streaks:
            st.info(t("Aucune série de 2 pertes consécutives ou plus.", "No streak of 2+ losses."))
        else:
            for s in streaks:
                span = (
                    f"{_weekday_label(s.start_ts.weekday())} "
                    f"{s.start_ts.strftime('%m-%d %H:%M')} → "
                    f"{_weekday_label(s.end_ts.weekday())} "
                    f"{s.end_ts.strftime('%m-%d %H:%M')}"
                )
                cum_r_note = f"{t('R cumulé', 'Cumulative R')} : {s.total_r:+.2f}R"
                st.markdown(
                    f"<div class='insight'>"
                    f"<b>{s.length} {t('pertes', 'losses')}</b> · {span}<br>"
                    f"<span style='color:{MUTED}'>{cum_r_note}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )

    with c2:
        tilt_title = t("Alertes de tilt et ce qui a suivi", "Tilt alerts and what followed")
        st.markdown(
            f"<div class='kpi-label'>{tilt_title}</div>",
            unsafe_allow_html=True,
        )
        if not tilt_alerts:
            st.info(t("Aucune alerte de tilt détectée.", "No tilt alert detected."))
        else:
            items: list[str] = []
            for alert in tilt_alerts:
                involved = [tr for tr in ordered if tr.trade_id in set(alert.trades_involved)]
                last = involved[-1] if involved else None
                followup_html = "—"
                if last is not None:
                    last_index = ordered.index(last)
                    following = ordered[last_index + 1 : last_index + 3]
                    if following:
                        pieces = []
                        for tr in following:
                            color = GAIN if tr.r_realized >= 0 else LOSS
                            pieces.append(
                                f"<span style='color:{color}'>{tr.r_realized:+.2f}R</span> "
                                f"({tr.session_date})"
                            )
                        followup_html = " · ".join(pieces)
                items.append(
                    f"<div class='insight'>"
                    f"<b>{alert.session_date}</b> — {tr_text(alert.pattern_type)}<br>"
                    f"<span style='color:{MUTED}'>{tr_text(alert.reason)}</span><br>"
                    f"{t('Trade(s) suivant(s)', 'Following trade(s)')} : {followup_html}"
                    "</div>"
                )
            st.markdown(
                "<div class='scroll-box'>" + "".join(items) + "</div>",
                unsafe_allow_html=True,
            )


def _confidence_html(confidence: str) -> str:
    labels = {
        "high": (t("haute confiance", "high confidence"), "conf-high"),
        "medium": (t("confiance moyenne", "medium confidence"), "conf-medium"),
        "low": (t("faible échantillon", "low sample"), "conf-low"),
    }
    text, cls = labels.get(confidence, labels["low"])
    return f"<span class='conf {cls}'>{text}</span>"


def _insight_sentence(insight) -> str:
    kind = insight.kind
    label = journal_segment_label(insight.label) if insight.label else ""
    value = insight.value
    n = insight.n
    if kind == "best_setup":
        return t(
            f"« {label} » est le setup le plus performant : espérance de "
            f"{value:+.2f}R sur {n} trades.",
            f"“{label}” is the best-performing setup: expectancy of "
            f"{value:+.2f}R over {n} trades.",
        )
    if kind == "worst_setup":
        return t(
            f"« {label} » est le setup le moins performant : espérance de "
            f"{value:+.2f}R sur {n} trades.",
            f"“{label}” is the weakest setup: expectancy of "
            f"{value:+.2f}R over {n} trades.",
        )
    if kind == "rule_break":
        total = insight.extra.get("total_r", 0.0)
        return t(
            f"Les trades non conformes cumulent {total:+.2f}R ; écart d'espérance de "
            f"{value:+.2f}R par trade par rapport aux trades conformes.",
            f"Non-compliant trades total {total:+.2f}R; expectancy gap of "
            f"{value:+.2f}R per trade versus compliant trades.",
        )
    if kind in ("gamma_regime", "vol_regime", "event_risk"):
        return t(
            f"Espérance négative dans le segment « {label} » : {value:+.2f}R sur {n} trades.",
            f"Negative expectancy in the “{label}” segment: {value:+.2f}R over {n} trades.",
        )
    if kind in ("best_hour", "worst_hour"):
        hour_label = f"{_weekday_label(insight.weekday or 0)} {(insight.hour or 0):02d}:00 ET"
        if kind == "best_hour":
            return t(
                f"Meilleure heure : {hour_label}, espérance de {value:+.2f}R sur {n} trades.",
                f"Best hour: {hour_label}, expectancy of {value:+.2f}R over {n} trades.",
            )
        return t(
            f"Pire heure : {hour_label}, espérance de {value:+.2f}R sur {n} trades.",
            f"Worst hour: {hour_label}, expectancy of {value:+.2f}R over {n} trades.",
        )
    return ""


def _render_insights(trades: list[TradeEntry], config: AppConfig) -> None:
    if not trades:
        st.info(
            t(
                "Les constats chiffrés apparaîtront après les premiers trades documentés.",
                "Data-driven insights will appear after the first documented trades.",
            )
        )
        return

    insights = compute_insights(trades, config=config)
    if not insights:
        st.info(t("Pas encore assez de données.", "Not enough data yet."))
        return

    for insight in insights:
        body = _insight_sentence(insight)
        if not body:
            continue
        badge = _confidence_html(insight.confidence)
        st.markdown(
            f"<div class='insight'><div class='insight-body'>{body}{badge}</div></div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Application Streamlit
# ---------------------------------------------------------------------------


def _instrument_filter_labels(
    trades: list[TradeEntry],
) -> tuple[list[str], dict[str, str]]:
    """Instrument labels sorted by trade count (desc), count shown in the label."""
    counts: dict[str, int] = {}
    for tr in trades:
        if tr.instrument:
            counts[tr.instrument] = counts.get(tr.instrument, 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    labels = [f"{name} ({count})" for name, count in items]
    mapping = {f"{name} ({count})": name for name, count in items}
    return labels, mapping


def _unique_setups(trades: list[TradeEntry]) -> list[str]:
    return sorted({tr.setup_tag for tr in trades if tr.setup_tag})


def render_coaching_app() -> None:
    """Point d'entrée principal de l'interface Streamlit de coaching."""
    try:
        st.set_page_config(page_title="NQ Cockpit · Coaching", layout="wide")
    except StreamlitAPIException:
        pass

    st.markdown(COACHING_CSS, unsafe_allow_html=True)

    config = load_config()
    tz_market = ZoneInfo(config.timezones.market)
    today_ny = datetime.now(tz_market).date()

    db_path_str = os.getenv("NQ_DATA_DB_PATH", config.data.db_path)
    conn = get_ui_db(db_path_str)
    all_trades = load_trades(conn)

    # -----------------------------------------------------------------------
    # Filtres en haut : chaque panneau se met à jour ensemble
    # -----------------------------------------------------------------------
    f1, f2, f3 = st.columns([1, 1, 1])
    range_labels = [
        t("Derniers 30 jours", "Last 30 days"),
        t("Derniers 90 jours", "Last 90 days"),
        t("Toutes les données", "All data"),
    ]
    with f1:
        range_choice = st.selectbox(
            t("Période", "Date range"),
            options=range_labels,
            index=2,
            key="coaching_date_range",
        )
    with f2:
        instrument_labels, instrument_map = _instrument_filter_labels(all_trades)
        instrument_options = [t("Tous les instruments", "All instruments")] + instrument_labels
        instrument_choice = st.selectbox(
            t("Instrument", "Instrument"),
            options=instrument_options,
            key="coaching_instrument",
        )
    with f3:
        setup_options = [t("Tous les setups", "All setups")] + _unique_setups(all_trades)
        setup_choice = st.selectbox(
            t("Setup", "Setup"),
            options=setup_options,
            key="coaching_setup",
        )

    filtered = list(all_trades)
    if range_choice == range_labels[0]:
        filtered = filter_trades_by_date_range(filtered, today_ny - timedelta(days=30), today_ny)
    elif range_choice == range_labels[1]:
        filtered = filter_trades_by_date_range(filtered, today_ny - timedelta(days=90), today_ny)
    if instrument_choice != instrument_options[0]:
        filtered = [tr for tr in filtered if tr.instrument == instrument_map[instrument_choice]]
    if setup_choice != setup_options[0]:
        filtered = [tr for tr in filtered if tr.setup_tag == setup_choice]

    min_required = config.validation.min_sessions
    r_trades, no_r_trades = split_by_stop(filtered)
    no_r_count = len(no_r_trades)
    # Statistiques R calculées uniquement sur les trades avec stop (jamais de R inventé).
    stats = compute_performance_stats(r_trades, min_trades=min_required, config=config)
    # Effectif total + conformité calculés sur l'ensemble (indépendants du R).
    stats_all = compute_performance_stats(filtered, min_trades=min_required, config=config)
    tilt_alerts = detect_period_tilt_alerts(filtered, config)
    total_r = sum(tr.r_realized for tr in r_trades)
    current_streak = current_loss_streak(r_trades)

    # --- En-tête : titre + badge de taille d'échantillon ---
    title_text = t("ANALYSE DE PERFORMANCE", "PERFORMANCE ANALYTICS")
    header_html = (
        '<div class="coach-title-row">'
        f'<span class="coach-title">COACHING // {title_text}</span>'
        f"{_sample_badge(len(filtered), min_required)}"
        "</div>"
        f'<div class="coach-sub">{t("Base", "Database")} : {Path(db_path_str).name}</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)

    st.markdown("---")
    if not filtered:
        st.info(
            t(
                "Aucun trade ne correspond aux filtres choisis. Les panneaux ci-dessous "
                "se rempliront dès que des trades seront enregistrés.",
                "No trade matches the selected filters. The panels below will populate "
                "as soon as trades are recorded.",
            )
        )

    # --- KPI ---
    expectancy = stats.expectancy_r if stats.expectancy_r is not None else stats.raw_mean_r
    if stats.sample_sufficient and stats.expectancy_ci_low is not None:
        expectancy_sub = (
            f"{t('IC 95%', '95% CI')} : "
            f"[{stats.expectancy_ci_low:+.2f}, {stats.expectancy_ci_high:+.2f}]"
        )
    else:
        expectancy_sub = t(
            "descriptif (échantillon insuffisant)", "descriptive (insufficient sample)"
        )

    wr_value = _fmt_pct(stats.win_rate)
    if stats.win_rate_ci_low is not None and stats.win_rate_ci_high is not None:
        wr_sub = (
            f"{t('IC Wilson 95%', 'Wilson 95% CI')} : "
            f"[{_fmt_pct(stats.win_rate_ci_low)}, {_fmt_pct(stats.win_rate_ci_high)}]"
        )
    else:
        wr_sub = ""

    streak_sub = (
        f"{t('actuelle', 'current')} {current_streak} / "
        f"{t('max', 'max')} {stats.max_loss_streak}"
    )
    dd_value = f"-{stats.max_drawdown_r:.2f}R" if r_trades else "—"
    comp_value = _fmt_pct(stats_all.compliance_rate)
    comp_sub = f"{stats_all.n_compliant} / {stats_all.n_trades} {t('trades', 'trades')}"

    if expectancy is None:
        exp_class = "kpi-mut"
    elif expectancy >= 0:
        exp_class = "kpi-pos"
    else:
        exp_class = "kpi-neg"

    pf_value = f"{stats.profit_factor:.2f}" if stats.profit_factor is not None else "—"
    comp_class = "kpi-pos" if (stats_all.compliance_rate or 1) >= 0.8 else "kpi-warn"
    total_r_caption = t("R total", "Total R") + f" : {total_r:+.2f}R"

    cards = [
        _kpi_card(
            t("Trades", "Trades"),
            str(stats_all.n_trades),
            f"{stats_all.n_wins} W / {stats_all.n_losses} L / {stats_all.n_breakeven} BE",
        ),
        _kpi_card(t("Win rate", "Win rate"), wr_value, wr_sub),
        _kpi_card(
            t("Espérance", "Expectancy"),
            _fmt_r(expectancy),
            expectancy_sub,
            exp_class,
        ),
        _kpi_card(
            t("Profit factor", "Profit factor"),
            pf_value,
            total_r_caption,
        ),
        _kpi_card(
            t("Drawdown max", "Max drawdown"),
            dd_value,
            t("pic à creux", "peak to trough"),
            "kpi-neg",
        ),
        _kpi_card(
            t("Série de pertes", "Loss streak"),
            f"{current_streak}/{stats.max_loss_streak}",
            streak_sub,
        ),
        _kpi_card(t("Conformité", "Compliance"), comp_value, comp_sub, comp_class),
    ]
    st.markdown('<div class="kpi-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)

    if no_r_count > 0:
        no_r_note = t(
            "trade(s) exclus des stats R (sans stop)",
            "trade(s) excluded from R stats (no stop)",
        )
        st.markdown(
            f"<span style='color:{MUTED}; font-size:0.76rem;'>"
            f"{no_r_count} {no_r_note}</span>",
            unsafe_allow_html=True,
        )

    # --- 2. Courbe d'équité ---
    _section(
        "EQUITY // COURBE D'ÉQUITÉ",
        "EQUITY // EQUITY CURVE",
        "Équité en R (unités de risque)",
        "Equity in R (risk units)",
    )
    eq1, eq2 = st.columns([1, 1])
    with eq1:
        show_violations = st.toggle(
            t("Marqueurs de violation", "Rule-violation markers"),
            value=True,
            key="coaching_show_violations",
        )
    with eq2:
        show_tilt = st.toggle(
            t("Marqueurs de tilt", "Tilt markers"),
            value=True,
            key="coaching_show_tilt",
        )
    st.plotly_chart(
        build_equity_curve_figure(
            r_trades,
            tilt_alerts,
            config,
            show_violations=show_violations,
            show_tilt=show_tilt,
        ),
        use_container_width=True,
    )

    # --- 3. Heatmap heure x jour ---
    _section(
        "TIMING // HEATMAP HEURE × JOUR",
        "TIMING // HOUR × WEEKDAY HEATMAP",
        "Cellules sous le seuil d'échantillon estompées.",
        "Cells below the sample threshold are muted.",
    )
    ny_hour_note = t(
        "La vue par heure NY est surtout significative pour le Nasdaq (NQ/MNQ).",
        "The NY-hour view is most meaningful for Nasdaq (NQ/MNQ).",
    )
    st.markdown(
        f"<span style='color:{MUTED}; font-size:0.76rem;'>{ny_hour_note}</span>",
        unsafe_allow_html=True,
    )
    cells = aggregate_heatmap(r_trades)
    qualified_cells = {k: c for k, c in cells.items() if c.n >= HEATMAP_MIN_CELL_SAMPLES}
    hcol1, hcol2 = st.columns([3, 1])
    with hcol1:
        st.plotly_chart(build_heatmap_figure(r_trades), use_container_width=True)
    with hcol2:
        if qualified_cells:
            best_key = max(qualified_cells, key=lambda k: qualified_cells[k].expectancy_r)
            worst_key = min(qualified_cells, key=lambda k: qualified_cells[k].expectancy_r)
            best = qualified_cells[best_key]
            worst = qualified_cells[worst_key]
            st.markdown(
                "<div class='insight'>"
                f"<div class='kpi-label'>{t('Meilleure heure', 'Best hour')}</div>"
                "<div class='insight-body'>"
                f"{_weekday_label(best.weekday)} {best.hour:02d}:00 ET<br>"
                f"<b style='color:{GAIN if best.expectancy_r >= 0 else LOSS}'>"
                f"{best.expectancy_r:+.2f}R</b> ({best.n} {t('trades', 'trades')})"
                "</div></div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='insight'>"
                f"<div class='kpi-label'>{t('Pire heure', 'Worst hour')}</div>"
                "<div class='insight-body'>"
                f"{_weekday_label(worst.weekday)} {worst.hour:02d}:00 ET<br>"
                f"<b style='color:{GAIN if worst.expectancy_r >= 0 else LOSS}'>"
                f"{worst.expectancy_r:+.2f}R</b> ({worst.n} {t('trades', 'trades')})"
                "</div></div>",
                unsafe_allow_html=True,
            )
        else:
            not_enough = t(
                "Pas assez de données pour une heure fiable.",
                "Not enough data for a reliable hour.",
            )
            st.markdown(
                f"<span style='color:{MUTED}'>{not_enough}</span>",
                unsafe_allow_html=True,
            )

    # --- 4. Table des setups + barres par régime ---
    _section("SETUP & RÉGIME // PERFORMANCE PAR SEGMENT", "SETUP & REGIME // SEGMENT PERFORMANCE")
    _render_setup_table(r_trades)

    tab_gamma, tab_vol, tab_event = st.tabs(
        [
            t("Régime gamma", "Gamma regime"),
            t("Régime de volatilité", "Volatility regime"),
            t("Risque événementiel", "Event risk"),
        ]
    )
    with tab_gamma:
        st.plotly_chart(
            build_segmentation_figure(
                segment_performance(r_trades, by="gamma_regime", min_samples=MIN_SEGMENT_SAMPLES),
                title=t("Espérance par régime gamma", "Expectancy by gamma regime"),
                by_label=t("Régime gamma", "Gamma regime"),
            ),
            use_container_width=True,
        )
    with tab_vol:
        st.plotly_chart(
            build_segmentation_figure(
                segment_performance(r_trades, by="vol_regime", min_samples=MIN_SEGMENT_SAMPLES),
                title=t("Espérance par régime de volatilité", "Expectancy by volatility regime"),
                by_label=t("Régime volatilité", "Volatility regime"),
            ),
            use_container_width=True,
        )
    with tab_event:
        st.plotly_chart(
            build_segmentation_figure(
                segment_performance(r_trades, by="event_risk", min_samples=MIN_SEGMENT_SAMPLES),
                title=t("Espérance par risque événementiel", "Expectancy by event risk"),
                by_label=t("Risque événementiel", "Event risk"),
            ),
            use_container_width=True,
        )

    # --- 5. Coût des violations ---
    _section("DISCIPLINE // COÛT DES VIOLATIONS", "DISCIPLINE // COST OF RULE BREAKS")
    _render_rule_break(r_trades, config)

    # --- 6. Séries de pertes & alertes de tilt ---
    _section("TILT // SÉRIES DE PERTES & ALERTES", "TILT // LOSS STREAKS & ALERTS")
    _render_streak_tilt(filtered, config)

    # --- 7. Constats chiffrés ---
    _section("INSIGHTS // CONSTATS CHIFFRÉS", "INSIGHTS // DATA-DRIVEN FINDINGS")
    _render_insights(r_trades, config)

    # --- Rapport de coaching qualitatif (disponible, non dupliqué) ---
    st.markdown("---")
    with st.expander(t("Rapport de coaching qualitatif", "Qualitative coaching report")):
        coaching = generate_coaching_report(
            trades=filtered,
            period="global",
            period_label="global",
            config=config,
        )
        if coaching.top_leaks:
            st.markdown(f"**{t('FUITES PRINCIPALES', 'TOP LEAKS')}**")
            for leak in coaching.top_leaks:
                st.markdown(f"- {tr_text(leak)}")
        if coaching.rule_to_reinforce:
            st.warning(f"**{tr_text(coaching.rule_to_reinforce)}**")
        if coaching.strength_to_keep:
            st.success(f"**{tr_text(coaching.strength_to_keep)}**")
        if coaching.measurable_goals:
            st.markdown(f"**{t('OBJECTIFS MESURABLES', 'MEASURABLE GOALS')}**")
            for goal in coaching.measurable_goals:
                st.markdown(f"- {tr_text(goal)}")


def render_coaching_summary() -> None:
    """Compact, read-only coaching summary for the Terminal side panel.

    Reuses the existing journal loaders and coaching engine (no new
    calculation): sample sufficiency, headline metrics, top leaks and the rule
    to reinforce. An empty journal shows a friendly message, never a traceback.
    """
    try:
        config = load_config()
        db_path_str = os.getenv("NQ_DATA_DB_PATH", config.data.db_path)
        conn = get_ui_db(db_path_str)
        trades = load_trades(conn)
        min_trades = config.validation.min_sessions
        stats = compute_performance_stats(trades, min_trades=min_trades, config=config)
        report = generate_coaching_report(
            trades,
            "global",
            t("Tout l'historique", "Full history"),
            config,
        )
    except Exception as exc:  # noqa: BLE001 - a missing journal never breaks the page
        st.info(
            t(
                f"Rapport de coaching indisponible ({exc}).",
                f"Coaching report unavailable ({exc}).",
            )
        )
        return

    if not trades:
        st.info(
            t(
                "Aucun trade enregistré : le résumé de coaching apparaîtra "
                "après le premier trade documenté.",
                "No trade recorded yet: the coaching summary will appear "
                "after the first documented trade.",
            )
        )
        return

    wr = f"{stats.win_rate:.1%}" if stats.win_rate is not None else "—"
    exp = (
        f"{stats.expectancy_r:+.3f}R"
        if stats.sample_sufficient and stats.expectancy_r is not None
        else "—"
    )
    compliance = f"{stats.compliance_rate:.1%}" if stats.compliance_rate is not None else "—"
    st.markdown(
        f"""
        <div class="card">
            <div class="strip">
                <div class="strip-item">
                    <div class="strip-label">{t("Trades", "Trades")}</div>
                    <div class="strip-value">{stats.n_trades} / {min_trades}</div>
                </div>
                <div class="strip-item">
                    <div class="strip-label">Win Rate</div>
                    <div class="strip-value">{wr}</div>
                </div>
                <div class="strip-item">
                    <div class="strip-label">{t("Espérance", "Expectancy")}</div>
                    <div class="strip-value">{exp}</div>
                </div>
                <div class="strip-item">
                    <div class="strip-label">{t("Conformité", "Compliance")}</div>
                    <div class="strip-value">{compliance}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not stats.sample_sufficient:
        st.warning(
            t(
                f"Échantillon insuffisant ({stats.n_trades}/{min_trades} trades) : "
                "les métriques restent descriptives, sans conclusion statistique.",
                f"Insufficient sample ({stats.n_trades}/{min_trades} trades): "
                "metrics stay descriptive, with no statistical conclusion.",
            )
        )

    if report.top_leaks:
        st.markdown(f"**{t('Fuites principales', 'Top leaks')}**")
        for index, leak in enumerate(report.top_leaks[:3], 1):
            st.markdown(f"{index}. {tr_text(leak)}")
    if report.rule_to_reinforce:
        st.warning(f"**{tr_text(report.rule_to_reinforce)}**")
    if report.strength_to_keep:
        st.success(f"**{tr_text(report.strength_to_keep)}**")
    if report.measurable_goals:
        st.markdown(f"**{t('Objectifs mesurables', 'Measurable goals')}**")
        for goal in report.measurable_goals:
            st.markdown(f"- {tr_text(goal)}")


if __name__ == "__main__":
    render_coaching_app()
