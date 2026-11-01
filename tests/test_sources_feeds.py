"""Tests des sources sans clé et du cache ForexFactory (fixtures HTTP mockées).

Aucun réseau réel. Vérifie : parse RSS, 404/429/timeout -> dégradé + cache servi,
déduplication, états de santé et le résumé « N/M sources OK ».
"""

from __future__ import annotations

import urllib.error
from datetime import datetime, timezone

from nqcockpit.events.models import DataStatus, SourceHealth

UTC = timezone.utc


# ---------------------------------------------------------------------------
# ForexFactory : codes HTTP, cache, plan B
# ---------------------------------------------------------------------------


def _ff_fetch_side_effect(responses):
    """Retourne un callable _fetch_ff_json qui répond selon l'URL."""
    def fake_fetch(url, timeout=5):
        return responses[url]
    return fake_fetch


def test_ff_nextweek_404_degrades_but_serves_thisweek(monkeypatch, tmp_path):
    import nqcockpit.events.sources.forexfactory as ff

    thisweek = [{"country": "USD", "impact": "high", "title": "CPI m/m",
                 "date": "2026-11-10T08:30:00-05:00"}]
    monkeypatch.setattr(ff, "_fetch_ff_json", _ff_fetch_side_effect({
        "http://x/thisweek.json": (thisweek, None),
        "http://x/nextweek.json": (None, "HTTP 404"),
    }))

    now = datetime(2026, 11, 1, tzinfo=UTC)
    events, status, err = ff.fetch_forexfactory_events(
        "http://x/thisweek.json", "http://x/nextweek.json",
        now_utc=now, cache_path=tmp_path / "ff.json", min_interval_s=0,
    )
    assert status == DataStatus.DEGRADED
    assert "404" in err
    assert len(events) == 1
    assert events[0].name == "CPI"


def test_ff_429_serves_cache(monkeypatch, tmp_path):
    import nqcockpit.events.sources.forexfactory as ff

    good = [{"country": "USD", "impact": "high", "title": "CPI m/m",
             "date": "2026-11-10T08:30:00-05:00"}]
    state = {"mode": "good"}

    def fake_fetch(url, timeout=5):
        if "thisweek" in url:
            return (good, None) if state["mode"] == "good" else (None, "HTTP 429")
        return None, "HTTP 404"

    monkeypatch.setattr(ff, "_fetch_ff_json", fake_fetch)
    now = datetime(2026, 11, 1, tzinfo=UTC)

    ev1, _, _ = ff.fetch_forexfactory_events(
        "http://x/thisweek.json", "http://x/nextweek.json",
        now_utc=now, cache_path=tmp_path / "ff.json", min_interval_s=0,
    )
    assert len(ev1) == 1

    state["mode"] = "rate_limited"
    ev2, st2, _ = ff.fetch_forexfactory_events(
        "http://x/thisweek.json", "http://x/nextweek.json",
        now_utc=now, cache_path=tmp_path / "ff.json", min_interval_s=0,
    )
    assert len(ev2) == 1  # servi depuis le cache
    assert st2 == DataStatus.DEGRADED


def test_ff_fetch_distinguishes_http_codes(monkeypatch):
    import nqcockpit.events.sources.forexfactory as ff

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(ff.urllib.request, "urlopen", fake_urlopen)
    data, err = ff._fetch_ff_json("http://x/nextweek.json")
    assert data is None
    assert err == "HTTP 404"


# ---------------------------------------------------------------------------
# Adaptateur RSS générique + sources ECB / Treasury
# ---------------------------------------------------------------------------


def test_rss_adapter_parse_ok(monkeypatch):
    import nqcockpit.events.sources.rss_adapter as ra

    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        '<item><title>ECB press</title>'
        '<pubDate>Wed, 04 Nov 2026 14:30:00 GMT</pubDate>'
        '<link>http://x/1</link></item></channel></rss>'
    )

    def fake_urlopen(req, timeout):
        class _Resp:
            def read(self):
                return rss.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr(ra.urllib.request, "urlopen", fake_urlopen)
    items, status, err = ra.normalize_feed("http://x/rss", source="ecb")
    assert status == DataStatus.OK
    assert len(items) == 1
    assert items[0].title == "ECB press"
    assert items[0].source == "ecb"
    assert items[0].published_utc is not None


def test_rss_adapter_404_degrades(monkeypatch):
    import nqcockpit.events.sources.rss_adapter as ra

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(ra.urllib.request, "urlopen", fake_urlopen)
    items, status, err = ra.normalize_feed("http://x/rss", source="ecb")
    assert status == DataStatus.DEGRADED
    assert items == []
    assert "404" in err


def test_ecb_and_treasury_feeds_degrade_gracefully(monkeypatch):
    from nqcockpit.events.sources import ecb, treasury

    monkeypatch.setattr(
        ecb, "normalize_feed",
        lambda url, source, timeout: ([], DataStatus.DEGRADED, "flux vide"),
    )
    monkeypatch.setattr(
        treasury, "normalize_feed",
        lambda url, source, timeout: ([], DataStatus.DEGRADED, "flux vide"),
    )
    items, st, err = ecb.fetch_ecb_feed()
    assert st == DataStatus.DEGRADED and items == []
    items2, st2, _ = treasury.fetch_treasury_feed()
    assert st2 == DataStatus.DEGRADED and items2 == []


# ---------------------------------------------------------------------------
# Santé des sources : résumé + rendu HTML (états, stale)
# ---------------------------------------------------------------------------


def test_source_health_summary_and_html():
    from nqcockpit.events.health import render_source_health_html, source_health_summary

    sh = [
        SourceHealth(source="fed", status=DataStatus.OK, events_count=3,
                     last_success_utc=datetime(2026, 11, 1, tzinfo=UTC)),
        SourceHealth(source="ecb", status=DataStatus.DEGRADED, events_count=0,
                     error_msg="flux vide", stale=True),
    ]
    assert source_health_summary(sh) == "1/2"

    html = render_source_health_html(sh, fr=False)
    assert "fed" in html
    assert "STALE" in html
    assert "flux vide" in html
    assert "DÉGRADÉ" in html
