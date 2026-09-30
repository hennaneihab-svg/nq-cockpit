# P07 · Contexte Macro & Prévisions d'Amplitude

## 1. Synthèse Exécutive
- **Statut global :** Implémenté, vérifié (155/155 tests unitaires & intégration OK, ruff 0 défaut).
- **Principe non-directionnel :** Respecté. COT CFTC identifié comme contexte de positionnement sans signal.
- **Règle stricte de calibration :** Aucun ajustement empirique sous 60 séances ($n < 60$). Statut affiché explicitement : `non calibré`. Facteur d'ajustement : `null`.
- **Intervalles de confiance :** Score de Wilson à 95 % calculé sur définitions de séances figées dans `config.yaml`.
- **Suivi 1-sigma :** Table `forecasts` alimentée, rapport `reports/calibration.md` généré.

---

## 2. Définitions Figées (`config.yaml`)
```yaml
macro:
  history_days: 252
  cache_ttl_seconds: 300
  cot:
    contract_name: "NASDAQ-100 CONSOLIDATED - CHICAGO MERCANTILE EXCHANGE"
    fallback_static_path: "data/cftc_cot_static.json"
forecast:
  min_sessions_for_calibration: 60
  confidence_level: 0.95
  day_types:
    range:
      max_range_em_ratio: 0.85
      description: "range <= 0.85 * expected move"
    trend:
      min_body_range_ratio: 0.60
      description: "|clôture - ouverture| / range >= 0.60"
    volatile:
      min_range_em_ratio: 1.15
      description: "range >= 1.15 * expected move"
```

---

## 3. Sorties Brutes d'Exécution

### A. Commande `nqcockpit macro`
```text
CFTC COT live fetch failed (HTTP Error 404: Not Found) -> repli sur relevé statique

===========================================================================
  NQ COCKPIT — CONTEXTE MACROÉCONOMIQUE & CROSS-ASSET (P07)
  Horodatage : 2026-09-30 14:42 ET | 2026-09-30 19:42 Alger
  Statut     : DÉGRADÉ
  Détail     : Sources dégradées : COT CFTC
===========================================================================
  TAUX & VOLATILITÉ (percentiles 1 an = 252 séances, variation 5 jours)
---------------------------------------------------------------------------
  Métrique   Niveau       Percentile 1 an    Var. 5j         Source / Statut
  -------- ---------- ---------------- ------------- --------------------
  US 10Y     5.24 %       100.0 %            +0.28 (+5.7%)   [OK] FRED (DGS10)
  US 2Y      4.92 %       100.0 %            +0.16 (+3.4%)   [OK] FRED (DGS2)
  DXY        101.45       98.8 %             +0.35 (+0.3%)   [OK] Yahoo (DX-Y.NYB)
  VIX        15.94        25.8 %             +0.76 (+5.0%)   [OK] Yahoo (^VIX)
  VXN        22.21        36.5 %             +1.45 (+7.0%)   [OK] Yahoo (^VXN)
---------------------------------------------------------------------------
  OVERNIGHT NQ (session CME 18:00 - 09:30 ET)
  Range de la nuit : 267.2 pts (H: 30779.5 | L: 30512.25)
  Gap vs veille    : N/A (Clôture veille: N/A | Dernier: 30699.25)
  Statut overnight : [OK] NQ=F CME (18:00 - 09:30 ET)
---------------------------------------------------------------------------
  POSITIONNEMENT COT (CFTC — CONTEXTE SEULEMENT, AUCUN SIGNAL)
  Contrat          : NASDAQ-100 CONSOLIDATED - CHICAGO MERCANTILE EXCHANGE
  Date du relevé   : 2026-09-22 (mardi de relevé)
  Position nette   : 6,120 contrats (Spéculateurs non-commerciaux)
  Variation 1 sem. : +1,250 contrats | Percentile 1 an : 58.4 %
  Statut COT       : [DÉGRADÉ: réseau CFTC inaccessible, relevé statique versionné] CFTC (statique versionné)
  NOTE             : contexte de positionnement, pas un signal directionnel
===========================================================================
```

