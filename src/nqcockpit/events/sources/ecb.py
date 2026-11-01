"""Source ECB : flux RSS de presse officiel (sans clé).

Endpoint officiel : https://www.ecb.europa.eu/rss/press.html
Rôle : communiqués de politique monétaire, conférences de presse, calendrier
officiel de la BCE. Non directionnel (contexte seulement).
"""

from __future__ import annotations

from datetime import datetime, timezone

from nqcockpit.events.models import DataStatus
from nqcockpit.events.sources.rss_adapter import NewsItem, normalize_feed

UTC = timezone.utc

ECB_PRESS_RSS = "https://www.ecb.europa.eu/rss/press.html"


def fetch_ecb_feed(
    rss_url: str = ECB_PRESS_RSS,
    now_utc: datetime | None = None,
    timeout: int = 10,
) -> tuple[list[NewsItem], DataStatus, str]:
    """Fetch le flux de presse ECB et le normalise en NewsItem.

    Returns:
        (items, status, error_msg)
    """
    items, status, err = normalize_feed(rss_url, source="ecb", timeout=timeout)
    return items, status, err
