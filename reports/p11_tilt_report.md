# Rapport P11 Reliquat — Élément 2 : Extension de la Détection des Patterns de Tilt

**Date :** 1er octobre 2026  
**Branche :** `master`  
**Statut :** Validé (259/259 tests passés, ruff 0 défaut) — en attente de validation utilisateur avant commit.

---

## 1. Localisation et Citation de la Fonction Existante

Avant toute modification, la fonction originale de détection de tilt identifiée dans [`src/nqcockpit/journal/engine.py`](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/journal/engine.py#L172-L215) était :

```python
def detect_tilt_alerts(
    session_date: str,
    session_trades: list[TradeEntry],
    config: AppConfig,
) -> list[TiltAlert]:
    """Détecte les signaux de tilt pour la séance.

    Ne bloque pas — signale uniquement le risque comportemental.
    """
    alerts: list[TiltAlert] = []
    if len(session_trades) < 2:
        return alerts

    # Trier par recorded_at
    ordered = sorted(session_trades, key=lambda t: t.recorded_at)

    # Alerte 1 : 2 pertes consécutives
    for i in range(1, len(ordered)):
        if (ordered[i - 1].outcome == TradeOutcome.LOSS
                and ordered[i].outcome == TradeOutcome.LOSS):
            alerts.append(TiltAlert(
                session_date=session_date,
                reason="2 pertes consécutives détectées.",
                trades_involved=[ordered[i - 1].trade_id, ordered[i].trade_id],
            ))
            break  # 1 alerte max par type

    # Alerte 2 : rentrée rapide (< cooldown) après perte
    cooldown = config.rules.cooldown_after_sl_minutes
    for t in ordered:
        if (t.outcome == TradeOutcome.LOSS
                and t.minutes_after_last_sl is not None
                and 0 < t.minutes_after_last_sl < cooldown):
            alerts.append(TiltAlert(
                session_date=session_date,
                reason=(
                    f"Rentrée {t.minutes_after_last_sl:.1f} min après un SL "
                    f"(cooldown : {cooldown} min) — signal de tilt."
                ),
                trades_involved=[t.trade_id],
            ))
            break

    return alerts
```

---

## 2. Patterns de Tilt Étendus et Implémentés

Cette fonction a été étendue dans le même module ([`src/nqcockpit/journal/engine.py`](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/journal/engine.py)) sans dupliquer la logique existante. Les 5 patterns gérés sont :

1. **Pertes consécutives (rétention de l'existant) :**
   - Constat factuel : `"2 pertes consécutives détectées sur la séance."`
   - Pattern type : `pertes_consécutives`.
2. **Sur-trading :**
   - Nombre de trades sur une séance dépassant la limite journalière (`config.rules.max_trades_per_day`, 2 trades/jour).
   - Constat factuel : `f"Sur-trading : {len(ordered)} trades enregistrés sur la séance (seuil configuré : {max_daily} trades/jour max)."`
   - Pattern type : `surtrading`.
3. **Vengeance trading :**
   - Trade pris moins de $X$ minutes après une perte ($X$ paramétrable via `config.rules.tilt.vengeance_minutes`, 30 min par défaut).
   - Constat factuel : `f"Vengeance trading : nouveau trade pris {delta_min:.1f} min après une perte (seuil configuré : < {vengeance_minutes:.0f} min)."`
   - Pattern type : `vengeance_trading`.
4. **Taille de position anormale :**
   - Trade dont la taille en contrats dépasse un multiple configurable (`size_multiplier_threshold`, 1.5x) de la moyenne observée sur la période.
   - Constat factuel : `f"Taille de position anormale : {c} contrat(s) exécuté(s) (moyenne observée : {mean_contracts:.2f} contrat(s), seuil configuré : >= {size_mult_threshold:.1f}x)."`
   - Pattern type : `taille_anormale`.
5. **Accélération de fréquence :**
   - Plus de $N$ trades dans une fenêtre glissante de $M$ minutes ($N$ et $M$ configurables via `frequency_max_trades: 3`, `frequency_window_minutes: 45`).
   - Constat factuel : `f"Accélération de fréquence : {len(window)} trades exécutés en {actual_span:.1f} min (seuil configuré : > {freq_max_trades} trades en {freq_window_min:.0f} min)."`
   - Pattern type : `accélération_fréquence`.

---

## 3. Neutralité et Objectivité des Formulations

Tous les messages sont de stricts constats quantitatifs et chronologiques. Aucun terme d'inférence émotionnelle, d'accusation ou de diagnostic subjectif n'est employé (tests validés avec rejet strict des mots tels que *impulsif, panique, colère, indiscipline, rage, mauvais*, etc.).

---

## 4. Intégration dans les Rapports Périodiques Markdown

Le générateur périodique ([`src/nqcockpit/journal/reports.py`](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/journal/reports.py)) intègre désormais la section `## 5. Patterns de Tilt Détectés` qui réutilise directement `detect_period_tilt_alerts` :
- Si aucun pattern n'est détecté : `✅ **Aucun pattern de tilt détecté** sur la période étudiée.`
- Si des patterns sont détectés : tableau récapitulatif listant la séance, le type de pattern, le constat factuel et les identifiants de trades concernés.

---

## 5. Sorties Brutes Complètes des Commandes

### 5.1. Liste des Fichiers de Tests (`Get-ChildItem -File tests`)

```text
Path                                    
----                                    
C:\Users\pccom\Desktop\trading asistante

Name          : test_cli.py
Length        : 1274
LastWriteTime : 29/09/2026 00:40:26

Name          : test_config.py
Length        : 4220
LastWriteTime : 29/09/2026 00:05:39

Name          : test_data_layer.py
Length        : 17431
LastWriteTime : 30/09/2026 19:15:34

Name          : test_deps_check.py
Length        : 153
LastWriteTime : 29/09/2026 01:47:11

Name          : test_env.py
Length        : 953
LastWriteTime : 29/09/2026 00:06:40

Name          : test_events.py
Length        : 35174
LastWriteTime : 30/09/2026 16:26:57

Name          : test_levels_engine.py
Length        : 21359
LastWriteTime : 30/09/2026 16:39:47

Name          : test_logging.py
Length        : 1817
LastWriteTime : 29/09/2026 01:00:13

Name          : test_p04fix3.py
Length        : 12926
LastWriteTime : 29/09/2026 15:13:36

Name          : test_p04fix4.py
Length        : 7707
LastWriteTime : 29/09/2026 14:25:24

Name          : test_p04fix5.py
Length        : 11426
LastWriteTime : 30/09/2026 17:17:59

Name          : test_p04fix6.py
Length        : 40082
LastWriteTime : 30/09/2026 18:27:23

Name          : test_p06_playbook.py
Length        : 14203
LastWriteTime : 30/09/2026 19:27:32

Name          : test_p07_macro_forecast.py
Length        : 12689
LastWriteTime : 30/09/2026 19:41:43

Name          : test_p08_profile.py
Length        : 11567
LastWriteTime : 30/09/2026 20:14:41

Name          : test_p09_discipline.py
Length        : 12909
LastWriteTime : 30/09/2026 21:12:26

Name          : test_p09_journal.py
Length        : 16432
LastWriteTime : 30/09/2026 20:43:36

Name          : test_p10_backup.py
Length        : 9137
LastWriteTime : 30/09/2026 23:06:06

Name          : test_p10_csv_import.py
Length        : 6836
LastWriteTime : 30/09/2026 21:46:25

Name          : test_p10_screenshot.py
Length        : 7281
LastWriteTime : 30/09/2026 22:51:14

Name          : test_p11_report.py
Length        : 11879
LastWriteTime : 30/09/2026 23:19:27

Name          : test_p11_tilt_patterns.py
Length        : 14693
LastWriteTime : 01/10/2026 00:03:42

Name          : test_sources.py
Length        : 13938
LastWriteTime : 29/09/2026 15:01:00

Name          : test_time.py
Length        : 5729
LastWriteTime : 29/09/2026 00:20:40
```

### 5.2. Analyse Statique (`ruff check .`)

```text
All checks passed!
```

### 5.3. Suite Globale Pytest (`pytest -v -o console_output_style=classic`)

```text
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\pccom\Desktop\trading asistante
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1, dash-4.4.1, platformdirs-4.12.1
collected 259 items

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
tests\test_p11_report.py ...........
tests\test_p11_tilt_patterns.py .................
tests\test_sources.py .................
tests\test_time.py .....

============================== warnings summary ===============================
tests/test_p04fix6.py::test_p04fix6b_prior_session_target_tolerance_and_remote_fallback
tests/test_p04fix6.py::test_p04fix6b_prior_session_target_tolerance_and_remote_fallback
  <string>:7: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
====================== 259 passed, 2 warnings in 28.44s =======================
```

### 5.4. État Git (`git status`)

```text
On branch master
Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   config.yaml
	modified:   src/nqcockpit/config.py
	modified:   src/nqcockpit/journal/__init__.py
	modified:   src/nqcockpit/journal/engine.py
	modified:   src/nqcockpit/journal/importer.py
	modified:   src/nqcockpit/journal/models.py
	modified:   src/nqcockpit/journal/reports.py
	modified:   src/nqcockpit/journal/store.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	reports/p11_tilt_report.md
	tests/test_p11_tilt_patterns.py

no changes added to commit (use "git add" and/or "git commit -a")
```
