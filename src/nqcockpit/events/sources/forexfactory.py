"""Source ForexFactory : calendrier JSON non officiel.

Endpoint : https://nfs.faireconomy.media/ff_calendar_thisweek.json
          + ff_calendar_nextweek.json (peut retourner 404 en dehors de la semaine)

Rôle : contrôle croisé + consensus/précédent/valeur actuelle.
Statut DÉGRADÉ si endpoint inaccessible (non bloquant).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nqcockpit.events.models import CalendarEvent, DataStatus

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc

# Mapping des noms ForexFactory → noms normalisés NQ Cockpit
_NAME_MAP = {
    "non-farm employment change": "NFP",
    "nonfarm payrolls": "NFP",
    "average hourly earnings m/m": "NFP",
    "unemployment rate": "NFP",
    "cpi m/m": "CPI",
    "cpi y/y": "CPI",
    "core cpi m/m": "CPI",
    "consumer price index": "CPI",
    "ppi m/m": "PPI",
    "core ppi m/m": "PPI",
    "producer price index": "PPI",
    "gdp q/q": "GDP",
    "final gdp q/q": "GDP",
    "advance gdp q/q": "GDP",
    "pce price index m/m": "PCE",
    "core pce price index m/m": "PCE",
    "jolts job openings": "JOLTS",
    "fomc statement": "FOMC",
    "fomc meeting minutes": "FOMC Minutes",
    "fomc minutes": "FOMC Minutes",
    "fed chair powell speaks": "Powell",
    "powell speaks": "Powell",
}

_TIER_MAP = {
    "NFP": 1, "CPI": 1, "FOMC": 1, "FOMC Minutes": 1,
    "Powell": 1, "GDP": 1, "PCE": 1,
    "PPI": 2, "JOLTS": 2,
}


def _normalize_name(raw_title: str) -> str | None:
    """Normalise un titre ForexFactory vers un nom NQ Cockpit."""
    tl = raw_title.strip().lower()
    for pattern, normalized in _NAME_MAP.items():
        if pattern in tl:
            return normalized
    return None


def _parse_ff_date(date_str: str) -> datetime | None:
    """Parse les dates ForexFactory (ISO 8601 avec offset ET)."""
    if not date_str:
        return None
    # Format typique : "2026-10-02T08:30:00-04:00"
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str[:25], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ET_TZ)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    # Fallback : date seule
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return d.replace(hour=12, minute=0, tzinfo=ET_TZ).astimezone(UTC)
    except ValueError:
        return None


def _fetch_ff_json(url: str, timeout: int = 10) -> list[dict]:
    """Fetch le JSON ForexFactory."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NQCockpit/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as exc:
        log.warning("ForexFactory fetch %s: %s", url, exc)
        return []


def fetch_forexfactory_events(
    thisweek_url: str,
    nextweek_url: str,
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    timeout: int = 10,
) -> tuple[list[CalendarEvent], DataStatus, str]:
    """Fetch les événements USD à fort impact depuis ForexFactory.

    Retourne les événements normalisés + consensus/précédent pour croisement.
    Statut DÉGRADÉ si les deux endpoints sont inaccessibles.

    Returns:
        (events, status, error_msg)
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    from datetime import timedelta

    horizon_end = now_utc + timedelta(days=horizon_days)
    fetched_utc = datetime.now(UTC)

    raw_this = _fetch_ff_json(thisweek_url, timeout)
    raw_next = _fetch_ff_json(nextweek_url, timeout)

    all_raw = raw_this + raw_next
    reachable = bool(raw_this or raw_next)

    if not reachable:
        return (
            [],
            DataStatus.DEGRADED,
            "ForexFactory inaccessible (les deux endpoints ont échoué)",
        )

    status = DataStatus.OK
    error_msg = ""
    if not raw_next:
        status = DataStatus.DEGRADED
        error_msg = "semaine en cours OK, nextweek indisponible (404)"

    events: list[CalendarEvent] = []
    seen_keys: set[tuple[str, str]] = set()  # (name, date_day) pour dédoublonner

    for entry in all_raw:
        country = entry.get("country", "").upper()
        if country != "USD":
            continue

        impact = entry.get("impact", "").lower()
        if impact not in ("high", "medium"):
            continue

        raw_title = entry.get("title", "")
        name = _normalize_name(raw_title)
        if name is None:
            # Garder quand même les High USD non normalisés avec leur titre brut
            if impact == "high":
                name = raw_title[:40]
            else:
                continue

        date_str = entry.get("date", "")
        scheduled = _parse_ff_date(date_str)
        if scheduled is None:
            continue

        if scheduled < now_utc or scheduled > horizon_end:
            continue

        # Dédoublonner par (name, jour)
        day_key = scheduled.strftime("%Y-%m-%d")
        key = (name, day_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        tier = _TIER_MAP.get(name, 2 if impact == "medium" else 1)

        events.append(
            CalendarEvent(
                name=name,
                tier=tier,
                scheduled_utc=scheduled,
                source="forexfactory",
                description=f"[ForexFactory] {raw_title}",
                consensus=entry.get("forecast") or None,
                previous=entry.get("previous") or None,
                actual=entry.get("actual") or None,
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=DataStatus.OK,
                all_sources=["forexfactory"],
            )
        )

    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
