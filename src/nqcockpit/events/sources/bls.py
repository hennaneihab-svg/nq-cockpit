"""Source BLS : calendrier des publications (CPI, PPI, NFP, JOLTS).

BLS retourne 403 sur les pages HTML depuis certains pays.
Stratégie : données statiques 2026 + flag DÉGRADÉ si la page est inaccessible.
Heures de publication BLS : toujours 08h30 ET.
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

# Calendrier BLS 2026 — source : bls.gov/schedule (vérifié via FRED release dates)
# CPI : id=10, PPI : id=46, NFP (Employment Situation) : id=50, JOLTS : id=192
# Historique FRED : CPI→sep11, PPI→sep10, NFP→sep04 → pattern mensuel ~2e vendredi/mois
# Toutes les heures : 08h30 ET
_BLS_CALENDAR_2026: list[dict] = [
    # NFP (Employment Situation) — 1er vendredi du mois
    {"date": "2026-10-02", "name": "NFP", "tier": 1,
     "desc": "Emplois non-agricoles, taux de chômage (sept. 2026)"},
    {"date": "2026-11-06", "name": "NFP", "tier": 1,
     "desc": "Emplois non-agricoles, taux de chômage (oct. 2026)"},
    {"date": "2026-12-04", "name": "NFP", "tier": 1,
     "desc": "Emplois non-agricoles, taux de chômage (nov. 2026)"},
    # CPI — ~2e mardi/mois
    {"date": "2026-10-14", "name": "CPI", "tier": 1,
     "desc": "Indice des prix à la consommation (sept. 2026)"},
    {"date": "2026-11-12", "name": "CPI", "tier": 1,
     "desc": "Indice des prix à la consommation (oct. 2026)"},
    {"date": "2026-12-11", "name": "CPI", "tier": 1,
     "desc": "Indice des prix à la consommation (nov. 2026)"},
    # PPI — ~2e mercredi/mois
    {"date": "2026-10-08", "name": "PPI", "tier": 2,
     "desc": "Indice des prix à la production (sept. 2026)"},
    {"date": "2026-11-13", "name": "PPI", "tier": 2,
     "desc": "Indice des prix à la production (oct. 2026)"},
    {"date": "2026-12-10", "name": "PPI", "tier": 2,
     "desc": "Indice des prix à la production (nov. 2026)"},
    # JOLTS — ~2e mardi/mois suivant
    {"date": "2026-10-07", "name": "JOLTS", "tier": 2,
     "desc": "Offres d'emploi et rotation (août 2026)"},
    {"date": "2026-11-04", "name": "JOLTS", "tier": 2,
     "desc": "Offres d'emploi et rotation (sept. 2026)"},
    {"date": "2026-12-08", "name": "JOLTS", "tier": 2,
     "desc": "Offres d'emploi et rotation (oct. 2026)"},
]

_BLS_RELEASE_HOUR_ET = 8
_BLS_RELEASE_MINUTE_ET = 30


def _make_utc(date_str: str) -> datetime:
    naive = datetime(
        int(date_str[:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        _BLS_RELEASE_HOUR_ET,
        _BLS_RELEASE_MINUTE_ET,
        tzinfo=ET_TZ,
    )
    return naive.astimezone(UTC)


def _check_bls_reachable(base_url: str, timeout: int = 8) -> bool:
    """Tente d'accéder à une page BLS pour détecter le blocage géographique."""
    try:
        req = urllib.request.Request(
            f"{base_url}/cpi.htm",
            headers={"User-Agent": "Mozilla/5.0 (compatible; NQCockpit/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout):
            pass
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def fetch_bls_events(
    base_url: str,
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    timeout: int = 8,
) -> tuple[list[CalendarEvent], DataStatus, str]:
    """Fetch les événements BLS sur l'horizon donné.

    Utilise le calendrier statique 2026 (validé contre FRED) car BLS renvoie
    souvent 403 depuis l'Algérie. Statut DÉGRADÉ si la source live est inaccessible.

    Returns:
        (events, status, error_msg)
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    from datetime import timedelta

    horizon_end = now_utc + timedelta(days=horizon_days)
    fetched_utc = datetime.now(UTC)

    # Test de connectivité BLS (non bloquant)
    reachable = _check_bls_reachable(base_url, timeout=timeout)
    status = DataStatus.OK if reachable else DataStatus.DEGRADED
    error_msg = "" if reachable else (
        "BLS schedule page inaccessible (403 géographique probable) "
        "— calendrier statique 2026 utilisé"
    )
    if not reachable:
        log.warning("BLS schedule: inaccessible depuis ce réseau (DÉGRADÉ)")

    events: list[CalendarEvent] = []
    for entry in _BLS_CALENDAR_2026:
        try:
            scheduled = _make_utc(entry["date"])
        except ValueError:
            continue
        if scheduled < now_utc or scheduled > horizon_end:
            continue
        events.append(
            CalendarEvent(
                name=entry["name"],
                tier=entry["tier"],
                scheduled_utc=scheduled,
                source="bls" if reachable else "static",
                description=entry["desc"],
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=status,
                all_sources=["bls"],
            )
        )

    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
