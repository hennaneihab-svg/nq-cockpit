"""Tests unitaires pour le Radar Macro et le Dashboard synthétique (Tâche 5).

Vérifie :
1. Le statut DÉGRADÉ explicite sur défaillance de chaque flux (2Y, 10Y, CPI, Fed, WTI, DXY).
2. L'horloge multi-fuseaux (Africa/Algiers et America/New_York) sans décalage codé en dur.
3. L'affichage de la valeur en cache pour DGS2 en statut DÉGRADÉ (cohérence données).
4. La règle de cache intraday <= 60 s pour WTI, DXY et flux RSS.
5. Le fil d'actualités en direct (Fed RSS + Google News) et sa gestion dégradée.
6. L'exécution de render_cockpit() avec les 6 fenêtres et le fil d'actualités.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from nqcockpit.data.models import DataStatus, FredObservation
from nqcockpit.macro.news_radar import (
    CACHE_TTL_CONFIG,
    MacroRadarCard,
    _format_age,
    fetch_dollar_card,
    fetch_fed_card,
    fetch_inflation_card,
    fetch_live_news_wire,
    fetch_mega_caps_card,
    fetch_oil_card,
    fetch_rates_card,
    is_relevant_fed_wire_item,
)
from nqcockpit.ui.cockpit_page import _render_radar_card_html, render_cockpit

UTC = timezone.utc
TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_ET = ZoneInfo("America/New_York")


def test_format_age_utility():
    """Vérifie le formatage lisible de l'âge des données."""
    assert _format_age(45) == "45s"
    assert _format_age(120) == "2 min"
    assert _format_age(7200) == "2h 0m"
    assert _format_age(172800) == "2j 0h"


def test_dual_clocks_timezone_integrity():
    """Vérifie la conversion stricte entre Alger et New York sans offset en dur."""
    now_utc = datetime(2026, 10, 4, 18, 30, 0, tzinfo=UTC)
    card = MacroRadarCard(
        category="TEST",
        title="Test Clocks",
        main_value="100",
        sub_value="ok",
        source="Source Test",
        timestamp_utc=now_utc,
        observation_date="2026-10-04",
        age_str="1 min",
        status="OK",
        is_ok=True,
    )

    # 18h30 UTC = 19h30 Alger (UTC+1)
    assert "19:30 (Alger)" in card.timestamp_algiers_str
    # 18h30 UTC = 14h30 ET (UTC-4)
    assert "14:30 ET" in card.timestamp_et_str


def test_intraday_cache_ttl_triggers_network_after_61s(tmp_path):
    """Vérifie qu'une deuxième requête après 61s invalide le cache et déclenche un appel réseau."""
    from nqcockpit.data.cache import DiskCache
    from nqcockpit.macro.news_radar import get_cached_or_fetch

    test_cache = DiskCache(tmp_path / "test_cache")
    mock_network_fetcher = MagicMock(return_value={"status": "fresh_data"})

    t0 = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)

    # 1. Premier appel à t0 -> appel réseau déclenché
    with patch("nqcockpit.data.cache.datetime") as mock_dt:
        mock_dt.now.return_value = t0
        mock_dt.fromisoformat = datetime.fromisoformat
        res1 = get_cached_or_fetch(
            "intraday_key",
            mock_network_fetcher,
            max_age_seconds=60.0,
            cache=test_cache,
        )
        assert res1 == {"status": "fresh_data"}
        assert mock_network_fetcher.call_count == 1

    # 2. Deuxième appel à t0 + 30s -> servi depuis le cache, aucun appel réseau
    t_30s = datetime(2026, 10, 4, 12, 0, 30, tzinfo=UTC)
    with patch("nqcockpit.data.cache.datetime") as mock_dt:
        mock_dt.now.return_value = t_30s
        mock_dt.fromisoformat = datetime.fromisoformat
        res2 = get_cached_or_fetch(
            "intraday_key",
            mock_network_fetcher,
            max_age_seconds=60.0,
            cache=test_cache,
        )
        assert res2 == {"status": "fresh_data"}
        assert mock_network_fetcher.call_count == 1

    # 3. Troisième appel à t0 + 61s -> cache expiré (> 60s), nouvel appel réseau déclenché
    t_61s = datetime(2026, 10, 4, 12, 1, 1, tzinfo=UTC)
    mock_network_fetcher.return_value = {"status": "renewed_data"}
    with patch("nqcockpit.data.cache.datetime") as mock_dt:
        mock_dt.now.return_value = t_61s
        mock_dt.fromisoformat = datetime.fromisoformat
        res3 = get_cached_or_fetch(
            "intraday_key",
            mock_network_fetcher,
            max_age_seconds=60.0,
            cache=test_cache,
        )
        assert res3 == {"status": "renewed_data"}
        assert mock_network_fetcher.call_count == 2

    # 4. Vérification complémentaire des constantes de configuration
    intraday_keys = [
        "YAHOO_WTI",
        "YAHOO_DXY",
        "YAHOO_TNX",
        "MAG7_CALENDAR",
        "RSS_FED",
        "RSS_GOOGLE_NEWS",
    ]
    for key in intraday_keys:
        ttl = CACHE_TTL_CONFIG[key]
        assert ttl <= 60.0, f"Le cache intraday pour {key} ({ttl}s) dépasse la limite de 60s"
    assert CACHE_TTL_CONFIG["FRED_DAILY"] <= 1800.0


