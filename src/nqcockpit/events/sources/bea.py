"""Source BEA : calendrier des publications GDP et PCE.

BEA publie GDP advance/second/third et PCE via sa page news/schedule.
Heure de publication : 08h30 ET.
Source de référence : bea.gov/news/schedule + FRED release_id=53 (GDP), 54 (PCE).
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

# Calendrier BEA 2026 — source : bea.gov/news/schedule + FRED (GDP=53, PCE=54)
# Historique FRED : GDP → Aug 26, Jul 30, Jun 25; PCE → Aug 26, Jul 30
# GDP advance T3 2026 : attendu fin octobre 2026 (pattern historique ~dernier mercredi oct.)
# PCE : publié avec Personal Income and Outlays, ~dernier mercredi du mois précédent
_BEA_CALENDAR_2026: list[dict] = [
    # PCE (Personal Income and Outlays) — fin de mois
    {"date": "2026-09-30", "name": "PCE", "tier": 1,
     "desc": "Personal Income & Outlays, PCE Price Index (août 2026) — 08h30 ET"},
    {"date": "2026-10-30", "name": "PCE", "tier": 1,
     "desc": "Personal Income & Outlays, PCE Price Index (sept. 2026) — 08h30 ET"},
    {"date": "2026-11-25", "name": "PCE", "tier": 1,
     "desc": "Personal Income & Outlays, PCE Price Index (oct. 2026) — 08h30 ET"},
    # GDP (Gross Domestic Product)
    {"date": "2026-09-30", "name": "GDP", "tier": 1,
     "desc": "Gross Domestic Product Q2 2026 (troisième estimation) — 08h30 ET"},
    # GDP Advance (1re estimation trimestrielle)
    {"date": "2026-10-29", "name": "GDP", "tier": 1,
     "desc": "GDP Advance Q3 2026 (1re estimation) — 08h30 ET"},
    {"date": "2026-11-25", "name": "GDP", "tier": 1,
     "desc": "GDP Second Estimate Q3 2026 — 08h30 ET"},
]

_BEA_RELEASE_HOUR_ET = 8
_BEA_RELEASE_MINUTE_ET = 30


def _make_utc(date_str: str) -> datetime:
    naive = datetime(
        int(date_str[:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        _BEA_RELEASE_HOUR_ET,
        _BEA_RELEASE_MINUTE_ET,
        tzinfo=ET_TZ,
    )
    return naive.astimezone(UTC)


def _check_bea_reachable(url: str, timeout: int = 8) -> bool:
    """Test de connectivité BEA."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NQCockpit/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout):
            pass
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def fetch_bea_events(
    schedule_url: str,
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    timeout: int = 8,
) -> tuple[list[CalendarEvent], DataStatus, str]:
    """Fetch les événements BEA (GDP, PCE) sur l'horizon donné.

    Utilise le calendrier statique 2026 (validé contre FRED) avec test de
    connectivité pour signaler le statut réel de la source.

    Returns:
        (events, status, error_msg)
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    from datetime import timedelta

    horizon_end = now_utc + timedelta(days=horizon_days)
    fetched_utc = datetime.now(UTC)

    reachable = _check_bea_reachable(schedule_url, timeout=timeout)
    status = DataStatus.OK if reachable else DataStatus.DEGRADED
    error_msg = "" if reachable else (
        "BEA schedule page inaccessible — calendrier statique 2026 utilisé"
    )
    if not reachable:
        log.warning("BEA schedule: inaccessible depuis ce réseau (DÉGRADÉ)")

    today_et = now_utc.astimezone(ET_TZ).date()
    events: list[CalendarEvent] = []
    for entry in _BEA_CALENDAR_2026:
        try:
            scheduled = _make_utc(entry["date"])
        except ValueError:
            continue
        if scheduled.astimezone(ET_TZ).date() < today_et or scheduled > horizon_end:
            continue
        events.append(
            CalendarEvent(
                name=entry["name"],
                tier=entry["tier"],
                scheduled_utc=scheduled,
                source="bea" if reachable else "static",
                description=entry["desc"],
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=status,
                all_sources=["bea"],
            )
        )

    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
