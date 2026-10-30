"""Page Streamlit P12/P13 — Briefing pré-séance consolidé.

Permet la consultation et la génération à la demande du briefing pré-séance,
avec intégration des statuts d'intégrité, avertissements DÉGRADÉ et sorties Gemini/Telegram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.briefing.engine import generate_briefing
from nqcockpit.ui.components import render_degraded_banner, render_status_badge
from nqcockpit.ui.i18n import get_lang, t, tr_text

# GitHub alert directives emitted by the briefing engine: rendered as native
# Streamlit boxes so the raw "[!WARNING]" token never reaches the browser.
_ALERT_DIRECTIVE_RE = re.compile(
    r"^\s*>\s*\[!(WARNING|NOTE|TIP|IMPORTANT|CAUTION)\]\s*$", re.IGNORECASE
)

# "### Scénarios Conditionnels :" / "### Conditional Scenarios:" followed only
# by blank lines: the empty body becomes one muted line instead of blank space.
_SCENARIO_HEADING_RE = re.compile(
    r"(?m)^(?P<heading>###[ \t]+"
    r"(?:Scénarios Conditionnels|Conditional Scenarios)"
    r"[ \t]*:?[ \t]*)\n"
    r"(?:[ \t]*\n)*"
    r"(?=(?:#{1,3}[ \t]|---[ \t]*$|\Z))"
)

_EMPTY_SCENARIO_MESSAGE = {
    "EN": "_No conditional scenarios for this session._",
    "FR": "_Aucun scénario conditionnel pour cette séance._",
}


@dataclass(frozen=True)
class BriefingBlock:
    """One display block: plain Markdown or a GitHub alert kind."""

    kind: str
    text: str


def ensure_empty_scenario_message(markdown: str, lang: str) -> str:
    """Replace an empty conditional-scenarios section with one muted line."""
    message = _EMPTY_SCENARIO_MESSAGE.get(
        "EN" if str(lang).upper() == "EN" else "FR",
        _EMPTY_SCENARIO_MESSAGE["EN"],
    )
    return _SCENARIO_HEADING_RE.sub(
        lambda match: f"{match.group('heading')}\n\n{message}\n\n", markdown
    )


def prepare_briefing_markdown(markdown: str) -> str:
    """Translate at display level, then fill the empty scenarios section."""
    text = tr_text(markdown)
    return ensure_empty_scenario_message(text, get_lang())


def parse_briefing_blocks(markdown: str) -> list[BriefingBlock]:
    """Split rendered text into Markdown runs and alert boxes, in order."""
    blocks: list[BriefingBlock] = []
    buffer: list[str] = []

    def flush_markdown() -> None:
        text = "\n".join(buffer).strip("\n")
        if text.strip():
            blocks.append(BriefingBlock("markdown", text))
        buffer.clear()

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        match = _ALERT_DIRECTIVE_RE.match(lines[index])
        if not match:
            buffer.append(lines[index])
            index += 1
            continue
        flush_markdown()
        kind = match.group(1).upper()
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith(">"):
            body.append(re.sub(r"^\s*>\s?", "", lines[index]).rstrip())
            index += 1
        text = "\n".join(body).strip()
        if text:
            blocks.append(BriefingBlock(kind, text))
    flush_markdown()
    return blocks


def render_briefing_markdown(markdown: str) -> None:
    """Render the briefing with native alert boxes and no raw alert tokens."""
    for block in parse_briefing_blocks(prepare_briefing_markdown(markdown)):
        if block.kind == "markdown":
            st.markdown(block.text)
        elif block.kind == "WARNING":
            st.warning(block.text)
        elif block.kind == "CAUTION":
            st.error(block.text)
        else:  # NOTE / TIP / IMPORTANT
            st.info(block.text)


def render_briefing_page(
    embedded: bool = False, show_title: bool = True
) -> None:
    """Rendu complet de la page Briefing Pré-Séance.

    Args:
        embedded: affiche les contrôles de génération dans la page (et non la
            barre latérale), pour l'intégration dans l'expander « Réglages ».
        show_title: affiche le titre de page (désactivé en mode intégré).
    """
    try:
        st.set_page_config(
            page_title=t(
                "NQ Cockpit · Briefing Pré-Séance",
                "NQ Cockpit · Pre-Session Briefing",
            ),
            layout="wide",
        )
    except StreamlitAPIException:
        pass

    if show_title:
        st.title(
            t(
                "BRIEFING PRÉ-SÉANCE CONSOLIDÉ",
                "CONSOLIDATED PRE-SESSION BRIEFING",
            )
        )
        st.caption(
            t(
                "Données agrégées sans prédiction ni biais directionnel — P02-P08 + P12",
                "Aggregated data with zero prediction or directional bias — P02-P08 + P12",
            )
        )

    # ---------------------------------------------------------------------------
    # Options de génération (barre latérale par défaut, page en mode intégré)
    # ---------------------------------------------------------------------------
    controls = st if embedded else st.sidebar
    if not embedded:
        controls.title(t("[05] BRIEFING PRE-SEANCE", "[05] PRE-SESSION BRIEFING"))
    controls.markdown(
        t("### GÉNÉRATION DU BRIEFING", "### BRIEFING GENERATION")
    )
    use_gemini = controls.checkbox(
        t("Générer résumé IA (Gemini)", "Generate AI Summary (Gemini)"),
        value=False,
    )
    use_telegram = controls.checkbox(
        t(
            "Diffuser notification Telegram",
            "Broadcast Telegram Notification",
        ),
        value=False,
    )
    dry_run = controls.checkbox(
        t("Mode Dry-run", "Dry-run Mode"), value=True
    )

    briefing_dir = Path("reports/briefings")
    briefing_files = list(briefing_dir.glob("briefing_*.md")) if briefing_dir.exists() else []
    briefing_files.sort(reverse=True)

    if controls.button(
        t("Générer un nouveau briefing", "Generate New Briefing"),
        type="primary",
    ):
        with st.spinner(
            t(
                "Génération du briefing en cours...",
                "Generating pre-session briefing...",
            )
        ):
            briefing = generate_briefing(
                use_gemini=use_gemini,
                use_telegram=use_telegram,
                dry_run=dry_run,
            )
            st.session_state["current_briefing"] = briefing
            st.success(
                t(
                    "Briefing généré avec succès !",
                    "Briefing generated successfully!",
                )
            )

    # Sélection ou récupération du briefing actif
    briefing = st.session_state.get("current_briefing")

    if not briefing and briefing_files:
        st.info(
            t(
                f"Dernier briefing archivé détecté : `{briefing_files[0].name}`",
                f"Latest archived briefing detected: `{briefing_files[0].name}`",
            )
        )
        if st.button(
            t(
                "Charger le dernier briefing archivé",
                "Load Latest Archived Briefing",
            )
        ):
            content = briefing_files[0].read_text(encoding="utf-8")
            render_briefing_markdown(content)
            return

    if not briefing:
        st.warning(
            t(
                "Aucun briefing généré dans cette session. "
                "Cliquez sur « Générer un nouveau briefing » ci-dessus.",
                "No briefing generated in this session. "
                "Click 'Generate New Briefing' above.",
            )
        )
        return

    # ---------------------------------------------------------------------------
    # Affichage du statut & avertissements
    # ---------------------------------------------------------------------------
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"**{t('Séance NY', 'NY Session')}** : `{briefing.session_date_ny}`"
        )
    with col2:
        ts_lbl = t("Horodatage (Alger)", "Timestamp (Algiers)")
        st.markdown(f"**{ts_lbl}** : `{briefing.timestamp_algiers_str}`")
    with col3:
        render_status_badge(
            briefing.status, t("Intégrité Sources", "Source Integrity")
        )

    if briefing.status_warnings:
        render_degraded_banner(briefing.status_warnings)

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Affichage du Markdown complet
    # ---------------------------------------------------------------------------
    render_briefing_markdown(briefing.markdown_briefing)

    if briefing.output_path:
        st.caption(
            f"{t('Fichier exporté', 'Exported file')} : `{briefing.output_path}`"
        )


if __name__ == "__main__":
    render_briefing_page()
