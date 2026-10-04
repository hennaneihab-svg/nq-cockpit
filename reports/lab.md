# Laboratoire de Validation Empirique — NQ Cockpit (P14)

**Date d'évaluation :** 2026-10-04 20:36:16 UTC  
**Registre d'hypothèses :** `hypotheses.yaml` (v1.0.0, créé le 2026-10-04T20:00:00Z)  
**Empreinte cryptographique registre (SHA-256) :** `b45f81e23f2448f8d42aeff1aed10547ff62adacd3b3f14080e8f1d0c8dd993a`  
**Politique méthodologique :** Aucune conclusion permise sous 60 séances ou 12 événements. Ajustement FWER de Holm-Bonferroni. Aucun biais directionnel.

---

## 1. Synthèse de Validation des Hypothèses Figées

| ID | Hypothèse | n | Statut | p-value brute | p-value Holm | Taille d'effet | IC 95% |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **H1** | Régime Gamma Négatif et Amplitude de Séance | 0 | **ÉCHANTILLON INSUFFISANT** | — | — | — | — |
| **H2** | Position Relative au Gamma Flip et Compression de Volatilité | 0 | **ÉCHANTILLON INSUFFISANT** | — | — | — | — |
| **H3** | Expansion d'Amplitude lors des Sessions à Événements Tier 1 | 0 | **ÉCHANTILLON INSUFFISANT** | — | — | — | — |
| **H4** | Réaction Mesurable aux Niveaux Structuraux Majeurs (Murs Gamma) | 0 | **ÉCHANTILLON INSUFFISANT** | — | — | — | — |

---

## 2. Détail par Hypothèse & Justification

### Hypothèse H1 : Régime Gamma Négatif et Amplitude de Séance
- **Énoncé théorique :** En régime de Gamma Négatif (Net GEX < 0), la couverture des teneurs de marché étant déstabilisatrice (vendre en baisse, acheter en hausse), l'amplitude réalisée de la séance (High - Low) et la consommation de l'Expected Move journalier sont statistiquement supérieures à celles observées en Gamma Positif.
- **Direction attendue :** `RANGE_NEGATIVE_GAMMA > RANGE_POSITIVE_GAMMA`
- **Biais directionnel :** `NONE`
- **Échantillon collecté :** n = 0 séances / occurrences.
- **Détails métriques :** Échantillon insuffisant : 0 séances observées (requis >= 60). Interdiction de conclure.

### Hypothèse H2 : Position Relative au Gamma Flip et Compression de Volatilité
- **Énoncé théorique :** Lorsque le cours du NQ évolue durablement au-dessus du Gamma Flip de séance, l'action de marché bénéficie d'un amortissement de volatilité (Mean Reversion), induisant une amplitude de volatilité intra-journalière plus faible que lorsque le cours navigue sous le niveau de Flip.
- **Direction attendue :** `RANGE_ABOVE_FLIP < RANGE_BELOW_FLIP`
- **Biais directionnel :** `NONE`
- **Échantillon collecté :** n = 0 séances / occurrences.
- **Détails métriques :** Échantillon insuffisant : 0 séances observées (requis >= 60). Interdiction de conclure.

### Hypothèse H3 : Expansion d'Amplitude lors des Sessions à Événements Tier 1
- **Énoncé théorique :** Les séances comportant un événement macroéconomique majeur de Tier 1 (CPI, NFP, décision de taux FOMC) présentent une amplitude réalisée significativement plus large que les séances sans publication de niveau Tier 1.
- **Direction attendue :** `RANGE_TIER1_SESSIONS > RANGE_NON_TIER1_SESSIONS`
- **Biais directionnel :** `NONE`
- **Échantillon collecté :** n = 0 séances / occurrences.
- **Détails métriques :** Échantillon insuffisant : 0 événements Tier 1 observés (requis >= 12) sur 0 séances (requis >= 60). Interdiction de conclure.

### Hypothèse H4 : Réaction Mesurable aux Niveaux Structuraux Majeurs (Murs Gamma)
- **Énoncé théorique :** Lorsqu'un niveau structural majeur (Call Wall, Put Support, Expected Move ±1σ) est testé (tolérance ±5 points NQ), la probabilité d'un retournement (rejet) ou d'une expansion directionnelle rapide dans une fenêtre de N minutes (N=15, 30) est statistiquement différente d'une marche aléatoire brownienne sans mémoire.
- **Direction attendue :** `P_REACTION != P_RANDOM_WALK`
- **Biais directionnel :** `NONE`
- **Échantillon collecté :** n = 0 séances / occurrences.
- **Détails métriques :** Échantillon insuffisant : 0 tests de niveaux observés (requis >= 60). Interdiction de conclure.

---

## 3. Règles d'Éthique & Non-Surapprentissage

- **Gel des hypothèses :** Les 4 hypothèses ci-dessus ont été définies a priori. Tout ajout futur doit figurer dans le registre avec horodatage certifié avant injection de nouvelles données.
- **Contrôle FWER :** L'ajustement séquentiel de Holm-Bonferroni évite l'inflation de l'erreur de type I lors des tests simultanés.
- **Refus de sur-interprétation :** Tant que le seuil de 60 séances n'est pas atteint dans les données locales archivées, le statut demeure irrévocablement `ÉCHANTILLON INSUFFISANT`.