def test_rates_card_degraded_displays_cached_2y_value():
    """Vérifie la cohérence DGS2 : affiche la valeur en cache, sa date et son âge en DÉGRADÉ."""
    mock_fetcher = MagicMock()
    now_utc = datetime.now(UTC)

    # 10 ans OK direct, 2 ans direct défaillant
    mock_fetcher.fetch_fred_series.side_effect = [
        FredObservation(
            series_id="DGS10",
            observation_date="2026-10-01",
            value=5.24,
            source="FRED",
            fetched_at_utc=now_utc,
            status=DataStatus.OK,
        ),
        FredObservation(
            series_id="DGS2",
            observation_date="",
            value=0.0,
            source="FRED",
            fetched_at_utc=now_utc,
            status=DataStatus.DEGRADED,
            notes="Panne réseau",
        ),
    ]

    # Le cache local contient l'observation précédente
    mock_fetcher.cache.get.return_value = {
        "series_id": "DGS2",
        "observation_date": "2026-10-01",
        "value": 4.78,
        "fetched_at_utc": now_utc.isoformat(),
        "status": "OK",
    }

    card = fetch_rates_card(mock_fetcher)
    assert card.status == "DÉGRADÉ"
    assert not card.is_ok
    # La valeur en cache de 2Y (4.78%) doit être affichée, pas INDISPONIBLE
    assert "4.78%" in card.main_value
    assert "5.24%" in card.main_value
    assert "cache" in card.main_value.lower()
    # Le motif doit mentionner la date d'observation du cache
    assert "Obs: 2026-10-01" in card.degraded_reason
    assert "repli cache local" in card.degraded_reason
    # Le badge rendu doit être deg-dot (ambre fixe)
    assert "deg-dot" in _render_radar_card_html(card, delay_idx=0)


def test_rates_card_10y_fallback_yahoo_delayed():
    """Vérifie que le repli 10 ans sur Yahoo Finance est étiqueté 'différé 15 min' et DÉGRADÉ."""
    mock_fetcher = MagicMock()
    mock_fetcher.cache.get.return_value = None
    now_utc = datetime.now(UTC)

    # 10 ans FRED indisponible, 2 ans OK
    mock_fetcher.fetch_fred_series.side_effect = [
        FredObservation(
            series_id="DGS10",
            observation_date="",
            value=0.0,
            source="FRED",
            fetched_at_utc=now_utc,
            status=DataStatus.DEGRADED,
        ),
        FredObservation(
            series_id="DGS2",
            observation_date="2026-10-01",
            value=4.78,
            source="FRED",
            fetched_at_utc=now_utc,
            status=DataStatus.OK,
        ),
    ]

    with patch("yfinance.Ticker") as mock_ticker:
        import pandas as pd

        mock_df = pd.DataFrame({"Close": [52.4]})
        mock_ticker.return_value.history.return_value = mock_df

        card = fetch_rates_card(mock_fetcher)
        assert card.status == "DÉGRADÉ"
        assert not card.is_ok
        assert "différée de 15 min" in card.degraded_reason
        assert "Yahoo ^TNX/10 [différé 15 min]" in card.source


