"""Source US Treasury : calendrier d'adjudications (FiscalData API, sans clé).

Diagnostic réel : le flux RSS ``home.treasury.gov/news/press-releases.rss``
expire (timeout) depuis ce réseau, mais la page HTML (200) et l'API officielle
FiscalData ``upcoming_auctions`` (200, sans clé) répondent. On utilise donc
l'API FiscalData pour le calendrier d'adjudications.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

from nqcockpit.events.models import DataStatus
from nqcockpit.events.sources.rss_adapter import NewsItem

log = logging.getLogger(__name__)

UTC = timezone.utc

AUCTIONS_API = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v1/accounting/od/upcoming_auctions"
)

DEFAULT_USER_AGENT = "NQCockpit/1.0 (contact@nqcockpit.local)"


def fetch_treasury_feed(
    api_url: str = AUCTIONS_API,
    now_utc: datetime | None = None,
    timeout: int = 10,
) -> tuple[list[NewsItem], DataStatus, str]:
    """Fetch le calendrier d'adjudications du Trésor US (FiscalData, sans clé).

    Returns:
        (items, status, error_msg)
    """
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": DEFAULT_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return [], DataStatus.DEGRADED, f"FiscalData HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return [], DataStatus.DEGRADED, f"FiscalData inaccessible: {exc}"
    except json.JSONDecodeError as exc:
        return [], DataStatus.DEGRADED, f"FiscalData JSON invalide: {exc}"

    records = data.get("data", []) if isinstance(data, dict) else []
    items: list[NewsItem] = []
    for rec in records:
        sec = str(rec.get("security_type", "")).strip()
        term = str(rec.get("security_term", "")).strip()
        title = "Treasury auction: " + " ".join(p for p in (sec, term) if p)
        published: datetime | None = None
        auction_date = rec.get("auction_date") or rec.get("announcement_date") or ""
        if auction_date:
            try:
                published = datetime.strptime(
                    str(auction_date)[:10], "%Y-%m-%d"
                ).replace(tzinfo=UTC)
            except ValueError:
                published = None
        items.append(NewsItem(title=title, published_utc=published, link="", source="treasury"))

    if items:
        return items, DataStatus.OK, ""
    return [], DataStatus.DEGRADED, "aucune adjudication à venir (FiscalData)"
