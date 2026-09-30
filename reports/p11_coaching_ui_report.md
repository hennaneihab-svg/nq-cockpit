# Rapport P11 Reliquat — Élément 3 : Interface Streamlit & Visualisations Plotly (Coaching & Analytics)

**Date :** 1er octobre 2026  
**Branche :** `master`  
**Port :** `8504` (`http://localhost:8504`)  
**Statut :** Validé (268/268 tests passés, ruff 0 défaut) — **En attente de validation explicite avant tout commit**.

---

## 1. Fonctions Réutilisées (Zéro Duplication de Calculs)

Conformément aux instructions et principes directeurs, l'interface utilisateur Streamlit n'effectue aucun recalcul propre de statistiques de trading. Elle orchestre et projette visuellement les résultats des fonctions déjà éprouvées et testées :

### A. Depuis `nqcockpit.journal.engine`
1. `compute_performance_stats(trades, min_trades=..., config=...)` :
   - Calcule le Win Rate et son Intervalle de Confiance Wilson 95 %.
   - Calcule l'espérance mathématique en R et son intervalle normal si l'échantillon est représentatif.
   - Calcule le Profit Factor, le Max Drawdown en R, et la plus longue série de pertes consécutives.
   - Évalue la représentativité statistique (`sample_sufficient = True/False`).
   - Calcule le taux global de conformité et l'espérance comparée des trades conformes vs non conformes.
2. `segment_by_setup_tag(trades, min_samples=...)` :
   - Segmente la performance par étiquette de configuration technique (`setup_tag`).
3. `segment_by_gamma_regime(trades, min_samples=...)` :
   - Segmente la performance par régime gamma optionnel (`GEX+`, `GEX-`, `inconnu`).
4. `detect_period_tilt_alerts(trades, config)` :
   - Évalue et retourne les 5 patterns de tilt comportementaux (sur-trading, vengeance trading, taille anormale, accélération de fréquence, 2 pertes consécutives).
   - Fournit pour chaque alerte les identifiants précis des trades impliqués (`trades_involved`).
5. `detect_violations(trade, session_trades, config)` :
   - Identifie les infractions factuelles aux règles de discipline (hors kill zone, dépassement de limite, non-respect du cooldown, stop déplacé, sortie anticipée, sur-risque).
6. `generate_coaching_report(trades, period, period_label, config)` :
   - Produit l'analyse qualitative et les fuites chiffrées sans jugement moral ni invention statistique sous les seuils.

### B. Depuis `nqcockpit.journal.reports`
1. `get_period_bounds(period, ref_date)` :
   - Découpe calendaire des semaines ISO (du lundi au dimanche) et mois civils avec la période précédente correspondante.
2. `filter_trades_by_date_range(trades, start_date, end_date)` :
   - Filtrage temporel inclusif et tri chronologique strict.

### C. Depuis `nqcockpit.journal.store`
1. `init_journal_db(db_path)` et `load_trades(conn)` :
   - Connexion transactionnelle et chargement des trades horodatés.

---

## 2. Choix d'Architecture & Port de Service

La topologie des services Streamlit de la suite NQ Cockpit respecte une distribution de ports cohérente et dédiée :
- `8501` : Cockpit live d'aide à la décision (`src/nqcockpit/ui/cockpit_page.py`)
- `8502` : Journal de bord et saisie des trades (`src/nqcockpit/ui/journal_page.py`)
- `8503` : Porte de discipline live et dimensionnement de position (`src/nqcockpit/ui/discipline_page.py`)
- **`8504`** : Coaching et visualisations analytiques Plotly (`src/nqcockpit/ui/coaching_page.py`)

Commande CLI mise à disposition :
```bash
nqcockpit journal coaching-ui [--port 8504]
```

---

## 3. Détail des Visualisations Plotly Développées

Toutes les visualisations sont intégrées sous le thème sombre natif (`#0d1117`, `#161b22`, `#30363d`, `#e6edf3`) :

1. **Courbe d'équité en R cumulé chronologique & Alertes de tilt** :
   - Courbe continue reliant chaque trade chronologiquement avec son gain/perte en R cumulé.
   - Ligne en pointillés à `0.0 R`.
   - Infobulle (hover) complète sur chaque point : numéro de trade, date et heure locale, instrument, nombre de contrats (si renseigné, sans valeur inventée si `None`), direction, résultat en R, statut de conformité.
   - **Superposition des alertes de tilt** : marqueurs triangulaires rouges bien visibles placés exactement aux points des trades ayant généré ou subi un pattern de tilt, avec hover détaillant le motif exact et le pattern concerné.

2. **Performance par segment (Setup Tags & Régimes Gamma)** :
   - Diagrammes à barres horizontales comparant l'espérance de gain en R.
   - Coloration conditionnelle : vert (`#3fb950`) si espérance positive, rouge (`#f85149`) si négative.
   - Mention explicite `(n < seuil)` lorsque l'échantillon d'un segment est inférieur au seuil minimal.

3. **Évolution temporelle de la conformité aux règles** :
   - Diagramme à barres par séance montrant le pourcentage de trades 100 % conformes (zéro violation).
   - Code couleur strict : vert pour 100 %, ambre pour $\ge 80\,\%$, rouge pour $< 80\,\%$.
   - Ligne d'objectif en pointillés à 100 %.

4. **Cartes d'indicateurs clés (KPI) et Bandeau de représentativité statistique** :
   - Alerte visuelle orange si $N < 60$ : *"Échantillon insuffisant (N / 60 trades requis). Les métriques sont descriptives et n'ont pas de significativité statistique confirmée."*
   - Bannière verte si $N \ge 60$.
   - Affichage propre des valeurs manquantes (`—`) pour l'espérance, drawdown ou profit factor quand l'échantillon est insuffisant, sans jamais inventer de données.

