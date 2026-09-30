"""Source ISM : calendrier des publications ISM Manufacturing et ISM Services.

ISM publie l'ISM Manufacturing (1er jour ouvré du mois) et l'ISM Services
(3e jour ouvré du mois) à 10h00 ET.
Source officielle : https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nqcockpit.events.models import CalendarEvent, DataStatus

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc

_ISM_SCHEDULE_URL = (
    "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/"
)

# Calendrier ISM 2026 — source officielle ismworld.org (consultation : 2026-09-30)
# Manufacturing : 1er jour ouvré du mois, 10:00 ET
# Services : 3e jour ouvré du mois, 10:00 ET (5 oct 2026, 4 nov 2026, 3 déc 2026)
_ISM_CALENDAR_2026: list[dict] = [
    {
        "date": "2026-10-01",
        "name": "ISM Manufacturing",
        "tier": 2,
        "desc": "ISM Manufacturing PMI (sept. 2026) — 10h00 ET",
        "time_et": (10, 0),
        "primary_source": _ISM_SCHEDULE_URL,
        "consultation_date": "2026-09-30",
        "verified": True,
    },
    {
        "date": "2026-10-05",
        "name": "ISM Services",
        "tier": 2,
        "desc": "ISM Services PMI (sept. 2026) — 10h00 ET",
        "time_et": (10, 0),
        "primary_source": _ISM_SCHEDULE_URL,
        "consultation_date": "2026-09-30",
        "verified": True,
    },
    {
        "date": "2026-11-02",
        "name": "ISM Manufacturing",
        "tier": 2,
        "desc": "ISM Manufacturing PMI (oct. 2026) — 10h00 ET",
        "time_et": (10, 0),
        "primary_source": _ISM_SCHEDULE_URL,
        "consultation_date": "2026-09-30",
        "verified": True,
    },
    {
        "date": "2026-11-04",
        "name": "ISM Services",
        "tier": 2,
        "desc": "ISM Services PMI (oct. 2026) — 10h00 ET",
        "time_et": (10, 0),
        "primary_source": _ISM_SCHEDULE_URL,
        "consultation_date": "2026-09-30",
        "verified": True,
    },
    {
        "date": "2026-12-01",
        "name": "ISM Manufacturing",
        "tier": 2,
        "desc": "ISM Manufacturing PMI (nov. 2026) — 10h00 ET",
        "time_et": (10, 0),
        "primary_source": _ISM_SCHEDULE_URL,
        "consultation_date": "2026-09-30",
        "verified": True,
    },
    {
        "date": "2026-12-03",
        "name": "ISM Services",
        "tier": 2,
        "desc": "ISM Services PMI (nov. 2026) — 10h00 ET",
        "time_et": (10, 0),
        "primary_source": _ISM_SCHEDULE_URL,
        "consultation_date": "2026-09-30",
        "verified": True,
    },
]


def _make_utc(
    date_str: str, time_et: tuple[int, int] | None
) -> tuple[datetime, str, DataStatus]:
    if time_et is None:
        naive = datetime(
            int(date_str[:4]),
            int(date_str[5:7]),
            int(date_str[8:10]),
            0,
            0,
            tzinfo=ET_TZ,
        )
        return naive.astimezone(UTC), "non fournie [DÉGRADÉ]", DataStatus.DEGRADED

    h, m = time_et
    naive = datetime(
        int(date_str[:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        h,
        m,
        tzinfo=ET_TZ,
    )
    return naive.astimezone(UTC), f"table versionnée ISM ({h:02d}:{m:02d} ET)", DataStatus.OK


def _check_ism_reachable(schedule_url: str, timeout: int = 8) -> bool:
    """Tente d'accéder au site officiel ISM."""
    try:
        req = urllib.request.Request(
            schedule_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NQCockpit/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout):
            pass
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def fetch_ism_events(
    schedule_url: str = _ISM_SCHEDULE_URL,
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    timeout: int = 8,
) -> tuple[list[CalendarEvent], DataStatus, str]:
    """Fetch les événements ISM sur l'horizon donné.

    Si la page ISM est inaccessible (réseau/blocage), utilise le calendrier
    statique versionné 2026 avec statut DÉGRADÉ visible.

    Returns:
        (events, status, error_msg)
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    from datetime import timedelta

    horizon_end = now_utc + timedelta(days=horizon_days)
    fetched_utc = datetime.now(UTC)

    reachable = _check_ism_reachable(schedule_url, timeout=timeout)
    status = DataStatus.OK if reachable else DataStatus.DEGRADED
    error_msg = "" if reachable else (
        "Site ISM inaccessible — calendrier statique 2026 utilisé (DÉGRADÉ)"
    )
    if not reachable:
        log.warning("ISM schedule: inaccessible depuis ce réseau (DÉGRADÉ)")

    events: list[CalendarEvent] = []
    for entry in _ISM_CALENDAR_2026:
        time_et = entry.get("time_et")
        try:
            scheduled, time_prov, time_status = _make_utc(entry["date"], time_et)
        except ValueError:
            continue
        today_et = now_utc.astimezone(ET_TZ).date()
        if scheduled.astimezone(ET_TZ).date() < today_et or scheduled > horizon_end:
            continue
        is_verified = bool(entry.get("verified", False) and entry.get("primary_source"))
        primary_url = entry.get("primary_source", "")
        consult_dt = entry.get("consultation_date", "")
        ev_status = (
            DataStatus.DEGRADED
            if (
                status == DataStatus.DEGRADED
                or time_status == DataStatus.DEGRADED
                or not is_verified
            )
            else DataStatus.OK
        )
        events.append(
            CalendarEvent(
                name=entry["name"],
                tier=entry["tier"],
                scheduled_utc=scheduled,
                source="ism" if reachable else "static",
                description=entry["desc"],
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=ev_status,
                all_sources=["ism"],
                time_provenance=time_prov,
                verified=is_verified,
                primary_source_url=primary_url,
                consultation_date=consult_dt,
            )
        )

    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