def test_inflation_card_degraded_when_history_insufficient():
    """Vérifie le statut DÉGRADÉ si l'historique CPI est inférieur à 13 observations."""
    with patch("nqcockpit.macro.news_radar.fetch_fred_history", return_value=[]):
        card = fetch_inflation_card()
        assert card.status == "DÉGRADÉ"
        assert not card.is_ok
        assert card.main_value == "INDISPONIBLE"
        assert "deg-dot" in _render_radar_card_html(card, delay_idx=1)


def test_mega_caps_card_degraded_when_scans_fail():
    """Vérifie le statut DÉGRADÉ si les calendriers tech sont inaccessibles."""
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        card = fetch_mega_caps_card()
        assert card.status == "DÉGRADÉ"
        assert not card.is_ok
        assert card.main_value == "INDISPONIBLE"


def test_fed_card_degraded_when_rates_unavailable():
    """Vérifie le statut DÉGRADÉ si les données FOMC de FRED échouent."""
    mock_fetcher = MagicMock()
    now_utc = datetime.now(UTC)
    mock_fetcher.fetch_fred_series.return_value = FredObservation(
        series_id="DFEDTARU",
        observation_date="",
        value=0.0,
        source="FRED",
        fetched_at_utc=now_utc,
        status=DataStatus.DEGRADED,
    )
    card = fetch_fed_card(mock_fetcher)
    assert card.status == "DÉGRADÉ"
    assert not card.is_ok
    assert "INDISPONIBLE" in card.main_value


def test_oil_card_degraded_on_network_failure():
    """Vérifie le statut DÉGRADÉ pour le pétrole en cas d'échec de cotation."""
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.side_effect = RuntimeError("Réseau indisponible")
        card = fetch_oil_card()
        assert card.status == "DÉGRADÉ"
        assert not card.is_ok
        assert "ERREUR RÉSEAU" in card.main_value


