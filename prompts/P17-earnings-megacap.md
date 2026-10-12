# MISSION P17 : Calendrier des résultats des mega-caps tech & Correctif Santé Composants

## État de la mission
Terminée avec succès. Aucun commit effectué (en attente de confirmation).

## Résumé des implémentations
1. **Modèle de données** : Ajout du champ `tier: int = 1` à `EarningsEvent` dans `src/nqcockpit/events/models.py`.
2. **Classification Tier 1 / Tier 2** :
   - Sources officielles : `slickcharts.com/nasdaq100` et Nasdaq.com (NDX, automne 2026).
   - **Tier 1 (> 5.9%)** : NVDA (8.15%), AAPL (7.26%), MSFT (5.90%).
   - **Tier 2 (< 5.0%)** : AMZN (4.98%), META (4.19%), AVGO (3.95%), GOOGL (3.55%), TSLA (3.46%), GOOG (3.31%).
   - Documenté dans `_get_tier()` (`src/nqcockpit/events/earnings.py`) avec note de réévaluation périodique suite aux rebalancements de l'indice.
3. **Radar d'événements CLI/JSON** : `radar.py` exporte désormais la classification `tier` (`[T1]` / `[T2]`) et le statut de confirmation (`[confirmée]` / `[estimée]`).
4. **Radar Streamlit (UI)** :
   - Unification de `fetch_mega_caps_card()` dans `src/nqcockpit/macro/news_radar.py` sur `fetch_earnings_events()`.
   - Affichage en direct du statut OK / DÉGRADÉ avec motif explicite sans jamais dupliquer le mot statut.
   - Protection TTL cache : un statut DÉGRADÉ n'est mis en cache que 60 secondes (contre 12h pour OK), évitant le verrouillage en dégradé suite à un test ou une coupure réseau transitoire.
   - Isolation des tests : `test_mega_caps_card_degraded_when_scans_fail` patche `_save_cache` pour ne plus polluer le répertoire `data/cache` sur disque.
5. **Correctif du bug visuel "DÉGRADÉ: DÉGRADÉ"** :
   - **Localisation** : `src/nqcockpit/profile/engine.py` (ligne 725) où `f"DÉGRADÉ: {snap_status}"` concaténait `"DÉGRADÉ"` avec la colonne `status` de la base qui valait déjà `"DÉGRADÉ"`.
   - **Correction** : Extraction du motif réel (via anomalies du snapshot SQLite, ou source CBOE), nettoyage des préfixes redondants, et filtre défensif regex `re.sub(r"(DÉGRADÉ\s*[:—\-]\s*)+DÉGRADÉ", "DÉGRADÉ", ...)` dans `cockpit_page.py`.
6. **Tests unitaires dédiés** (`tests/test_p17_earnings.py`) :
   - `test_get_tier_classification` : validation mathématique Tier 1 vs Tier 2.
   - `test_yfinance_degraded_on_failure` : bascule en DÉGRADÉ sans inventer de date.
   - `test_earnings_confirmed_vs_estimated_display` : vérification des balises textuelles.
   - `test_degraded_status_never_duplicates_word` : non-duplication consécutive du mot DÉGRADÉ.
   - `test_gamma_component_health_degraded_status_formatting` : extraction du motif réel du snapshot.

## Sortie ruff (sur fichiers modifiés)
```
All checks passed!
```

## Diff --stat (périmètre P17 + correctif santé)
```
 src/nqcockpit/events/earnings.py   | 25 ++++++++++++-
 src/nqcockpit/events/models.py     |  3 ++
 src/nqcockpit/events/radar.py      |  3 +-
 src/nqcockpit/macro/news_radar.py  | 73 +++++++++++++++-----------------------
 src/nqcockpit/profile/engine.py    | 42 ++++++++++++++++++++--
 src/nqcockpit/ui/cockpit_page.py   | 13 +++++--
 tests/test_dashboard_news_radar.py |  4 ++-
 tests/test_p17_earnings.py         | 149 ++++++++++++++++++++++++++++++++++++++
 8 files changed, 261 insertions(+), 51 deletions(-)
```

## Sortie pytest brute (suite complète)
```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\pccom\Desktop\trading asistante
configfile: pyproject.toml
plugins: anyio-4.15.1, dash-4.4.1, platformdirs-4.12.1
collected 342 items

tests\test_cli.py .........                                              [  2%]
tests\test_config.py ......                                              [  4%]
tests\test_dashboard_news_radar.py ..............                        [  8%]
tests\test_data_layer.py ..................                              [ 13%]
tests\test_deps_check.py .                                               [ 14%]
tests\test_env.py ..                                                     [ 14%]
tests\test_events.py .........................                           [ 21%]
tests\test_levels_engine.py ..................                           [ 27%]
tests\test_logging.py ..                                                 [ 27%]
tests\test_p04fix3.py ............                                       [ 31%]
tests\test_p04fix4.py ......                                             [ 33%]
tests\test_p04fix5.py ......                                             [ 34%]
tests\test_p04fix6.py ..............                                     [ 38%]
tests\test_p06_playbook.py ........                                      [ 41%]
tests\test_p07_macro_forecast.py ........                                [ 43%]
tests\test_p08_profile.py ...........                                    [ 46%]
tests\test_p09_discipline.py .................                           [ 51%]
tests\test_p09_journal.py ..........................                     [ 59%]
tests\test_p10_backup.py .......                                         [ 61%]
tests\test_p10_csv_import.py .........                                   [ 64%]
tests\test_p10_screenshot.py ........                                    [ 66%]
tests\test_p11_coaching_ui.py .........                                  [ 69%]
tests\test_p11_report.py .............                                   [ 72%]
tests\test_p11_tilt_patterns.py .................                        [ 77%]
tests\test_p12_briefing.py ...........                                   [ 80%]
tests\test_p13_multipage_ui.py ........                                  [ 83%]
tests\test_p14_lab_hardening.py ...........                              [ 86%]
tests\test_p15_mt5_integration.py ...................                    [ 92%]
tests\test_p17_earnings.py .....                                         [ 93%]
tests\test_sources.py .................                                  [ 98%]
tests\test_time.py .....                                                 [100%]

================= 342 passed, 2 warnings in 78.67s (0:01:18) ==================
```
