"""Graphique en bougies NQ construit depuis la base SQLite locale.

Aucun widget externe (TradingView a été retiré pour raison de licence) et
aucune donnée inventée : si la table ``bars`` ne contient pas de NQ=F, le
constructeur renvoie un message d'état vide explicite au lieu d'une figure
vide. Les niveaux gamma (gamma flip / call wall / put support) sont dessinés
en lignes horizontales uniquement quand le snapshot les fournit.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

from nqcockpit.data.db import get_bars
from nqcockpit.data.models import Bar
from nqcockpit.ui.i18n import label

TZ_ET = ZoneInfo("America/New_York")
UTC = timezone.utc

CHART_SYMBOL = "NQ=F"
CHART_INTERVAL = "1m"
_MAX_LOOKBACK_BARS = 1500


@dataclass(frozen=True)
class SessionChart:
    """Résultat affichable : figure prête, ou message d'état vide honnête."""

    figure: go.Figure | None
    message: str
    last_bar_utc: datetime | None = None

    @property
    def has_data(self) -> bool:
        return self.figure is not None


def _ensure_aware(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def format_bar_timestamp(ts: datetime | None) -> str:
    """Horodatage de barre lisible en heure de marché (ET)."""
    if ts is None:
        return ""
    return _ensure_aware(ts).astimezone(TZ_ET).strftime("%Y-%m-%d %H:%M ET")


def load_latest_session_bars(
    conn: sqlite3.Connection,
    symbol: str = CHART_SYMBOL,
    interval: str = CHART_INTERVAL,
    lookback_bars: int = _MAX_LOOKBACK_BARS,
) -> tuple[list[Bar], datetime | None]:
    """Barres de la dernière séance ET disponible + horodatage de la dernière barre.

    La séance retenue est celle de la date America/New_York du dernier bar stocké.
    Retourne ``([], None)`` si la table est vide : aucun chiffre n'est fabriqué.
    """
    recent = get_bars(conn, symbol, interval, limit=lookback_bars)
    if not recent:
        return [], None

    last_ts = _ensure_aware(recent[-1].timestamp_utc)
    session_date = last_ts.astimezone(TZ_ET).date()
    session_bars = [
        bar
        for bar in recent
        if _ensure_aware(bar.timestamp_utc).astimezone(TZ_ET).date() == session_date
    ]
    return session_bars, last_ts


def empty_chart_message(last_bar_utc: datetime | None = None) -> str:
    """Message d'état vide, avec l'horodatage de la dernière barre s'il existe."""
    if last_bar_utc is None:
        return label("chart.empty_no_bars")
    return label("chart.empty_with_last", last_bar=format_bar_timestamp(last_bar_utc))


def build_session_chart(
    bars: Sequence[Bar],
    *,
    gamma_flip: float | None = None,
    call_wall: float | None = None,
    put_support: float | None = None,
    last_bar_utc: datetime | None = None,
    symbol: str = CHART_SYMBOL,
) -> SessionChart:
    """Construit la figure en bougies + lignes de niveaux, ou l'état vide.

    Returns:
        ``SessionChart(figure=..., message="")`` si des barres existent,
        sinon ``SessionChart(figure=None, message="No chart data — ...")``.
    """
    bars = list(bars)
    if not bars:
        hint = last_bar_utc or None
        return SessionChart(
            figure=None,
            message=empty_chart_message(hint),
            last_bar_utc=hint,
        )

    resolved_last = last_bar_utc or _ensure_aware(bars[-1].timestamp_utc)
    times = [
        _ensure_aware(bar.timestamp_utc).astimezone(TZ_ET).replace(tzinfo=None)
        for bar in bars
    ]

    figure = go.Figure(
        data=[
            go.Candlestick(
                x=times,
                open=[bar.open for bar in bars],
                high=[bar.high for bar in bars],
                low=[bar.low for bar in bars],
                close=[bar.close for bar in bars],
                name=symbol,
                increasing_line_color="#10B981",
                increasing_fillcolor="rgba(16, 185, 129, 0.45)",
                decreasing_line_color="#EF4444",
                decreasing_fillcolor="rgba(239, 68, 68, 0.45)",
            )
        ]
    )

    levels = (
        (gamma_flip, "chart.gamma_flip", "#A78BFA"),
        (call_wall, "chart.call_wall", "#F59E0B"),
        (put_support, "chart.put_support", "#38BDF8"),
    )
    for value, key, color in levels:
        if value is None:
            continue
        figure.add_hline(
            y=float(value),
            line_dash="dash",
            line_width=1,
            line_color=color,
            annotation_text=f"{label(key)} {float(value):,.1f}",
            annotation_position="top right",
            annotation_font_size=10,
            annotation_font_color=color,
        )

    figure.update_layout(
        template="plotly_dark",
        title=dict(text=label("chart.title"), font=dict(size=13)),
        height=520,
        margin=dict(l=10, r=10, t=36, b=10),
        paper_bgcolor="#0B1220",
        plot_bgcolor="#0B1220",
        showlegend=False,
        xaxis=dict(
            title=label("chart.xaxis"),
            rangeslider=dict(visible=False),
            showgrid=False,
            type="date",
        ),
        yaxis=dict(
            title=label("chart.yaxis"),
            gridcolor="rgba(148, 163, 184, 0.12)",
            zeroline=False,
        ),
    )

    return SessionChart(figure=figure, message="", last_bar_utc=resolved_last)
