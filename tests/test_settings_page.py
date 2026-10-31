"""Tests de la page Réglages : aucun libellé brut ni clé i18n visible."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest


def _settings_script() -> None:
    from nqcockpit.ui.settings_page import render_settings_page

    render_settings_page()


def _visible_text(app: AppTest) -> str:
    parts = [element.value for element in app.markdown]
    parts += [element.value for element in app.caption]
    parts += [element.value for element in app.info]
    parts += [element.value for element in app.warning]
    parts += [button.label for button in app.button]
    parts += [box.label for box in app.selectbox]
    return " ".join(str(part) for part in parts)


@pytest.mark.parametrize("lang", ["EN", "FR"])
def test_settings_page_has_no_raw_i18n_key(lang: str) -> None:
    app = AppTest.from_function(_settings_script, default_timeout=60)
    app.session_state["lang"] = lang
    app.run()

    assert not app.exception, app.exception
    text = _visible_text(app)
    assert "ui." not in text, text
    assert "config ui.language" not in text
