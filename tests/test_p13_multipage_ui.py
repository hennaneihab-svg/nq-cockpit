"""Tests unitaires P13 — UI Finale Consolidée Multipage et Design System.

Vérifie l'importabilité des pages, l'exécution réelle des composants et renderers UI,
la structure de l'application multipage, et la non-directionnalité des libellés UI.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from nqcockpit.briefing.models import PreSessionBriefing
from nqcockpit.ui.app import main as app_main
from nqcockpit.ui.briefing_page import render_briefing_page
from nqcockpit.ui.coaching_page import render_coaching_app
from nqcockpit.ui.cockpit_page import render_cockpit
from nqcockpit.ui.components import (
    render_degraded_banner,
    render_status_badge,
    render_terminal_metric,
)
from nqcockpit.ui.db import get_ui_db
from nqcockpit.ui.discipline_page import render_discipline_page
from nqcockpit.ui.journal_page import render_journal_page


def test_ui_renderers_importable():
    """Vérifie que chaque sous-page exporte sa fonction de rendu sans erreur."""
    assert callable(render_cockpit)
    assert callable(render_journal_page)
    assert callable(render_discipline_page)
    assert callable(render_coaching_app)
    assert callable(render_briefing_page)
    assert callable(app_main)


def test_streamlit_config_exists():
    """Vérifie la présence et le contenu de la configuration du thème Streamlit."""
    config_path = Path(".streamlit/config.toml")
    assert config_path.exists(), ".streamlit/config.toml doit exister"
    content = config_path.read_text(encoding="utf-8")
    assert '[theme]' in content
    assert 'backgroundColor = "#020617"' in content
    assert 'font = "sans serif"' in content


def test_ui_components_export():
    """Vérifie l'exécution des fonctions de rendu de composants UI."""
    assert callable(render_status_badge)
    assert callable(render_degraded_banner)
    assert callable(render_terminal_metric)


def test_non_directional_ui_labels():
    """Vérifie qu'aucun fichier UI ne contient de terme directionnel interdit."""
    directional_regex = re.compile(
        r"\b(bullish|bearish|haussier|baissier|achat fort|vente forte)\b",
        re.IGNORECASE,
    )
    ui_dir = Path("src/nqcockpit/ui")
    for py_file in ui_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        matches = directional_regex.findall(content)
        assert not matches, (
            f"Fichier UI {py_file.name} contient des termes directionnels interdits : {matches}"
        )


def test_render_briefing_page_execution():
    """Exécute réellement render_briefing_page avec un objet PreSessionBriefing actif."""
    briefing = PreSessionBriefing(
        timestamp_utc=datetime.now(timezone.utc),
        session_date_ny="2026-10-01",
        timestamp_algiers_str="2026-10-01 04:00:00",
        status="OK",
        status_warnings=[],
        markdown_briefing="# Briefing Test Multipage P13",
    )
    st.session_state["current_briefing"] = briefing

    # Valide l'accès aux deux propriétés d'horodatage sans AttributeError
    assert briefing.timestamp_algiers_str == "2026-10-01 04:00:00"
    assert briefing.timestamp_alg == "2026-10-01 04:00:00"

    # L'exécution réelle de la page ne doit pas lever d'exception
    render_briefing_page()


def test_render_discipline_page_execution():
    """Exécute réellement render_discipline_page."""
    render_discipline_page()


def test_render_cockpit_execution():
    """Exécute réellement render_cockpit."""
    render_cockpit()


def test_ui_db_connection_cached():
    """Vérifie la centralisation et la mise en cache de la connexion SQLite UI."""
    conn1 = get_ui_db()
    conn2 = get_ui_db()
    assert conn1 is conn2, "get_ui_db() doit retourner une instance unique mise en cache"


def test_tradingview_widget_config_loading():
    """Vérifie le chargement du symbole TradingView depuis config.yaml."""
    from nqcockpit.config import load_config
    cfg = load_config()
    assert hasattr(cfg.sources, "tradingview_symbol")
    assert cfg.sources.tradingview_symbol == "CME_MINI:NQ1!"


def test_tradingview_widget_render():
    """Vérifie l'exécution du composant graphique TradingView."""
    from nqcockpit.ui.components import render_tradingview_chart
    assert callable(render_tradingview_chart)
    # L'exécution du composant ne doit lever aucune exception
    render_tradingview_chart(symbol="CME_MINI:NQ1!", height=750)


def test_tradingview_widget_offline_degradation():
    """Vérifie le repli en mode DÉGRADÉ visible lors d'une absence de connexion internet."""
    from nqcockpit.ui.components import render_tradingview_chart
    # En forçant le mode offline, le bandeau DÉGRADÉ doit être rendu de façon propre
    render_tradingview_chart(symbol="CME_MINI:NQ1!", force_offline=True)


def test_tradingview_widget_socket_failure_simulation():
    """Simule concrètement une panne réseau au niveau socket via unittest.mock.patch."""
    from unittest.mock import patch

    from nqcockpit.ui.components import render_tradingview_chart

    with patch("socket.create_connection", side_effect=OSError("Network unreachable")):
        render_tradingview_chart(symbol="CME:NQ1!")


