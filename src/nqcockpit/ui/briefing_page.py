"""Page Streamlit P12/P13 — Briefing pré-séance consolidé.

Permet la consultation et la génération à la demande du briefing pré-séance,
avec intégration des statuts d'intégrité, avertissements DÉGRADÉ et sorties Gemini/Telegram.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from nqcockpit.briefing.engine import generate_briefing
from nqcockpit.ui.components import render_degraded_banner, render_status_badge


def render_briefing_page() -> None:
    """Rendu complet de la page Briefing Pré-Séance."""
    try:
        st.set_page_config(
            page_title="NQ Cockpit · Briefing Pré-Séance",
            page_icon="📄",
            layout="wide",
        )
    except Exception:
        pass

    st.title("📄 Briefing Pré-Séance Consolidé")
    st.caption("Données agrégées sans prédiction ni biais directionnel — P02-P08 + P12")

    # ---------------------------------------------------------------------------
    # Sidebar / Options de génération
    # ---------------------------------------------------------------------------
    st.sidebar.markdown("### ⚙️ Génération du Briefing")
    use_gemini = st.sidebar.checkbox("Générer résumé IA (Gemini)", value=False)
    use_telegram = st.sidebar.checkbox("Diffuser notification Telegram", value=False)
    dry_run = st.sidebar.checkbox("Mode Dry-run", value=True)

    briefing_dir = Path("reports/briefings")
    briefing_files = list(briefing_dir.glob("briefing_*.md")) if briefing_dir.exists() else []
    briefing_files.sort(reverse=True)

    if st.sidebar.button("🔄 Générer un nouveau briefing", type="primary"):
        with st.spinner("Génération du briefing en cours..."):
            briefing = generate_briefing(
                use_gemini=use_gemini,
                use_telegram=use_telegram,
                dry_run=dry_run,
            )
            st.session_state["current_briefing"] = briefing
            st.success("Briefing généré avec succès !")

    # Sélection ou récupération du briefing actif
    briefing = st.session_state.get("current_briefing")

    if not briefing and briefing_files:
        st.info(f"Dernier briefing archivé détecté : `{briefing_files[0].name}`")
        if st.button("📖 Charger le dernier briefing archivé"):
            content = briefing_files[0].read_text(encoding="utf-8")
            st.markdown(content)
            return

    if not briefing:
        st.warning(
            "Aucun briefing généré dans cette session. "
            "Cliquez sur « Générer un nouveau briefing » dans la barre latérale."
        )
        return

    # ---------------------------------------------------------------------------
    # Affichage du statut & avertissements
    # ---------------------------------------------------------------------------
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"**Séance NY** : `{briefing.session_date_ny}`")
    with col2:
        st.markdown(f"**Horodatage (Alger)** : `{briefing.timestamp_algiers_str}`")
    with col3:
        render_status_badge(briefing.status, "Intégrité Sources")

    if briefing.status_warnings:
        render_degraded_banner(briefing.status_warnings)

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Affichage du Markdown complet
    # ---------------------------------------------------------------------------
    st.markdown(briefing.markdown_briefing)

    if briefing.output_path:
        st.caption(f"Fichier exporté : `{briefing.output_path}`")


if __name__ == "__main__":
    render_briefing_page()
