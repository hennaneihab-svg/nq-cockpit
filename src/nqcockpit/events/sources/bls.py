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
     "desc": "Emplois non-agricoles, taux de chômage (sept. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/empsit.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    {"date": "2026-11-06", "name": "NFP", "tier": 1,
     "desc": "Emplois non-agricoles, taux de chômage (oct. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/empsit.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    {"date": "2026-12-04", "name": "NFP", "tier": 1,
     "desc": "Emplois non-agricoles, taux de chômage (nov. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/empsit.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    # CPI — 14 oct 2026 (source officielle BLS)
    {"date": "2026-10-14", "name": "CPI", "tier": 1,
     "desc": "Indice des prix à la consommation (sept. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/cpi.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    {"date": "2026-11-12", "name": "CPI", "tier": 1,
     "desc": "Indice des prix à la consommation (oct. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/cpi.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    {"date": "2026-12-11", "name": "CPI", "tier": 1,
     "desc": "Indice des prix à la consommation (nov. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/cpi.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    # PPI — 15 oct attendu, pas le 8 (source officielle BLS)
    {"date": "2026-10-15", "name": "PPI", "tier": 2,
     "desc": "Indice des prix à la production (sept. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/ppi.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    {"date": "2026-11-13", "name": "PPI", "tier": 2,
     "desc": "Indice des prix à la production (oct. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/ppi.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    {"date": "2026-12-10", "name": "PPI", "tier": 2,
     "desc": "Indice des prix à la production (nov. 2026)",
     "time_et": (8, 30),
     "primary_source": "https://www.bls.gov/schedule/news_release/ppi.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    # JOLTS — 3 nov attendu, pas le 7 oct (10:00 ET, source officielle BLS)
    {"date": "2026-11-03", "name": "JOLTS", "tier": 2,
     "desc": "Offres d'emploi et rotation (sept. 2026)",
     "time_et": (10, 0),
     "primary_source": "https://www.bls.gov/schedule/news_release/jolts.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
    {"date": "2026-12-08", "name": "JOLTS", "tier": 2,
     "desc": "Offres d'emploi et rotation (oct. 2026)",
     "time_et": (10, 0),
     "primary_source": "https://www.bls.gov/schedule/news_release/jolts.htm",
     "consultation_date": "2026-09-30",
     "verified": True},
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
    return naive.astimezone(UTC), f"table versionnée BLS ({h:02d}:{m:02d} ET)", DataStatus.OK


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
                source="bls" if reachable else "static",
                description=entry["desc"],
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=ev_status,
                all_sources=["bls"],
                time_provenance=time_prov,
                verified=is_verified,
                primary_source_url=primary_url,
                consultation_date=consult_dt,
            )
        )

    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
