"""Adaptateur RSS officiel générique (sans clé API).

Normalise un flux RSS (RSS 2.0 / Atom) vers un modèle ``NewsItem`` commun.
Utilisé par les sources officielles sans clé (Fed, BEA, BLS, US Treasury, ECB,
agences de presse). Politique réseau : User-Agent identifiant, timeout court,
intervalle minimal par source, et déduplication par (titre, jour).
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from nqcockpit.events.models import DataStatus

log = logging.getLogger(__name__)

UTC = timezone.utc

DEFAULT_USER_AGENT = "NQCockpit/1.0 (contact@nqcockpit.local)"


@dataclass
class NewsItem:
    """Un item de presse normalisé depuis un flux RSS officiel."""

    title: str
    published_utc: datetime | None
    link: str
    source: str


def fetch_rss_items(
    url: str,
    timeout: int = 10,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[list[dict], str | None]:
    """Fetch un flux RSS et retourne ``(items, error)``.

    Chaque item est un dict ``{title, pubdate, link}``. Retourne une liste vide
    et un message d'erreur en cas d'échec (jamais silencieux).
    """
    items: list[dict] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        for node in root.iter("item"):
            title = node.findtext("title") or ""
            pubdate = node.findtext("pubDate") or node.findtext("published") or ""
            link = node.findtext("link") or ""
            items.append({"title": title.strip(), "pubdate": pubdate.strip(), "link": link.strip()})
    except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError, OSError) as exc:
        return [], f"RSS inaccessible: {exc}"
    return items, None


def parse_rss_date(pubdate: str) -> datetime | None:
    """Parse une date RSS/Atom vers un datetime UTC (ou None)."""
    if not pubdate:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(pubdate.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    return None


def normalize_feed(
    url: str,
    source: str,
    timeout: int = 10,
    max_items: int = 40,
) -> tuple[list[NewsItem], DataStatus, str]:
    """Normalise un flux RSS officiel en ``NewsItem``.

    Dédoublonne par ``(titre, jour)``. Statut DÉGRADÉ si le flux est vide ou
    inaccessible. Retourne ``(items, status, error_msg)``.
    """
    raw_items, err = fetch_rss_items(url, timeout=timeout)
    if err is not None or not raw_items:
        return [], DataStatus.DEGRADED, err or "flux vide"

    items: list[NewsItem] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_items:
        title = raw["title"]
        if not title:
            continue
        published = parse_rss_date(raw["pubdate"])
        day_key = published.strftime("%Y-%m-%d") if published else title
        if (title, day_key) in seen:
            continue
        seen.add((title, day_key))
        items.append(
            NewsItem(title=title, published_utc=published, link=raw["link"], source=source)
        )
        if len(items) >= max_items:
            break

    return items, DataStatus.OK, ""
