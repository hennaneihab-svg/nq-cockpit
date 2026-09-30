"""Source FRED : dates de publication des séries économiques clés.

Utilise l'API FRED (clé gratuite, 120 req/min) pour récupérer les dates
de release passées et extrapoler la prochaine date.
Release IDs : CPI=10, PPI=46, NFP=50, GDP=53, PCE=54.

Rôle : CONTRÔLE CROISÉ avec BLS/BEA, pas source primaire.
Signale les divergences si FRED indique une date différente.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nqcockpit.events.models import CalendarEvent, DataStatus

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc

# Release IDs FRED par défaut (overridable via config)
DEFAULT_RELEASE_IDS = {
    "CPI": 10,
    "PPI": 46,
    "NFP": 50,
    "GDP": 53,
    "PCE": 54,
}

# Heure de publication FRED pour chaque release (08h30 ET pour BLS/BEA)
RELEASE_HOURS_ET = {
    "CPI": (8, 30),
    "PPI": (8, 30),
    "NFP": (8, 30),
    "GDP": (8, 30),
    "PCE": (8, 30),
}

# Tiers
RELEASE_TIERS = {
    "CPI": 1, "NFP": 1, "GDP": 1, "PCE": 1,
    "PPI": 2,
}


def _load_fred_key() -> str:
    """Charge la clé FRED depuis l'environnement ou le fichier .env."""
    key = os.environ.get("FRED_API_KEY", "")
    if key:
        return key
    # Recherche dans .env à la racine du projet
    for candidate in [
        pathlib.Path.cwd() / ".env",
        pathlib.Path(__file__).parent.parent.parent.parent.parent / ".env",
    ]:
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("FRED_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return ""


def _fetch_release_dates(
    release_id: int,
    api_key: str,
    timeout: int = 10,
) -> list[str]:
    """Récupère les 5 dernières dates de publication FRED pour un release_id."""
    url = (
        f"https://api.stlouisfed.org/fred/release/dates"
        f"?release_id={release_id}&api_key={api_key}"
        f"&file_type=json&sort_order=desc&limit=5"
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "NQCockpit/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return [d.get("date", "") for d in data.get("release_dates", [])]
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        log.warning("FRED release %s fetch error: %s", release_id, exc)
        return []


def _is_us_federal_holiday(d: date) -> bool:
    """Vérifie si une date correspond à un jour férié fédéral américain."""
    month = d.month
    day = d.day
    weekday = d.weekday()  # 0=Monday, 6=Sunday

    # 1. New Year's Day (Jan 1, ou Jan 2 si Jan 1 est dimanche)
    if month == 1 and (day == 1 or (day == 2 and weekday == 0)):
        return True
    # 2. Martin Luther King Jr. Day (3e lundi de janvier)
    if month == 1 and weekday == 0 and 15 <= day <= 21:
        return True
    # 3. Washington's Birthday / Presidents' Day (3e lundi de février)
    if month == 2 and weekday == 0 and 15 <= day <= 21:
        return True
    # 4. Memorial Day (dernier lundi de mai)
    if month == 5 and weekday == 0 and day >= 25:
        return True
    # 5. Juneteenth (19 juin, ou 20 si dimanche, ou 18 si samedi)
    if month == 6 and (
        day == 19 or (day == 20 and weekday == 0) or (day == 18 and weekday == 4)
    ):
        return True
    # 6. Independence Day (4 juillet)
    if month == 7 and (
        day == 4 or (day == 5 and weekday == 0) or (day == 3 and weekday == 4)
    ):
        return True
    # 7. Labor Day (1er lundi de septembre)
    if month == 9 and weekday == 0 and 1 <= day <= 7:
        return True
    # 8. Columbus Day / Indigenous Peoples' Day (2e lundi d'octobre)
    if month == 10 and weekday == 0 and 8 <= day <= 14:
        return True
    # 9. Veterans Day (11 novembre)
    if month == 11 and (
        day == 11 or (day == 12 and weekday == 0) or (day == 10 and weekday == 4)
    ):
        return True
    # 10. Thanksgiving Day (4e jeudi de novembre)
    if month == 11 and weekday == 3 and 22 <= day <= 28:
        return True
    # 11. Christmas Day (25 décembre)
    if month == 12 and (
        day == 25 or (day == 26 and weekday == 0) or (day == 24 and weekday == 4)
    ):
        return True
    return False


def _infer_next_date(past_dates: list[str]) -> str | None:
    """Infère la prochaine date à partir des dates passées (pattern mensuel).

    Calcule le delta médian entre les 3 dernières dates et l'ajoute à la plus
    récente. Exclut automatiquement les week-ends et jours fériés fédéraux US.
    """
    if len(past_dates) < 2:
        return None
    parsed = []
    for ds in past_dates:
        try:
            parsed.append(datetime.strptime(ds, "%Y-%m-%d").date())
        except ValueError:
            continue
    if len(parsed) < 2:
        return None
    parsed.sort(reverse=True)
    deltas = [(parsed[i] - parsed[i + 1]).days for i in range(len(parsed) - 1)]
    median_delta = sorted(deltas)[len(deltas) // 2]
    next_date = parsed[0] + timedelta(days=median_delta)

    # Les publications gouvernementales ne sont jamais publiées le week-end
    # ni les jours fériés fédéraux
    while next_date.weekday() >= 5 or _is_us_federal_holiday(next_date):
        next_date += timedelta(days=1)
    return next_date.isoformat()


def _make_utc(date_str: str, hour_et: int, minute_et: int) -> datetime:
    naive = datetime(
        int(date_str[:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        hour_et,
        minute_et,
        tzinfo=ET_TZ,
    )
    return naive.astimezone(UTC)


def fetch_fred_events(
    release_ids: dict[str, int] | None = None,
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    timeout: int = 10,
) -> tuple[list[CalendarEvent], DataStatus, str]:
    """Fetch les dates FRED pour contrôle croisé avec BLS/BEA.

    Retourne uniquement les événements futurs dans l'horizon donné.
    Statut DÉGRADÉ si clé absente ou API inaccessible.

    Returns:
        (events, status, error_msg)
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    if release_ids is None:
        release_ids = DEFAULT_RELEASE_IDS

    api_key = _load_fred_key()
    if not api_key:
        return (
            [],
            DataStatus.DEGRADED,
            "FRED_API_KEY absente — contrôle croisé FRED indisponible",
        )

    from datetime import timedelta

    horizon_end = now_utc + timedelta(days=horizon_days)
    fetched_utc = datetime.now(UTC)
    age_s = 0.0

    events: list[CalendarEvent] = []
    any_error = False

    for name, rid in release_ids.items():
        past_dates = _fetch_release_dates(rid, api_key, timeout=timeout)
        if not past_dates:
            any_error = True
            log.warning("FRED: aucune date pour %s (id=%s)", name, rid)
            continue

        next_date_str = _infer_next_date(past_dates)
        if next_date_str is None:
            continue

        time_pair = RELEASE_HOURS_ET.get(name)
        if time_pair is not None:
            hour_et, min_et = time_pair
            time_prov = f"règle FRED ({hour_et:02d}:{min_et:02d} ET)"
            ev_status = DataStatus.OK
        else:
            hour_et, min_et = 0, 0
            time_prov = "non fournie [DÉGRADÉ]"
            ev_status = DataStatus.DEGRADED

        try:
            scheduled = _make_utc(next_date_str, hour_et, min_et)
        except ValueError:
            continue

        today_et = now_utc.astimezone(ET_TZ).date()
        if scheduled.astimezone(ET_TZ).date() < today_et or scheduled > horizon_end:
            continue

        tier = RELEASE_TIERS.get(name, 2)
        events.append(
            CalendarEvent(
                name=name,
                tier=tier,
                scheduled_utc=scheduled,
                source="fred",
                description=(
                    f"{name} — date extrapolée FRED (passées : "
                    f"{', '.join(past_dates[:3])})"
                ),
                source_fetched_utc=fetched_utc,
                source_age_seconds=age_s,
                status=ev_status,
                all_sources=["fred"],
                time_provenance=time_prov,
            )
        )

    status = DataStatus.DEGRADED if any_error else DataStatus.OK
    error_msg = "Certaines séries FRED inaccessibles" if any_error else ""
    events.sort(key=lambda e: e.scheduled_utc)
    return events, status, error_msg
