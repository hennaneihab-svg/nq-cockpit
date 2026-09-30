"""Source Fed : RSS press_all.xml + parsing HTML calendrier FOMC.

Retourne les événements FOMC (réunions, minutes, discours) horodatés en UTC.
Statut DÉGRADÉ si source inaccessible ; jamais de crash silencieux.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nqcockpit.events.models import CalendarEvent, DataStatus

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc

# Membres FOMC connus (insensible à la casse pour la recherche)
_FOMC_MEMBERS = [
    "powell", "waller", "jefferson", "cook", "barr", "kugler",
    "logan", "daly", "goolsbee", "hammack", "kashkari",
    "musalem", "schmid", "williams", "bostic", "collins",
    "harker", "mester", "bullard",
]

# Réunions FOMC 2026 connues (source : federalreserve.gov/monetarypolicy/fomccalendars.htm)
# Vérifiées le 2026-09-29. Heure de décision : 14h00 ET (jour J de la décision).
# Minutes publiées ~3 semaines après. Conférence de presse : réunions avec *.
_FOMC_MEETINGS_2026: list[dict] = [
    {"date": "2026-01-28", "type": "FOMC", "has_presser": False},
    {"date": "2026-03-18", "type": "FOMC", "has_presser": True},
    {"date": "2026-04-29", "type": "FOMC", "has_presser": False},
    {"date": "2026-06-17", "type": "FOMC", "has_presser": True},
    {"date": "2026-07-29", "type": "FOMC", "has_presser": False},
    {"date": "2026-09-16", "type": "FOMC", "has_presser": True},
    {"date": "2026-10-28", "type": "FOMC", "has_presser": False},
    {"date": "2026-12-09", "type": "FOMC", "has_presser": True},
]

# Minutes publiées ~3 semaines après chaque réunion (lag confirmé sur historique)
# Lag réel observé : Jan→Feb 18, Mar→Apr 08, Apr→May 20, Jun→Jul 08, Jul→Aug 19, Sep→?
_FOMC_MINUTES_2026: list[dict] = [
    {"date": "2026-02-18", "meeting_date": "2026-01-28"},
    {"date": "2026-04-08", "meeting_date": "2026-03-18"},
    {"date": "2026-05-20", "meeting_date": "2026-04-29"},
    {"date": "2026-07-08", "meeting_date": "2026-06-17"},
    {"date": "2026-08-19", "meeting_date": "2026-07-29"},
    # Minutes de la réunion Sep 15-16 : publiées 7 oct. (3 semaines après, mercredi 14h00 ET)
    {"date": "2026-10-07", "meeting_date": "2026-09-16"},
    # Minutes d'octobre : publiées ~19 nov. (extrapolé)
    {"date": "2026-11-18", "meeting_date": "2026-10-28"},
]


def _make_utc(date_str: str, hour_et: int = 14, minute_et: int = 0) -> datetime:
    """Crée un datetime UTC depuis une date 'YYYY-MM-DD' et une heure ET."""
    naive = datetime(
        int(date_str[:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        hour_et,
        minute_et,
        tzinfo=ET_TZ,
    )
    return naive.astimezone(UTC)


def _fetch_rss(url: str, timeout: int = 10) -> list[dict]:
    """Fetch et parse le flux RSS Fed. Retourne une liste de dicts {title, pubdate, link}."""
    items: list[dict] = []
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            pubdate = item.findtext("pubDate") or ""
            link = item.findtext("link") or ""
            items.append({"title": title, "pubdate": pubdate, "link": link})
    except (urllib.error.URLError, ET.ParseError, OSError) as exc:
        log.warning("Fed RSS inaccessible: %s", exc)
    return items


def _parse_rss_date(pubdate: str) -> datetime | None:
    """Parse une date RFC-2822 du RSS Fed vers UTC."""
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(pubdate.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    return None


def _is_fomc_speech(title: str) -> bool:
    """Détecte un discours FOMC dans le titre RSS."""
    t = title.lower()
    return any(m in t for m in _FOMC_MEMBERS) or "speech" in t or "remarks" in t


def fetch_fed_events(
    rss_url: str,
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    timeout: int = 10,
) -> tuple[list[CalendarEvent], DataStatus, str]:
    """Fetch les événements Fed (FOMC, minutes, discours) sur l'horizon donné.

    Returns:
        (events, status, error_msg)
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    events: list[CalendarEvent] = []
    status = DataStatus.OK
    error_msg = ""
    fetched_utc = datetime.now(UTC)

    from datetime import timedelta
    horizon_end_dt = now_utc + timedelta(days=horizon_days)

    today_et = now_utc.astimezone(ET_TZ).date()

    # 1. Calendrier FOMC statique 2026 (source : federalreserve.gov, vérifiée)
    for mtg in _FOMC_MEETINGS_2026:
        try:
            scheduled = _make_utc(mtg["date"], hour_et=14, minute_et=0)
        except ValueError:
            continue
        if scheduled.astimezone(ET_TZ).date() < today_et or scheduled > horizon_end_dt:
            continue
        desc = "Décision de politique monétaire FOMC"
        if mtg.get("has_presser"):
            desc += " + conférence de presse Powell (14h30 ET)"
        events.append(
            CalendarEvent(
                name="FOMC",
                tier=1,
                scheduled_utc=scheduled,
                source="fed_html",
                description=desc,
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=DataStatus.OK,
                all_sources=["fed_html"],
            )
        )

    for min_rec in _FOMC_MINUTES_2026:
        try:
            scheduled = _make_utc(min_rec["date"], hour_et=14, minute_et=0)
        except ValueError:
            continue
        if scheduled.astimezone(ET_TZ).date() < today_et or scheduled > horizon_end_dt:
            continue
        events.append(
            CalendarEvent(
                name="FOMC Minutes",
                tier=1,
                scheduled_utc=scheduled,
                source="fed_html",
                description=(
                    f"Minutes de la réunion FOMC du {min_rec['meeting_date']} "
                    "(14h00 ET — source : calendrier officiel Fed)"
                ),
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=DataStatus.OK,
                all_sources=["fed_html"],
            )
        )

    # 2. RSS Fed pour discours et événements récents non couverts par le statique
    rss_items = _fetch_rss(rss_url, timeout=timeout)
    if not rss_items:
        status = DataStatus.DEGRADED
        error_msg = "RSS Fed inaccessible — calendrier statique utilisé"
        log.warning("Fed RSS: aucune donnée (DÉGRADÉ)")
    else:
        age_s = (datetime.now(UTC) - fetched_utc).total_seconds()
        for item in rss_items:
            title = item["title"]
            pubdate_raw = item["pubdate"]
            pub_dt = _parse_rss_date(pubdate_raw)
            if pub_dt is None:
                continue
            # Ignorer les événements passés
            if pub_dt < now_utc:
                continue
            if pub_dt > horizon_end_dt:
                continue
            tl = title.lower()
            if "fomc statement" in tl or "fomc" in tl:
                name = "FOMC"
                tier = 1
            elif "minutes" in tl and "fomc" in tl:
                name = "FOMC Minutes"
                tier = 1
            elif _is_fomc_speech(title):
                name = "Powell" if "powell" in tl else "Fed Speech"
                tier = 1 if "powell" in tl else 2
            else:
                continue

            # Dédoublonner avec le statique (même nom même jour ±1h)
            duplicate = any(
                e.name == name
                and abs((e.scheduled_utc - pub_dt).total_seconds()) < 3600
                for e in events
            )
            if not duplicate:
                events.append(
                    CalendarEvent(
                        name=name,
                        tier=tier,
                        scheduled_utc=pub_dt,
                        source="fed_rss",
                        description=title[:200],
                        source_fetched_utc=fetched_utc,
                        source_age_seconds=age_s,
                        status=DataStatus.OK,
                        all_sources=["fed_rss"],
                    )
                )

    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