---

## 4. Guide de Vérification Manuelle pour l'Utilisateur

Pour inspecter visuellement l'application en conditions réelles :

1. Lancer la commande CLI :
   ```bash
   nqcockpit journal coaching-ui
   ```
2. Ouvrir le navigateur à l'adresse [http://localhost:8504](http://localhost:8504).
3. Tester les éléments interactifs :
   - **Sélecteur de période dans la barre latérale** : basculer entre *Toutes les données*, *Cette semaine*, *Semaine précédente*, *Ce mois*, *Mois précédent*, *Plage personnalisée*.
   - **Inspecter le bandeau d'échantillon** : observer l'avertissement de non-significativité si $N < 60$.
   - **Survoler la courbe d'équité Plotly** : vérifier le tracé du R cumulé et les marqueurs rouges d'alertes de tilt.
   - **Examiner les segments** : vérifier que les tags de setup et les régimes GEX s'affichent avec leur nombre d'occurrences.
   - **Consulter le rapport de coaching** en bas de page (fuites chiffrées, force à conserver, règle à renforcer, objectifs).

---

## 5. Sorties Brutes du Terminal

### A. Répertoire courant (`Get-Location`)
```powershell
Path                                    
----                                    
C:\Users\pccom\Desktop\trading asistante
```

### B. Arborescence des tests (`Get-ChildItem -File tests`)
```powershell
    Répertoire : C:\Users\pccom\Desktop\trading asistante\tests

Mode                 LastWriteTime         Length Name                                                                 
----                 -------------         ------ ----                                                                 
-a----        29/09/2026     00:40           1274 test_cli.py                                                          
-a----        29/09/2026     00:05           4220 test_config.py                                                       
-a----        30/09/2026     19:15          17431 test_data_layer.py                                                   
-a----        29/09/2026     01:47            153 test_deps_check.py                                                   
-a----        29/09/2026     00:06            953 test_env.py                                                          
-a----        30/09/2026     16:26          35174 test_events.py                                                       
-a----        30/09/2026     16:39          21359 test_levels_engine.py                                                
-a----        29/09/2026     01:00           1817 test_logging.py                                                      
-a----        29/09/2026     15:13          12926 test_p04fix3.py                                                      
-a----        29/09/2026     14:25           7707 test_p04fix4.py                                                      
-a----        30/09/2026     17:17          11426 test_p04fix5.py                                                      
-a----        30/09/2026     18:27          40082 test_p04fix6.py                                                      
-a----        30/09/2026     19:27          14203 test_p06_playbook.py                                                 
-a----        30/09/2026     19:41          12689 test_p07_macro_forecast.py                                           
-a----        30/09/2026     20:14          11567 test_p08_profile.py                                                  
-a----        30/09/2026     21:12          12909 test_p09_discipline.py                                               
-a----        30/09/2026     20:43          16432 test_p09_journal.py                                                  
-a----        30/09/2026     23:06           9137 test_p10_backup.py                                                   
-a----        30/09/2026     21:46           6836 test_p10_csv_import.py                                               
-a----        30/09/2026     22:51           7281 test_p10_screenshot.py                                               
-a----        01/10/2026     00:24           9222 test_p11_coaching_ui.py                                              
-a----        30/09/2026     23:19          11879 test_p11_report.py                                                   
-a----        01/10/2026     00:09          18380 test_p11_tilt_patterns.py                                            
-a----        29/09/2026     15:01          13938 test_sources.py                                                      
-a----        29/09/2026     00:20           5729 test_time.py                                                         
```

### C. Exécution complète des tests (`.venv\Scripts\pytest.exe -v -o console_output_style=classic`)
```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\pccom\Desktop\trading asistante
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1, dash-4.4.1, platformdirs-4.12.1
collected 268 items

tests\test_cli.py .......
tests\test_config.py ......
tests\test_data_layer.py ..................
tests\test_deps_check.py .
tests\test_env.py ..
tests\test_events.py .........................
tests\test_levels_engine.py ..................
tests\test_logging.py ..
tests\test_p04fix3.py ............
tests\test_p04fix4.py ......
tests\test_p04fix5.py ......
tests\test_p04fix6.py ..............
tests\test_p06_playbook.py ........
tests\test_p07_macro_forecast.py ........
tests\test_p08_profile.py ...........
tests\test_p09_discipline.py ...............
tests\test_p09_journal.py ..........................
tests\test_p10_backup.py .......
tests\test_p10_csv_import.py .........
tests\test_p10_screenshot.py ........
tests\test_p11_coaching_ui.py .........
tests\test_p11_report.py ...........
tests\test_p11_tilt_patterns.py .................
tests\test_sources.py .................
tests\test_time.py .....

============================== warnings summary ===============================
tests/test_p04fix6.py::test_p04fix6b_prior_session_target_tolerance_and_remote_fallback
tests/test_p04fix6.py::test_p04fix6b_prior_session_target_tolerance_and_remote_fallback
  <string>:7: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
====================== 268 passed, 2 warnings in 29.60s =======================
```

### D. Contrôle Linter (`.venv\Scripts\ruff.exe check .`)
```
All checks passed!
```

### E. État Git (`git status`)
```powershell
On branch master
Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   src/nqcockpit/cli.py
	modified:   src/nqcockpit/journal/__init__.py
	modified:   src/nqcockpit/journal/engine.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	reports/p11_coaching_ui_report.md
	src/nqcockpit/ui/coaching_page.py
	tests/test_p11_coaching_ui.py

no changes added to commit (use "git add" and/or "git commit -a")
```
