"""Journal & Discipline page — two existing pages, one destination."""

from __future__ import annotations

import streamlit as st

from nqcockpit.ui import sections
from nqcockpit.ui.discipline_page import render_discipline_page
from nqcockpit.ui.i18n import label
from nqcockpit.ui.journal_page import render_journal_page


def render_journal_discipline_page() -> None:
    """Group the existing journal and discipline pages behind two tabs."""
    sections.inject_ui_css()
    sections.render_page_heading("ui.journal.title", "ui.journal.desc")
    tabs = st.tabs(
        [
            label("ui.journal.tab_journal"),
            label("ui.journal.tab_discipline"),
        ]
    )
    with tabs[0]:
        render_journal_page()
    with tabs[1]:
        render_discipline_page()


if __name__ == "__main__":
    render_journal_discipline_page()
