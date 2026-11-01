"""Source ForexFactory : calendrier JSON non officiel.

Endpoint : https://nfs.faireconomy.media/ff_calendar_thisweek.json
          + ff_calendar_nextweek.json (peut retourner 404 en dehors de la semaine)

Rôle : contrôle croisé + consensus/précédent/valeur actuelle.
Statut DÉGRADÉ si endpoint inaccessible (non bloquant).
"""

from __future__ import annotations

import json
import logging
import pathlib
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
    "adp non-farm employment": "ADP",
    "adp": "ADP",
    "non-farm employment change": "NFP",
    "nonfarm payrolls": "NFP",
    "average hourly earnings m/m": "Average Hourly Earnings",
    "average hourly earnings y/y": "Average Hourly Earnings",
    "average hourly earnings": "Average Hourly Earnings",
    "unemployment rate": "Unemployment Rate",
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
    "ism manufacturing": "ISM",
    "ism services": "ISM",
    "ism": "ISM",
    "unemployment claims": "Jobless Claims",
    "fomc statement": "FOMC",
    "fomc meeting minutes": "FOMC Minutes",
    "fomc minutes": "FOMC Minutes",
    "fed chair powell speaks": "Powell",
    "powell speaks": "Powell",
}

_TIER_MAP = {
    "NFP": 1, "CPI": 1, "FOMC": 1, "FOMC Minutes": 1,
    "Powell": 1, "GDP": 1, "PCE": 1,
    "PPI": 2, "JOLTS": 2, "ISM": 2, "ADP": 2, "Jobless Claims": 2,
    "Average Hourly Earnings": 2, "Unemployment Rate": 2,
}


def _normalize_name(raw_title: str) -> str | None:
    """Normalise un titre ForexFactory vers un nom NQ Cockpit."""
    tl = raw_title.strip().lower()
    for pattern, normalized in _NAME_MAP.items():
        if pattern in tl:
            return normalized
    return None


def _parse_ff_date(date_str: str) -> tuple[datetime | None, str, DataStatus]:
    """Parse les dates ForexFactory (ISO 8601 avec offset ET)."""
    if not date_str:
        return None, "", DataStatus.DEGRADED
    # Format typique : "2026-10-02T08:30:00-04:00"
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str[:25], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ET_TZ)
            et_dt = dt.astimezone(ET_TZ)
            return dt.astimezone(UTC), f"ForexFactory ({et_dt.strftime('%H:%M')} ET)", DataStatus.OK
        except ValueError:
            continue
    # Date seule : aucune heure fournie -> statut DÉGRADÉ
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        naive = datetime(d.year, d.month, d.day, 0, 0, tzinfo=ET_TZ)
        return naive.astimezone(UTC), "non fournie [DÉGRADÉ]", DataStatus.DEGRADED
    except ValueError:
        return None, "", DataStatus.DEGRADED


def _fetch_ff_json(url: str, timeout: int = 5) -> tuple[list[dict] | None, str | None]:
    """Fetch le JSON ForexFactory. Retourne ``(data, error)``.

    Distingue HTTP 404 (pas encore publié) / 429 (rate-limit) / timeout pour
    permettre le repli sur le cache sans jamais masquer l'erreur.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NQCockpit/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            if not isinstance(data, list):
                return None, "format inattendu (pas une liste)"
            return data, None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as exc:
        return None, str(exc)


def _load_cache(cache_path: pathlib.Path) -> dict:
    """Charge le cache JSON (dernier fetch réussi)."""
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache_path: pathlib.Path, raw_this: list[dict], raw_next: list[dict]) -> None:
    """Sauvegarde le dernier fetch réussi (plan B en cas de 429/timeout)."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "fetched_utc": datetime.now(UTC).isoformat(),
                    "raw_this": raw_this,
                    "raw_next": raw_next,
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("ForexFactory cache write failed: %s", exc)


def fetch_forexfactory_events(
    thisweek_url: str,
    nextweek_url: str,
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    timeout: int = 5,
    cache_path: pathlib.Path | None = None,
    min_interval_s: float = 1800.0,
) -> tuple[list[CalendarEvent], DataStatus, str]:
    """Fetch les événements USD à fort impact depuis ForexFactory.

    Retourne les événements normalisés + consensus/précédent pour croisement.
    Statut DÉGRADÉ si les deux endpoints sont inaccessibles ; en cas de 429 ou
    timeout, sert le cache (jamais silencieusement).

    Returns:
        (events, status, error_msg)
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    from datetime import timedelta

    horizon_end = now_utc + timedelta(days=horizon_days)
    fetched_utc = datetime.now(UTC)

    if cache_path is None:
        cache_path = pathlib.Path("data/cache/forexfactory.json")
    cache = _load_cache(cache_path)

    cached_at = cache.get("fetched_utc")
    fresh = False
    if cached_at:
        try:
            age_s = (fetched_utc - datetime.fromisoformat(cached_at)).total_seconds()
            fresh = age_s < min_interval_s
        except (ValueError, TypeError):
            fresh = False

    if fresh:
        raw_this = cache.get("raw_this", [])
        raw_next = cache.get("raw_next", [])
    else:
        raw_this, err_this = _fetch_ff_json(thisweek_url, timeout)
        raw_next, err_next = _fetch_ff_json(nextweek_url, timeout)
        fetch_errors: list[str] = []
        if raw_this is None:
            raw_this = []
            fetch_errors.append(f"thisweek: {err_this}")
        if raw_next is None:
            raw_next = []
            # 404 = la semaine suivante n'est pas encore publiée : pas une panne.
            if err_next != "HTTP 404":
                fetch_errors.append(f"nextweek: {err_next}")

        # Repli cache si la semaine courante est injoignable (429/timeout).
        if not raw_this and cache.get("raw_this"):
            raw_this = cache.get("raw_this", [])
            raw_next = cache.get("raw_next", [])
        elif raw_this:
            _save_cache(cache_path, raw_this, raw_next)

    all_raw = raw_this + raw_next
    reachable = bool(raw_this or raw_next)

    if not reachable:
        return (
            [],
            DataStatus.DEGRADED,
            "ForexFactory inaccessible (429/timeout) — aucun cache disponible",
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
        scheduled, time_prov, time_status = _parse_ff_date(date_str)
        if scheduled is None:
            continue

        today_et = now_utc.astimezone(ET_TZ).date()
        if scheduled.astimezone(ET_TZ).date() < today_et or scheduled > horizon_end:
            continue

        # Dédoublonner par (name, jour)
        day_key = scheduled.strftime("%Y-%m-%d")
        key = (name, day_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        tier = _TIER_MAP.get(name, 2 if impact == "medium" else 1)
        ev_status = (
            DataStatus.DEGRADED
            if (status == DataStatus.DEGRADED or time_status == DataStatus.DEGRADED)
            else DataStatus.OK
        )

        fcst = entry.get("forecast") or None
        prec = entry.get("previous") or None
        act = entry.get("actual") or None
        c_source = "ForexFactory" if (fcst or prec or act) else ""

        events.append(
            CalendarEvent(
                name=name,
                tier=tier,
                scheduled_utc=scheduled,
                source="forexfactory",
                description=f"[ForexFactory] {raw_title}",
                consensus=fcst,
                previous=prec,
                actual=act,
                source_fetched_utc=fetched_utc,
                source_age_seconds=0.0,
                status=ev_status,
                all_sources=["forexfactory"],
                time_provenance=time_prov,
                consensus_source=c_source,
            )
        )

    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