### B. Commande `nqcockpit amplitude`
```text
===========================================================================
  NQ COCKPIT — PRÉVISIONS D'AMPLITUDE & CALIBRATION (P07)
  Horodatage       : 2026-09-30 14:42 ET | 2026-09-30 19:42 Alger
  Séance cible     : 2026-09-30
  Statut           : OK
===========================================================================
  PRÉVISION D'AMPLITUDE DU JOUR
---------------------------------------------------------------------------
  Spot NQ                  : 30548.51
  Expected Move de base    : 81.53 pts
  Source de base           : ACT/365 CBOE NDX Options (P04-fix6)
  Ajustement empirique     : aucun (non prouvé — échantillon insuffisant)
  Amplitude projetée (EM)  : 81.53 pts
  Bornes projetées (±EM/2) : [30507.75  —  30589.28]
---------------------------------------------------------------------------
  ÉTAT DE CALIBRATION (séparé de l'amplitude)
---------------------------------------------------------------------------
  État de calibration      : [NON CALIBRÉ]
  Justification            : échantillon insuffisant (n=7 < 60 séances requises)
  Règle stricte            : Aucun ajustement empirique sous 60 séances complètes.
---------------------------------------------------------------------------
  PROBABILITÉS EMPIRIQUES DU TYPE DE JOURNÉE (Intervalles de Wilson à 95 %)
---------------------------------------------------------------------------
  Type       Observé    IC Wilson 95 %       Définition figée (config)
  -------- -------- ------------------ -----------------------------------
  range      14.3 %     [2.6% - 51.3%]       range <= 0.85 * expected move (config) (échantillon insuffisant (n=7 < 60))
  trend      28.6 %     [8.2% - 64.1%]       |clôture - ouverture| / range >= 0.60 (config) (échantillon insuffisant (n=7 < 60))
  volatile   57.1 %     [25.0% - 84.2%]      range >= 1.15 * expected move (config) (échantillon insuffisant (n=7 < 60))
---------------------------------------------------------------------------
  SUIVI DE CALIBRATION 1-SIGMA (historique forecasts)
  Séances archivées        : 0 (couvertes : 0)
  Couverture observée      : 0.0 % (attendu théorique : 68.3 %)
  Écart à la cible         : -68.3 %
  Brier score              : N/A
  Rapport généré           : reports/calibration.md
===========================================================================
```

### C. Commande `nqcockpit amplitude --json`
```json
{
  "as_of_utc": "2026-09-30T18:42:56.681406+00:00",
  "target_date": "2026-09-30",
  "spot_nq": 30548.51,
  "base_expected_move_pts": 81.53,
  "base_source": "ACT/365 CBOE NDX Options (P04-fix6)",
  "empirical_adjustment_factor": null,
  "is_calibrated": false,
  "calibration_status": "non calibré",
  "calibration_reason": "échantillon insuffisant (n=7 < 60 séances requises)",
  "projected_amplitude_pts": 81.53,
  "range_low": 30507.75,
  "range_high": 30589.28,
  "day_type_probabilities": [
    {
      "day_type": "range",
      "count": 1,
      "total_sessions": 7,
      "probability_pct": 14.3,
      "wilson_ci_low_pct": 2.6,
      "wilson_ci_high_pct": 51.3,
      "is_sufficient": false,
      "definition": "range <= 0.85 * expected move (config)",
      "note": "échantillon insuffisant (n=7 < 60)"
    },
    {
      "day_type": "trend",
      "count": 2,
      "total_sessions": 7,
      "probability_pct": 28.6,
      "wilson_ci_low_pct": 8.2,
      "wilson_ci_high_pct": 64.1,
      "is_sufficient": false,
      "definition": "|clôture - ouverture| / range >= 0.60 (config)",
      "note": "échantillon insuffisant (n=7 < 60)"
    },
    {
      "day_type": "volatile",
      "count": 4,
      "total_sessions": 7,
      "probability_pct": 57.1,
      "wilson_ci_low_pct": 25.0,
      "wilson_ci_high_pct": 84.2,
      "is_sufficient": false,
      "definition": "range >= 1.15 * expected move (config)",
      "note": "échantillon insuffisant (n=7 < 60)"
    }
  ],
  "status": "OK",
  "status_detail": ""
}
```

---

## 4. Rapport de Calibration Généré (`reports/calibration.md`)
```markdown
# Rapport de Calibration des Prévisions d'Amplitude (P07)

**Date du rapport :** 2026-09-30 14:42 ET | 2026-09-30 19:42 Alger  
**État global de calibration :** `non calibré (n=0 < 60)`  

---

## 1. Métriques de Couverture 1-Sigma

- **Séances évaluées (n) :** 0 (seuil de validation requis : 60)
- **Séances couvertes dans la bande :** 0
- **Taux de couverture observé :** 0.00 %
- **Taux théorique 1-sigma attendu :** 68.27 %
- **Écart à la cible :** -68.27 %
- **Brier score :** N/A

---

## 2. Règle de Non-Surajustement

> **JAMAIS d'ajustement non prouvé :** tant que l'échantillon $n$ n'atteint pas le seuil configuré de 60 séances complètes archivées, la prévision d'amplitude reste strictement égale à l'expected move de base (P04 ACT/365 CBOE) étiquetée **« non calibré »**.

---

## 3. Historique Récent des Prévisions

| Date cible | Prévu Bas | Prévu Haut | Réel Bas | Réel Haut | Couvert ? | Statut |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| 2026-09-30 | 30507.8 | 30589.3 | N/A | N/A | en attente | `OK` |
```

---

## 5. Matrice des Tests & Couverture
```text
tests/test_p07_macro_forecast.py:
  test_macro_config_loaded                PASSED [12%]
  test_compute_series_stats               PASSED [25%]
  test_compute_overnight_stats            PASSED [37%]
  test_wilson_score_interval              PASSED [50%]
  test_1sigma_coverage_and_brier_score    PASSED [62%]
  test_session_classification_day_types   PASSED [75%]
  test_strict_uncalibrated_amplitude      PASSED [87%]
  test_build_calibration_report          PASSED [100%]

Total suite: 155 passed, 2 warnings in 10.91s
Ruff linter: All checks passed!
```
