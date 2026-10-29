"""Settings page — language, data locations and the pre-session briefing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from nqcockpit.config import find_config_path, load_config
from nqcockpit.ui import sections
from nqcockpit.ui.briefing_page import render_briefing_page
from nqcockpit.ui.components import badge_html
from nqcockpit.ui.i18n import get_lang, label, set_lang

_LANGUAGES = (("EN", "English"), ("FR", "Français"))


def render_settings_page() -> None:
    """Render the Settings page; all values come from config.yaml."""
    config = load_config()
    sections.inject_ui_css()
    sections.render_page_heading("ui.settings.title", "ui.settings.desc")

    # --- Language ---------------------------------------------------------
    st.markdown(
        f'<div class="section-title">{label("ui.settings.language")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(label("ui.settings.language_help"))
    language_cols = st.columns(len(_LANGUAGES))
    active_lang = get_lang()
    for column, (code, name) in zip(language_cols, _LANGUAGES, strict=False):
        with column:
            st.button(
                name,
                key=f"settings_lang_{code}",
                use_container_width=True,
                type="primary" if code == active_lang else "secondary",
                on_click=set_lang,
                args=(code,),
            )

    # --- Data & storage ---------------------------------------------------
    st.markdown(
        f'<div class="section-title">{label("ui.settings.data")}</div>',
        unsafe_allow_html=True,
    )
    db_path = Path(config.data.db_path)
    try:
        config_path = find_config_path()
    except Exception:  # noqa: BLE001 - settings must still render
        config_path = Path("config.yaml")
    db_status = (
        f"{badge_html('OK')} {db_path}"
        if db_path.exists()
        else f"{badge_html('NO_DATA')} {db_path}"
    )
    st.markdown(
        f"""
        <div class="card">
            <div class="levels-table">
                <table class="levels-table">
                    <tbody>
                        <tr><td>{label("ui.settings.db_path")}</td>
                            <td>{db_status}</td></tr>
                        <tr><td>{label("ui.settings.config_path")}</td>
                            <td>{config_path}</td></tr>
                        <tr><td>{label("ui.settings.display_tz")}</td>
                            <td>{config.timezones.display}</td></tr>
                        <tr><td>{label("ui.settings.market_tz")}</td>
                            <td>{config.timezones.market}</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    windows = ", ".join(
        f"{window.name} {window.start}–{window.end}"
        for window in config.trading_windows_algiers
    )
    snapshots = ", ".join(config.snapshots_algiers)
    st.markdown(
        f"""
        <div class="card">
            <div class="levels-table">
                <table class="levels-table">
                    <tbody>
                        <tr><td>{label("ui.settings.windows")}</td>
                            <td>{windows}</td></tr>
                        <tr><td>{label("ui.settings.snapshots")}</td>
                            <td>{snapshots}</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Pre-session briefing (existing page, embedded) -------------------
    with st.expander(label("ui.settings.briefing"), expanded=False):
        st.caption(label("ui.settings.briefing_note"))
        render_briefing_page(embedded=True, show_title=False)

    # --- About ------------------------------------------------------------
    st.markdown(
        f'<div class="section-title">{label("ui.settings.about")}</div>'
        f'<div class="page-desc">{label("ui.settings.disclaimer")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")


if __name__ == "__main__":
    render_settings_page()
