"""Plain-language navigation for the NQ Cockpit.

Six destinations, each with a one-line description shown under its button in
the sidebar. The page list and descriptions live here so tests can assert the
English and French versions without rendering Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from nqcockpit.ui.i18n import label

NAV_STATE_KEY = "nav_page"


@dataclass(frozen=True)
class PageSpec:
    """One sidebar destination: stable key + i18n keys for name and description."""

    key: str
    name_key: str
    desc_key: str


PAGES: tuple[PageSpec, ...] = (
    PageSpec("today", "ui.nav.today.name", "ui.nav.today.desc"),
    PageSpec("levels", "ui.nav.levels.name", "ui.nav.levels.desc"),
    PageSpec("macro", "ui.nav.macro.name", "ui.nav.macro.desc"),
    PageSpec("journal", "ui.nav.journal.name", "ui.nav.journal.desc"),
    PageSpec("coaching", "ui.nav.coaching.name", "ui.nav.coaching.desc"),
    PageSpec("settings", "ui.nav.settings.name", "ui.nav.settings.desc"),
)

DEFAULT_PAGE = "today"

# Query-parameter and legacy section aliases keep old links working.
_PAGE_ALIASES: dict[str, str] = {
    "": DEFAULT_PAGE,
    "1": "today",
    "today": "today",
    "cockpit": "today",
    "2": "journal",
    "journal": "journal",
    "journal_discipline": "journal",
    "3": "journal",
    "discipline": "journal",
    "4": "coaching",
    "coaching": "coaching",
    "5": "settings",
    "briefing": "settings",
    "levels": "levels",
    "levels_chart": "levels",
    "chart": "levels",
    "macro": "macro",
    "macro_news": "macro",
    "news": "macro",
    "settings": "settings",
}


def page_keys() -> list[str]:
    """Stable keys in sidebar display order."""
    return [spec.key for spec in PAGES]


def get_page_spec(key: str) -> PageSpec:
    """Return the spec for a key, falling back to the default page."""
    for spec in PAGES:
        if spec.key == key:
            return spec
    return PAGES[0]


def resolve_page(raw: str | None) -> str:
    """Map a query-param value or legacy section number to a page key."""
    value = str(raw or "").strip().lower()
    return _PAGE_ALIASES.get(value, DEFAULT_PAGE)


def page_name(key: str) -> str:
    """Localised plain name for a page key."""
    return label(get_page_spec(key).name_key)


def page_description(key: str) -> str:
    """Localised one-line description for a page key."""
    return label(get_page_spec(key).desc_key)


def set_page(key: str) -> None:
    """Store the active page for the next Streamlit run."""
    st.session_state[NAV_STATE_KEY] = get_page_spec(key).key


def active_page(query_value: str | None) -> str:
    """Current page: explicit navigation first, then query parameter, then Today."""
    stored = st.session_state.get(NAV_STATE_KEY)
    if stored:
        return get_page_spec(str(stored)).key
    return resolve_page(query_value)


def render_sidebar_nav(active_key: str) -> str:
    """Six clearly clickable buttons, each with its description underneath."""
    st.sidebar.markdown(
        f'<div class="nav-title">{label("ui.nav.title")}</div>',
        unsafe_allow_html=True,
    )
    for spec in PAGES:
        is_active = spec.key == active_key
        name = label(spec.name_key)
        clicked = st.sidebar.button(
            f"{name}  ›",
            key=f"nav_{spec.key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        )
        st.sidebar.caption(label(spec.desc_key))
        if clicked and not is_active:
            set_page(spec.key)
            st.rerun()
    return active_key


__all__ = [
    "DEFAULT_PAGE",
    "NAV_STATE_KEY",
    "PAGES",
    "PageSpec",
    "active_page",
    "get_page_spec",
    "page_description",
    "page_keys",
    "page_name",
    "render_sidebar_nav",
    "resolve_page",
    "set_page",
]