def test_dollar_card_degraded_on_weekend():
    """Vérifie que le DXY bascule explicitement en DÉGRADÉ le week-end avec motif honnête."""
    sunday_utc = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
    with patch("nqcockpit.macro.news_radar.datetime") as mock_dt:
        mock_dt.now.return_value = sunday_utc
        with patch("yfinance.Ticker") as mock_ticker:
            import pandas as pd

            df = pd.DataFrame(
                {"Close": [102.10, 101.93]},
                index=[pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02")],
            )
            mock_ticker.return_value.history.return_value = df

            card = fetch_dollar_card()
            assert card.status == "DÉGRADÉ"
            assert not card.is_ok
            assert "week-end" in card.degraded_reason
            assert "deg-dot" in _render_radar_card_html(card, delay_idx=5)


def test_live_news_wire_fetches_and_degraded_fallback():
    """Vérifie que fetch_live_news_wire gère la dégradation si une source échoue."""
    # Simulation d'un échec Google News mais succès Fed RSS
    fake_rss_xml = b"""<rss version="2.0"><channel>
        <item>
            <title>Test Fed Headline Statement</title>
            <link>https://www.federalreserve.gov/test.htm</link>
            <pubDate>Sun, 04 Oct 2026 14:00:00 GMT</pubDate>
        </item>
    </channel></rss>"""

    def mock_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "federalreserve.gov" in url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = fake_rss_xml
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp
        raise RuntimeError("Simulation coupure réseau Google")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        report = fetch_live_news_wire(max_items_per_source=2)
        assert len(report.items) == 1
        item = report.items[0]
        assert item.title == "Test Fed Headline Statement"
        assert item.link == "https://www.federalreserve.gov/test.htm"
        assert "Alger" in item.timestamp_algiers_str
        assert "ET" in item.timestamp_et_str
        # Google News doit apparaître en source dégradée
        assert not report.is_ok
        assert any("Google News" in s for s in report.degraded_sources)


def test_render_cockpit_full_execution_without_error():
    """Exécute render_cockpit() de bout en bout avec le radar et le fil sans exception."""
    render_cockpit()


def test_fed_wire_filter_relevance_procedural_vs_policy():
    """Vérifie que le filtre élimine le bruit procédural et préserve les dépêches de marché."""
    # Exemples administratifs/procéduraux qui ne bougent pas le marché (à exclure)
    assert not is_relevant_fed_wire_item("extend comment period on Regulation O proposal")
    assert not is_relevant_fed_wire_item("enforcement action with Ontario Bancorporation")
    assert not is_relevant_fed_wire_item(
        "Federal Reserve Board announces it will extend comment period on Regulation O proposal"
    )
    assert not is_relevant_fed_wire_item(
        "Federal Reserve Board issues enforcement action with Ontario Bancorporation"
    )
    assert not is_relevant_fed_wire_item("proposes to extend compliance date for regulatory report")
    assert not is_relevant_fed_wire_item("Federal Reserve issues correction to statistical release")
    assert not is_relevant_fed_wire_item("appointment of director to branch board")

    # Exemple de dépêche pertinente (à conserver impérativement)
    assert is_relevant_fed_wire_item("FOMC raises target rate")

    # Autres dépêches monétaires et macroéconomiques pertinentes conservées par défaut
    assert is_relevant_fed_wire_item("Federal Reserve issues FOMC statement")
    assert is_relevant_fed_wire_item("Chair Powell speech on monetary policy and inflation outlook")
    assert is_relevant_fed_wire_item("Federal Reserve releases Beige Book")
    assert is_relevant_fed_wire_item("Minutes of the Federal Open Market Committee")
    assert is_relevant_fed_wire_item("release economic projections from the September FOMC meeting")


def test_fetch_live_news_wire_filters_administrative_items():
    """Vérifie l'intégration dans fetch_live_news_wire : exclusion des dépêches procédurales."""
    fake_fed_xml = b"""<rss version="2.0"><channel>
        <item>
            <title>extend comment period on Regulation O proposal</title>
            <link>https://www.federalreserve.gov/press/1.htm</link>
            <pubDate>Mon, 05 Oct 2026 14:00:00 GMT</pubDate>
        </item>
        <item>
            <title>enforcement action with Ontario Bancorporation</title>
            <link>https://www.federalreserve.gov/press/2.htm</link>
            <pubDate>Mon, 05 Oct 2026 13:00:00 GMT</pubDate>
        </item>
        <item>
            <title>FOMC raises target rate</title>
            <link>https://www.federalreserve.gov/press/3.htm</link>
            <pubDate>Mon, 05 Oct 2026 12:00:00 GMT</pubDate>
        </item>
    </channel></rss>"""

    def mock_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "federalreserve.gov" in url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = fake_fed_xml
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp
        # Stub Google News sans éléments
        mock_g = MagicMock()
        mock_g.read.return_value = b"<rss><channel></channel></rss>"
        mock_g.__enter__.return_value = mock_g
        return mock_g

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        report = fetch_live_news_wire(max_items_per_source=5)
        fed_items = [it for it in report.items if it.tag == "FED / TAUX"]
        titles = [it.title for it in fed_items]

        # L'élément pertinent doit être présent
        assert "FOMC raises target rate" in titles
        # Les éléments administratifs doivent être exclus
        assert "extend comment period on Regulation O proposal" not in titles
        assert "enforcement action with Ontario Bancorporation" not in titles
        assert len(fed_items) == 1

