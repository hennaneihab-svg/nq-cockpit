"""Compact horizontal navigation for the NQ Cockpit terminal layout.

Four destinations share one top bar: Terminal, Journal & Discipline, Coaching
and Settings. The page list and localized names live here so tests can assert
the English and French versions without rendering Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from nqcockpit.ui.i18n import label

NAV_STATE_KEY = "nav_page"

# Compact top navigation: one row, no sidebar block, neutral selected state.
# Colour is reserved for data status, so the active tab only gets a border.
TOP_NAV_CSS = """
<style>
div[data-testid="stRadio"] > div[role="radiogroup"] {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
    margin: 0;
}
div[data-testid="stRadio"] > div[role="radiogroup"] label {
    background: transparent;
    border: 1px solid #1F2937;
    border-radius: 6px;
    padding: 3px 12px;
    margin: 0;
    font-size: 0.84rem;
    color: #CBD5E1;
    cursor: pointer;
}
div[data-testid="stRadio"] > div[role="radiogroup"] label p {
    font-size: 0.84rem;
    margin: 0;
}
div[data-testid="stRadio"] > div[role="radiogroup"] label:has(input:checked) {
    background: #111827;
    border-color: #64748B;
    color: #F8FAFC;
    font-weight: 700;
}
div[data-testid="stRadio"] > div[role="radiogroup"] label > div:first-child {
    display: none;
}
.topnav-brand {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #F8FAFC;
    white-space: nowrap;
    padding-top: 6px;
}
.topnav-brand span {
    color: #64748B;
    font-weight: 600;
    font-size: 0.72rem;
    margin-left: 6px;
}
</style>
"""

# Kept as an alias so older imports keep working; the sidebar block is gone.
NAV_CSS = TOP_NAV_CSS


@dataclass(frozen=True)
class PageSpec:
    """One destination: stable key + i18n keys for name and description."""

    key: str
    name_key: str
    desc_key: str


PAGES: tuple[PageSpec, ...] = (
    PageSpec("terminal", "ui.nav.terminal.name", "ui.nav.terminal.desc"),
    PageSpec("journal", "ui.nav.journal.name", "ui.nav.journal.desc"),
    PageSpec("coaching", "ui.nav.coaching.name", "ui.nav.coaching.desc"),
    PageSpec("settings", "ui.nav.settings.name", "ui.nav.settings.desc"),
)

DEFAULT_PAGE = "terminal"

# Query-parameter and legacy section aliases keep old links working. The old
# Levels, Macro and Briefing destinations are now panels of the Terminal page.
_PAGE_ALIASES: dict[str, str] = {
    "": DEFAULT_PAGE,
    "1": "terminal",
    "today": "terminal",
    "terminal": "terminal",
    "cockpit": "terminal",
    "levels": "terminal",
    "levels_chart": "terminal",
    "chart": "terminal",
    "macro": "terminal",
    "macro_news": "terminal",
    "news": "terminal",
    "briefing": "terminal",
    "2": "journal",
    "journal": "journal",
    "journal_discipline": "journal",
    "3": "journal",
    "discipline": "journal",
    "4": "coaching",
    "coaching": "coaching",
    "5": "settings",
    "settings": "settings",
}


def page_keys() -> list[str]:
    """Stable keys in top-navigation display order."""
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
    """Current page: explicit navigation first, then query parameter, then Terminal."""
    stored = st.session_state.get(NAV_STATE_KEY)
    if stored:
        return get_page_spec(str(stored)).key
    return resolve_page(query_value)


def render_top_nav(active_key: str) -> str:
    """Compact horizontal navigation: one widget, four destinations."""
    st.markdown(TOP_NAV_CSS, unsafe_allow_html=True)
    if NAV_STATE_KEY not in st.session_state:
        st.session_state[NAV_STATE_KEY] = get_page_spec(active_key).key
    choice = st.radio(
        label("ui.nav.title"),
        options=page_keys(),
        format_func=page_name,
        key=NAV_STATE_KEY,
        horizontal=True,
        label_visibility="collapsed",
    )
    return get_page_spec(str(choice)).key


__all__ = [
    "DEFAULT_PAGE",
    "NAV_CSS",
    "NAV_STATE_KEY",
    "PAGES",
    "TOP_NAV_CSS",
    "PageSpec",
    "active_page",
    "get_page_spec",
    "page_description",
    "page_keys",
    "page_name",
    "render_top_nav",
    "resolve_page",
    "set_page",
]
