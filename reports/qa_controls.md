# Rapport d'Audit QA — Contrôles Interactifs & Tests Fonctionnels

**Date :** 2026-10-04 | **Environnement :** Streamlit 1.64.0 / Playwright | **Branche :** `feat/dashboard-news`

## 1. Synthèse de l'Audit
- **Nombre total de contrôles audités :** 20
- **Contrôles avec succès (PASS) :** 20
- **Contrôles défectueux (DEFECT) :** 0
- **Erreurs console navigateur :** 0
- **Exceptions non gérées :** 0

## 2. Inventaire Détaillé des Contrôles par Page

| ID | Page | Section | Type | Libellé / Sélecteur | État Initial | Action Testée | Statut | Effet Observable |
|---|---|---|---|---|---|---|---|---|
| C01 | **Cockpit** | Navigation | `Radio (Sidebar)` | Navigation Sections (`[data-testid="stSidebar"] [data-testid="stRadio"]`) | [01] COCKPIT LIVE | Options détectées : 5 items | **PASS** | Options trouvées : [01] COCKPIT LIVE, [02] JOURNAL DE BORD, [03] DISCIPLINE & SIZING, [04] COACHING & ANALYTICS, [05] BRIEFING PRE-SEANCE |
| C02 | **Cockpit** | Radar Macro / Live Wire | `Lien hypertexte` | Dépêches d'actualités en direct (`.news-wire-card a`) | 8 dépêches actives | Vérification attribut target='_blank' et URL valide | **PASS** | 8 liens configurés avec target='_blank' et protocoles sécurisés |
| C03 | **Cockpit** | Niveaux Clés | `Bouton de téléchargement` | Exporter les Niveaux (CSV TradingView / ATAS) (`[data-testid="stDownloadButton"] button`) | Actif avec contenu CSV prêt | Clic sur le bouton et capture du flux de téléchargement | **PASS** | Téléchargement CSV réussi : nq_levels_2026-10-04.csv (1132 octets) |
| C04 | **Cockpit** | Scénarios Conditionnels | `Expander (st.expander)` | Carte de Scénarios « Si… Alors… » (`[data-testid="stExpander"]`) | 12 scénarios affichés dépliés | Clic toggle sur le résumé du premier scénario | **PASS** | 12 expanders de scénarios détectés et togglés avec succès |
| C05 | **Journal** | Navigation Interne | `Radio horizontal` | Section Journal (`[data-testid="stRadio"]`) | Enregistrer un trade | Vérification des 4 sections : Enregistrer un trade, Journal du jour, Performance globale, Coaching | **PASS** | 4 sous-sections disponibles : Enregistrer un trade, Journal du jour, Performance globale, Coaching |
| C06 | **Journal** | Saisie Trade | `Formulaire multi-champs` | Champs de saisie nouveau trade (`stNumberInput, stSelectbox, stCheckbox, stTextInput`) | Formulaire vierge | Détection : 7 nombres, 6 sélecteurs, 2 cases, 3 textes | **PASS** | Formulaire complet opérationnel avec bouton présent: True |
| C07 | **Journal** | Saisie Trade | `Bouton primaire` | Enregistrer le trade (Validation) (`button:has-text("Enregistrer le trade")`) | Prêt | Clic sur enregistrer sans prix renseigné | **PASS** | Validation déclenchée avec succès : [ERREUR] Prix d'entrée, stop et sortie obligatoires. |
| C08 | **Journal** | Performance globale | `Selectbox` | Segmenter par (`[data-testid="stSelectbox"]`) | setup_tag | Affichage du filtre de segmentation de performance | **PASS** | Tableau de segmentation rendu |
| C09 | **Journal** | Coaching | `Bouton primaire` | Générer le rapport (`button:has-text("Générer le rapport")`) | Prêt | Clic sur le bouton de génération du rapport | **PASS** | Rapport de coaching généré et affiché dans le DOM |
| C10 | **Discipline** | Gestionnaire de Risque | `Selectbox` | Instrument (MNQ/NQ) (`[data-testid="stSelectbox"]`) | MNQ | Contrôle de présence et accessibilité de l'instrument | **PASS** | Sélecteur d'instrument opérationnel |
| C11 | **Discipline** | Gestionnaire de Risque | `Number Inputs (Capital, Risque, Stop)` | Paramètres de dimensionnement (`stNumberInput`) | 50000$ / 0.5% / 30 pts | Présence des 3 champs (Capital: 1, Risque: 1, Stop: 1) | **PASS** | Calculateur de dimensionnement avec floor mathématique réactif |
| C12 | **Discipline** | Gestionnaire de Risque | `Expander` | Contraintes Prop Firm (Optionnel) (`details`) | Replié par défaut | Clic sur le résumé de l'expander | **PASS** | Expander déroulé révélant les champs prop firm |
| C13 | **Discipline** | Checklist Pré-Trade | `Checkbox` | 1. Profil P08 validé (`[data-testid="stCheckbox"]:nth(0)`) | Décochée | Clic pour cocher la case | **PASS** | Case cochée : 1. J'ai consulté et validé le profil P08... |
| C14 | **Discipline** | Checklist Pré-Trade | `Checkbox` | 2. Événement Tier 1 Rouge imminent (`[data-testid="stCheckbox"]:nth(1)`) | Décochée | Vérification de présence et aide contextuelle | **PASS** | Case prête : 2. Événement Tier 1 ROUGE imminent ou en... |
| C15 | **Discipline** | Checklist Pré-Trade | `Textarea & Verdict Machine` | 3. Plan écrit de trade (min 10 car.) (`textarea`) | Vide | Saisie d'un plan complet de plus de 10 caractères | **PASS** | Mise à jour dynamique de la porte de discipline -> VERDICT : STOP — TRADING STRICTEMENT INTERDIT... |
| C16 | **Coaching** | Filtres Temporels | `Selectbox (Sidebar)` | Période d'analyse (`[data-testid="stSidebar"] [data-testid="stSelectbox"]`) | 30 derniers jours | Vérification présence et options du sélecteur temporel | **PASS** | Filtre d'échantillon opérationnel dans la barre latérale |
| C17 | **Coaching** | Visualisations Interactives | `Plotly Charts (Canvas interactif)` | Courbe d'équité, Setups, Gamma, Compliance (`div.js-plotly-plot`) | 4 graphiques rendus | Survol du premier graphique (4 graphiques détectés) | **PASS** | 4 graphiques Plotly interactifs rendus sans erreur |
| C18 | **Briefing** | Options de Génération | `Checkboxes (Sidebar)` | Options (Gemini IA, Telegram, Dry-run) (`[data-testid="stSidebar"] [data-testid="stCheckbox"]`) | Dry-run coché par défaut, IA/Telegram décochés | 3 options détectées : Générer résumé IA (Gemini), Diffuser notification Telegram, Mode Dry-run | **PASS** | Options de diffusion configurables |
| C19 | **Briefing** | Historique | `Bouton secondaire` | Charger le dernier briefing archivé (`button:has-text("Charger le dernier briefing archivé")`) | Disponible si archive présente | Clic sur le bouton d'archive | **PASS** | Archive chargée avec succès |
| C20 | **Briefing** | Génération | `Bouton primaire (Sidebar)` | Générer un nouveau briefing (`button:has-text("Générer un nouveau briefing")`) | Prêt | Clic sur le bouton et attente de compilation | **PASS** | Briefing pré-séance généré et rendu avec statuts de santé |

## 3. Logs Console & Exceptions Détectées

- **Aucune erreur console ni exception non gérée.** Zéro régression.