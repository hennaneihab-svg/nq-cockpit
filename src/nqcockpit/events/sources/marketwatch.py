"""Source MarketWatch : flux RSS top stories (officiel, sans clé).

Endpoint vérifié (HTTP 200) : https://feeds.content.dowjones.io/public/rss/mw_topstories
Titres d'actualité marché uniquement, non directionnels, sans score de sentiment.
"""

from __future__ import annotations

from datetime import datetime, timezone

from nqcockpit.events.models import DataStatus
from nqcockpit.events.sources.rss_adapter import NewsItem, normalize_feed

UTC = timezone.utc

MARKETWATCH_RSS = "https://feeds.content.dowjones.io/public/rss/mw_topstories"


def fetch_marketwatch_feed(
    rss_url: str = MARKETWATCH_RSS,
    now_utc: datetime | None = None,
    timeout: int = 10,
) -> tuple[list[NewsItem], DataStatus, str]:
    """Fetch le flux RSS MarketWatch top stories et le normalise en NewsItem.

    Returns:
        (items, status, error_msg)
    """
    items, status, err = normalize_feed(rss_url, source="marketwatch", timeout=timeout)
    return items, status, err
