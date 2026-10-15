"""Page Streamlit P12/P13 — Briefing pré-séance consolidé.

Permet la consultation et la génération à la demande du briefing pré-séance,
avec intégration des statuts d'intégrité, avertissements DÉGRADÉ et sorties Gemini/Telegram.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.briefing.engine import generate_briefing
from nqcockpit.ui.components import render_degraded_banner, render_status_badge
from nqcockpit.ui.i18n import t, tr_text


def render_briefing_page() -> None:
    """Rendu complet de la page Briefing Pré-Séance."""
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
    # Sidebar / Options de génération
    # ---------------------------------------------------------------------------
    st.sidebar.title(
        t("[05] BRIEFING PRE-SEANCE", "[05] PRE-SESSION BRIEFING")
    )
    st.sidebar.markdown(
        t("### GÉNÉRATION DU BRIEFING", "### BRIEFING GENERATION")
    )
    use_gemini = st.sidebar.checkbox(
        t("Générer résumé IA (Gemini)", "Generate AI Summary (Gemini)"),
        value=False,
    )
    use_telegram = st.sidebar.checkbox(
        t(
            "Diffuser notification Telegram",
            "Broadcast Telegram Notification",
        ),
        value=False,
    )
    dry_run = st.sidebar.checkbox(
        t("Mode Dry-run", "Dry-run Mode"), value=True
    )

    briefing_dir = Path("reports/briefings")
    briefing_files = list(briefing_dir.glob("briefing_*.md")) if briefing_dir.exists() else []
    briefing_files.sort(reverse=True)

    if st.sidebar.button(
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
            st.markdown(tr_text(content))
            return

    if not briefing:
        st.warning(
            t(
                "Aucun briefing généré dans cette session. "
                "Cliquez sur « Générer un nouveau briefing » dans la barre latérale.",
                "No briefing generated in this session. "
                "Click 'Generate New Briefing' in the sidebar.",
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
    st.markdown(tr_text(briefing.markdown_briefing))

    if briefing.output_path:
        st.caption(
            f"{t('Fichier exporté', 'Exported file')} : `{briefing.output_path}`"
        )


if __name__ == "__main__":
    render_briefing_page()
