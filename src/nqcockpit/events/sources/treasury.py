"""Source US Treasury : communiqués de presse officiels (sans clé).

Endpoint officiel : https://home.treasury.gov/news/press-releases.rss
Rôle : calendrier d'adjudications et communiqués du Trésor US (contexte macro,
non directionnel). Peut être lent/bloqué depuis certains réseaux : la source
se dégrade proprement et sert un statut DÉGRADÉ visible.
"""

from __future__ import annotations

from datetime import datetime, timezone

from nqcockpit.events.models import DataStatus
from nqcockpit.events.sources.rss_adapter import NewsItem, normalize_feed

UTC = timezone.utc

TREASURY_PRESS_RSS = "https://home.treasury.gov/news/press-releases.rss"


def fetch_treasury_feed(
    rss_url: str = TREASURY_PRESS_RSS,
    now_utc: datetime | None = None,
    timeout: int = 10,
) -> tuple[list[NewsItem], DataStatus, str]:
    """Fetch le flux de presse du Trésor US et le normalise en NewsItem.

    Returns:
        (items, status, error_msg)
    """
    items, status, err = normalize_feed(rss_url, source="treasury", timeout=timeout)
    return items, status, err
