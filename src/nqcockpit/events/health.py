"""Rendu de la santé des sources d'événements (panneau + résumé).

Fonctions pures (testables sans Streamlit) + un helper Streamlit.
Chaque source affiche : pastille de statut (OK / DÉGRADÉ / BLOQUÉ, FR+EN),
âge depuis le dernier succès, dernière erreur (courte, sans secret), nombre
d'items retournés, et un drapeau « stale » quand le cache dépasse son TTL.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nqcockpit.events.models import DataStatus, SourceHealth

UTC = timezone.utc

_STATUS_FR = {
    DataStatus.OK: "OK",
    DataStatus.DEGRADED: "DÉGRADÉ",
    DataStatus.BLOCKED: "BLOQUÉ",
}

_STATUS_PILL_CSS = {
    DataStatus.OK: ("#6EE7B7", "rgba(16,185,129,0.12)"),
    DataStatus.DEGRADED: ("#FCD34D", "rgba(245,158,11,0.12)"),
    DataStatus.BLOCKED: ("#FCA5A5", "rgba(248,113,113,0.12)"),
}


def source_health_summary(source_health: list[SourceHealth]) -> str:
    """Résumé compact « N/M sources OK » pour le chip du Terminal."""
    ok = sum(1 for s in source_health if s.status == DataStatus.OK)
    return f"{ok}/{len(source_health)}"


def source_health_chip_html(source_health: list[SourceHealth]) -> str:
    """Chip « N/M sources OK » : vert si tout est OK, ambre (DÉGRADÉ) sinon."""
    if not source_health:
        return ""
    ok = sum(1 for s in source_health if s.status == DataStatus.OK)
    css = "chip-ok" if ok == len(source_health) else "chip-degraded"
    return f'<span class="{css}"><b>{ok}/{len(source_health)} sources OK</b></span>'


def load_latest_event_source_health(
    cache_dir: str | Path = "data/events",
) -> list[SourceHealth]:
    """Reconstruit la santé des sources depuis le dernier rapport JSON du radar.

    Aucun appel réseau : lit uniquement le cache JSON exporté par le radar
    d'événements. Retourne une liste vide si aucun rapport n'existe.
    """
    d = Path(cache_dir)
    if not d.is_dir():
        return []
    files = sorted(d.glob("events_*.json"))
    if not files:
        return []
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    out: list[SourceHealth] = []
    for sh in data.get("source_health", []):
        try:
            out.append(
                SourceHealth(
                    source=sh.get("source", ""),
                    status=DataStatus(sh.get("status", "DÉGRADÉ")),
                    events_count=int(sh.get("events_count", 0)),
                    error_msg=sh.get("error_msg"),
                )
            )
        except (ValueError, TypeError):
            continue
    return out


def _status_pill(status: DataStatus, fr: bool) -> str:
    text = _STATUS_FR[status] if fr else status.value
    color, bg = _STATUS_PILL_CSS[status]
    return (
        f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
        f"color:{color};background:{bg};font-size:0.72rem;font-weight:700;'>{text}</span>"
    )


def _age_str(last_success_utc: datetime | None, now_utc: datetime | None) -> str:
    if last_success_utc is None:
        return "—"
    now = now_utc or datetime.now(UTC)
    seconds = max(0.0, (now - last_success_utc).total_seconds())
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    return f"{seconds / 3600:.1f}h"


def render_source_health_html(
    source_health: list[SourceHealth],
    fr: bool = False,
    now_utc: datetime | None = None,
) -> str:
    """Rendu HTML d'une ligne par source (statut, âge, erreur, items, stale)."""
    _td = "padding:6px 10px;border-bottom:1px solid #1F2937;"
    _muted = f"{_td}color:#94A3B8;"
    stale_tag = " <span style='color:#FCD34D;font-weight:700'>STALE</span>"

    rows = []
    for s in source_health:
        pill = _status_pill(s.status, fr)
        age = _age_str(s.last_success_utc, now_utc)
        err = (s.error_msg or "")[:120]
        stale = stale_tag if s.stale else ""
        rows.append(
            f"<tr>"
            f"<td style='{_td}'>{s.source}</td>"
            f"<td style='{_td}'>{pill}{stale}</td>"
            f"<td style='{_muted}'>{age}</td>"
            f"<td style='{_td}'>{s.events_count}</td>"
            f"<td style='{_muted}'>{err}</td>"
            f"</tr>"
        )
    header = (
        "<tr><th style='text-align:left;padding:6px 10px;color:#94A3B8;'>Source</th>"
        "<th style='text-align:left;padding:6px 10px;color:#94A3B8;'>Statut</th>"
        "<th style='text-align:left;padding:6px 10px;color:#94A3B8;'>Dernier succès</th>"
        "<th style='text-align:left;padding:6px 10px;color:#94A3B8;'>Items</th>"
        "<th style='text-align:left;padding:6px 10px;color:#94A3B8;'>Dernière erreur</th></tr>"
    )
    table_style = "width:100%;border-collapse:collapse;font-size:0.8rem;"
    return f"<table style='{table_style}'>{header}{''.join(rows)}</table>"


def render_source_health(source_health: list[SourceHealth]) -> None:
    """Rendu Streamlit du panneau de santé des sources d'événements."""
    import streamlit as st

    from nqcockpit.ui.i18n import get_lang

    fr = get_lang() == "FR"
    st.markdown(render_source_health_html(source_health, fr=fr), unsafe_allow_html=True)
