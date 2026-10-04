# Audit de Conception UI & Vérification des États d'Interface — Playwright

**Date :** 4 octobre 2026  
**Outil :** Microsoft Edge 154 (Playwright Headless, viewport 1600×1200)  
**Cible :** Interface Streamlit unifiée NQ Cockpit (port local 8509)  

---

## 1. Synthèse de l'Audit d'Interaction

L'évaluation automatisée a testé les états interactifs, les composants d'action, les états vides et les indicateurs d'état dégradé sur l'ensemble des 5 vues :

| Page | Composants testés | États vérifiés | Résultat |
|---|---|---|:---:|
| **[01] Cockpit Live** | Bouton de téléchargement CSV, Expanders « Si... Alors... », Wire d'actualités | Survol du bouton CSV, toggle interactif du premier expander, affichage des flux d'actualités | **CONFORME** |
| **[02] Journal de Bord** | Champs de saisie numérique, sélecteurs déroulants, bouton de soumission `Enregistrer le trade` | Survol du bouton d'action, réactivité du formulaire sans rechargement intempestif | **CONFORME** |
| **[03] Discipline & Sizing** | Cases à cocher (Checklist), sélecteur d'instrument (NQ / MNQ), champs de capital et stop | Survol des checkboxes, affichage dynamique de l'avertissement de budget insuffisant | **CONFORME** |
| **[04] Coaching & Analytics** | 4 graphiques interactifs Plotly (Equity curve, segmentations, distribution) | Rendu des canvas SVG/WebGL interactifs, survol des points de données sans latence ni crash JS | **CONFORME** |
| **[05] Briefing Pré-séance** | Bouton `Générer un nouveau briefing`, cases d'options de diffusion | Clic sur le déclencheur de génération, bascule de l'état vide vers l'état synthétisé | **CONFORME** |

---

## 2. Vérification des États Particuliers

### A. États Dégradés (Règle d'Honnêteté des Données)
- **Cockpit Live :**
  - Affichage visible des badges de dégradation sur les sources non rafraîchies :
    - `Niveaux Gamma & Options NDX (P04) : DÉGRADÉ` (encadré bordure orange avec libellé explicite)
    - `Contexte Macro & Cross-Asset (P07) : DÉGRADÉ`
    - `Overnight NQ CME (P07) : DÉGRADÉ`
  - Aucun masquage ni simulation de valeurs fausses.
- **Journal de Bord :**
  - Si aucune capture d'écran n'est liée à un trade, le système n'affiche aucun conteneur d'image cassée et reste propre.

### B. États Vides (Empty States)
- **Briefing Pré-séance :**
  - À l'ouverture sans briefing en session : bandeau d'information explicite `Aucun briefing généré dans cette session. Cliquez sur « Générer un nouveau briefing » dans la barre latérale.`
- **Coaching & Analytics :**
  - Quand le nombre de séances est inférieur au seuil réglementaire de 60 séances :
    - Bandeau d'alerte méthodologique visible : `Échantillon insuffisant : 11 / 60 trades requis pour la validité statistique. Les métriques ci-dessous sont purement descriptives et n'ont pas de significativité statistique confirmée.`
    - Espérance et Profit Factor remplacés par un tiret `—` avec sous-titre `Non significatif`.
    - Les tags de configurations affichent explicitement `(n < seuil)`.

### C. Contrastes et Accessibilité
- **Fond sombre mat :** Slate-950 (`#020617`), évitant toute fatigue visuelle sur longues sessions.
- **Cartes :** Slate-900 (`#0F172A`) avec bordure délimitante Slate-800 (`rgba(51, 65, 85, 0.6)`).
- **Texte :** Gris clair Slate-50 (`#F8FAFC`) pour une lisibilité supérieure à 12:1 sur fond sombre (dépasse largement les normes WCAG AAA 7:1).
- **Zéro information portée par la seule couleur :** Chaque statut vert/rouge est obligatoirement accompagné d'un texte d'état en toutes lettres (`[OK]`, `[DÉGRADÉ]`, `[BLOQUÉ]`, `[NO-TRADE]`, `AUTORISÉ`, `VERROUILLÉ`).
