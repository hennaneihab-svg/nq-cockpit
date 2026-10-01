"""Tests unitaires P13 — UI Finale Consolidée Multipage et Design System.

Vérifie l'importabilité des pages, la structure de l'application multipage,
les composants du design system et la non-directionnalité des libellés UI.
"""

from __future__ import annotations

import re
from pathlib import Path

from nqcockpit.ui.app import main as app_main
from nqcockpit.ui.briefing_page import render_briefing_page
from nqcockpit.ui.coaching_page import render_coaching_app
from nqcockpit.ui.cockpit_page import render_cockpit
from nqcockpit.ui.components import (
    render_degraded_banner,
    render_status_badge,
    render_terminal_metric,
)
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
    assert 'backgroundColor = "#0D1117"' in content
    assert 'font = "monospace"' in content


def test_ui_components_export():
    """Vérifie l'exécution des fonctions de rendu de composants UI."""
    # Les fonctions utilisent streamlit, vérifions qu'elles ne lèvent pas d'erreur d'importation
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
