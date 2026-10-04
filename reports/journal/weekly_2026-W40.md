# Rapport de Performance Hebdomadaire — 2026-W40

- **Période observée :** du 2026-09-28 au 2026-10-04
- **Généré le :** 2026-10-01 00:49 (fuseau : Africa/Algiers)
- **Seuil de significativité statistique :** 60 trades

---

## 1. Statut de Significativité Statistique

> [!WARNING]
> **Échantillon statistique insuffisant :** 7/60 trades enregistrés.
> Les statistiques et pourcentages ci-dessous sont descriptifs et ne constituent pas une espérance statistiquement robuste.

## 2. Métriques Clés de Performance

| Métrique | Valeur Observée | Intervalle de Confiance (95 %) |
| :--- | :---: | :---: |
| **Nombre de trades** | 7 (Wins: 4, Losses: 3, BE: 0) | Exact |
| **Taux de réussite** | 57.1 % | [25.0 %, 84.2 %] (Wilson) |
| **R cumulé** | +4.5775R | Somme réalisée |
| **R moyen / trade (Espérance)** | +0.6539R (moyen) | Non calculé (n < seuil) |
| **Facteur de profit** | N/A | Gains bruts / Pertes brutes |
| **Drawdown maximum en R** | -0.000R | Équité cumulée |
| **Série de pertes max** | 0 trade(s) | Consécutifs |
| **Taux de conformité aux règles** | 71.4 % | 5/7 conformes |

---

## 3. Discipline & Violations de Règles

⚠️ **3 violation(s) détectée(s)** sur les trades de la période :

| Type de violation | Nombre d'occurrences |
| :--- | :---: |
| `sl_déplacé` | 1 |
| `limite_trades_dépassée` | 1 |
| `rentrée_rapide_après_sl` | 1 |

---

## 4. Comparaison avec la Période Précédente (2026-W39)

| Métrique | Période Précédente (2026-W39) | Période Courante (2026-W40) | Évolution |
| :--- | :---: | :---: | :---: |
| **Trades exécutés** | 2 | 7 | +5 |
| **Taux de réussite** | 50.0 % | 57.1 % | +7.1 pts |
| **R cumulé** | +1.0000R | +4.5775R | +3.5775R |
| **R moyen / trade** | +0.5000R | +0.6539R | +0.1539R |
| **Conformité aux règles** | 0.0 % | 71.4 % | +71.4 pts |

---

## 5. Patterns de Tilt Détectés

⚠️ **3 pattern(s) de tilt détecté(s)** sur les trades de la période :

| Séance | Type de pattern | Constat factuel | Trades impliqués |
| :---: | :--- | :--- | :--- |
| 2026-09-30 | `pertes_consécutives` | 2 pertes consécutives détectées sur la séance. | 2c7fe8f9-ae2f-42fc-a885-d1b235869cc6, fc115f9d-5a5e-4748-b3e2-824cac283671 |
| 2026-09-30 | `surtrading` | Sur-trading : 3 trades enregistrés sur la séance (seuil configuré : 2 trades/jour max). | c2b07c26-3f86-4c27-a784-e7a8fc350adb, 2c7fe8f9-ae2f-42fc-a885-d1b235869cc6, fc115f9d-5a5e-4748-b3e2-824cac283671 |
| 2026-09-30 | `vengeance_trading` | Vengeance trading : nouveau trade pris 7.5 min après une perte (seuil configuré : < 30 min). | 2c7fe8f9-ae2f-42fc-a885-d1b235869cc6, fc115f9d-5a5e-4748-b3e2-824cac283671 |

---

## 6. Détail des Trades de la Période

| Date | Instrument | Direction | Entrée | Sortie | Résultat (R) | Issue | Setup |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| 2026-09-28 | MNQ | LONG | 20850.00 | 20950.00 | +1.99R | WIN | ICT_FVG_retest |
| 2026-09-28 | MNQ | SHORT | 20920.00 | 20960.00 | -1.01R | LOSS | Breakdown_reversal |
| 2026-09-29 | NQ | LONG | 20700.00 | 20780.00 | +1.98R | WIN | VWAP_retest |
| 2026-09-30 | MNQ | LONG | 20850.00 | 20950.00 | +2.00R | WIN | ICT_FVG_retest |
| 2026-09-30 | MNQ | SHORT | 20920.00 | 20975.00 | -1.38R | LOSS | Breakdown_reversal |
| 2026-09-30 | MNQ | LONG | 20970.00 | 20930.00 | -1.00R | LOSS | Revenge_long |
| 2026-10-01 | MNQ | LONG | 20900.00 | 20940.00 | +2.00R | WIN | TEST_INTEGRATION_BREAKOUT |
