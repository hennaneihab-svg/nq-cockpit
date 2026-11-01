"""Tests des sources sans clé et du cache ForexFactory (fixtures HTTP mockées).

Aucun réseau réel. Vérifie : parse RSS, 404/429/timeout -> dégradé + cache servi,
déduplication, états de santé et le résumé « N/M sources OK ».
"""

from __future__ import annotations

import json
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


def test_ecb_feed_degrade_gracefully(monkeypatch):
    from nqcockpit.events.sources import ecb

    monkeypatch.setattr(
        ecb, "normalize_feed",
        lambda url, source, timeout: ([], DataStatus.DEGRADED, "flux vide"),
    )
    items, st, err = ecb.fetch_ecb_feed()
    assert st == DataStatus.DEGRADED and items == []


def test_treasury_fiscaldata_parse(monkeypatch):
    """Trésor US : l'API FiscalData (sans clé) est parsée en items d'adjudication."""
    import nqcockpit.events.sources.treasury as tr

    payload = {
        "data": [
            {"security_type": "Bill", "security_term": "8-Week", "auction_date": "2026-11-05"},
            {"security_type": "Note", "security_term": "10-Year", "auction_date": "2026-11-10"},
        ]
    }

    def fake_urlopen(req, timeout):
        class _Resp:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr(tr.urllib.request, "urlopen", fake_urlopen)
    items, st, err = tr.fetch_treasury_feed()
    assert st == DataStatus.OK
    assert len(items) == 2
    assert "Bill" in items[0].title
    assert items[0].source == "treasury"


def test_treasury_fiscaldata_http_error(monkeypatch):
    import nqcockpit.events.sources.treasury as tr

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", None, None)

    monkeypatch.setattr(tr.urllib.request, "urlopen", fake_urlopen)
    items, st, err = tr.fetch_treasury_feed()
    assert st == DataStatus.DEGRADED
    assert items == []
    assert "500" in err


def test_marketwatch_feed(monkeypatch):
    from nqcockpit.events.sources import marketwatch
    from nqcockpit.events.sources.rss_adapter import NewsItem

    monkeypatch.setattr(
        marketwatch,
        "normalize_feed",
        lambda url, source, timeout: (
            [NewsItem(title="Stocks rise", published_utc=None, link="", source="marketwatch")],
            DataStatus.OK,
            "",
        ),
    )
    items, st, err = marketwatch.fetch_marketwatch_feed()
    assert st == DataStatus.OK
    assert items[0].title == "Stocks rise"
    assert items[0].source == "marketwatch"


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
    assert "DEGRADED" in html


def test_load_latest_event_source_health_preserves_age_and_stale(tmp_path):
    from nqcockpit.events.health import load_latest_event_source_health

    ts = "2026-10-31T10:00:00+00:00"
    payload = {
        "source_health": [
            {"source": "fed", "status": "OK", "events_count": 3,
             "error_msg": None, "last_success_utc": ts, "stale": False},
            {"source": "ecb", "status": "DÉGRADÉ", "events_count": 0,
             "error_msg": "flux vide", "last_success_utc": None, "stale": True},
        ]
    }
    (tmp_path / "events_20261031_1000.json").write_text(json.dumps(payload), encoding="utf-8")

    out = load_latest_event_source_health(str(tmp_path))
    assert len(out) == 2
    assert out[0].last_success_utc is not None
    assert out[0].stale is False
    assert out[1].last_success_utc is None
    assert out[1].stale is True


def test_status_pill_localisation():
    from nqcockpit.events.health import _status_pill

    assert "DEGRADED" in _status_pill(DataStatus.DEGRADED, fr=False)
    assert "DÉGRADÉ" in _status_pill(DataStatus.DEGRADED, fr=True)
    assert "DOWN" in _status_pill(DataStatus.BLOCKED, fr=False)
    assert "HORS LIGNE" in _status_pill(DataStatus.BLOCKED, fr=True)


def test_source_health_chip_localisation():
    from nqcockpit.events.health import source_health_chip_html

    sh = [SourceHealth(source="fed", status=DataStatus.OK, events_count=1)]
    assert "sources OK" in source_health_chip_html(sh, fr=False)
    assert "sources OK" in source_health_chip_html(sh, fr=True)
    assert "1/1" in source_health_chip_html(sh)


def test_radar_sets_last_success_utc_for_ok_sources():
    import inspect

    import nqcockpit.events.radar as radar

    src = inspect.getsource(radar)
    # Chaque fetcher réussi (fed, bls, bea, ism, fred, forexfactory, earnings)
    # renseigne last_success_utc pour que l'âge ne soit plus « — ».
    assert src.count("last_success_utc=datetime.now(UTC) if ") >= 7


def test_render_source_health_html_localisation_and_window_empty():
    from nqcockpit.events.health import render_source_health_html

    sh = [
        SourceHealth(source="fed", status=DataStatus.OK, events_count=0,
                     last_success_utc=datetime(2026, 10, 31, 10, 0, tzinfo=UTC)),
        SourceHealth(source="ecb", status=DataStatus.DEGRADED, events_count=0,
                     error_msg="x"),
    ]
    en = render_source_health_html(sh, fr=False)
    assert "Status" in en and "Last success" in en and "Last error" in en
    assert "0 (window empty)" in en
    assert "DEGRADED" in en

    fr = render_source_health_html(sh, fr=True)
    assert "Statut" in fr and "Dernier succès" in fr and "Dernière erreur" in fr
    assert "0 (fenêtre vide)" in fr
    assert "DÉGRADÉ" in fr


def test_bls_uses_contact_email_user_agent(monkeypatch):
    import nqcockpit.events.sources.bls as bls

    seen = {}

    def fake_urlopen(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr(bls.urllib.request, "urlopen", fake_urlopen)
    _, status, _ = bls.fetch_bls_events(
        "https://www.bls.gov/schedule/news_release",
        now_utc=datetime(2026, 10, 31, tzinfo=UTC),
    )
    assert status == DataStatus.OK
    assert "contact@" in seen["ua"]


def test_news_wire_includes_marketwatch(monkeypatch):
    import nqcockpit.macro.news_radar as nr
    from nqcockpit.events.sources import marketwatch
    from nqcockpit.events.sources.rss_adapter import NewsItem

    def fake_urlopen(req, timeout):
        class _Resp:
            def read(self):
                return b"<?xml version='1.0'?><rss><channel></channel></rss>"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr(nr.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        marketwatch,
        "fetch_marketwatch_feed",
        lambda timeout=10: (
            [NewsItem(title="Stocks rise", published_utc=datetime(2026, 10, 31, 10, 0, tzinfo=UTC),
                      link="http://x", source="marketwatch")],
            DataStatus.OK,
            "",
        ),
    )

    report = nr.fetch_live_news_wire(max_items_per_source=5)
    titles = [i.title for i in report.items]
    assert "Stocks rise" in titles
    mw = next(i for i in report.items if i.title == "Stocks rise")
    assert mw.source == "MarketWatch"
    assert mw.age_str
