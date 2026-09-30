# Rapport de livraison — P09 (réel) : Porte de Discipline Live & Risque

**Date :** 2026-09-30  
**Statut :** En attente de validation (non commité)  
**Tests :** 15/15 unitaires passés (207/207 global projet) | Ruff : 0 erreur

---

## 1. Ce qui a été fait

### Machine à états de la séance ([engine.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/discipline/engine.py))
- Interrogable en temps réel à tout instant.
- Détecte l'appartenance aux fenêtres d'Alger (`trading_windows_algiers`), le nombre de trades pris/restants, la perte journalière cumulée en $R$.
- Pause post-SL obligatoire avec compte à rebours en temps réel (`MM:SS`).
- Verrouillage automatique : limite de 2 trades/jour, annulation Trade 2 si Trade 1 en perte, limite de perte journalière atteinte ($-2.0R$).

### Checklist pré-trade interactive GO / STOP ([models.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/discipline/models.py), [engine.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/discipline/engine.py))
- Items vérifiés : machine à états permissive, risque événementiel Tier 1 non-rouge, confirmation consultation P08, plan écrit explicite ($\ge 10$ caractères), sizing calculé et valide.
- Statut purement logique, zéro appréciation subjective, aucun bouton pour forcer GO.

### Gestionnaire de risque & sizing ([risk.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/discipline/risk.py))
- Valeur du point configurable (`NQ`: 20 \$/pt, `MNQ`: 2 \$/pt, extensible sans codage en dur dans [config.yaml](file:///c:/Users/pccom/Desktop/trading%20asistante/config.yaml)).
- Arrondi strictement inférieur (`math.floor`) pour ne jamais excéder le risque alloué.
- Détection optionnelle des contraintes Prop Firm (perte max quotidienne, trailing drawdown).

### Interface Streamlit Discipline ([discipline_page.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/ui/discipline_page.py))
- Page dédiée sur port 8503 avec affichage réactif de l'état, compte à rebours et calculateur.

### CLI & Tests ([cli.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/cli.py), [test_p09_discipline.py](file:///c:/Users/pccom/Desktop/trading%20asistante/tests/test_p09_discipline.py))
- Commandes `status`, `check`, `sizing`, `ui`.
- 15 tests pytest unitaires couvrant tous les états, calculs à la main et garantie d'absence d'ordre.

---

## 2. Ce qui est dégradé
- Aucun composant dégradé. Le module est 100 % local, déterministe et sans dépendance externe.

---

## 3. Risques résiduels
- Si l'heure système locale dévie par rapport à l'heure réseau, les fenêtres d'Alger et le compte à rebours de cooldown peuvent avoir un décalage équivalent (dépendance vis-à-vis de l'horloge OS).

---

## 4. Prochaine étape
- Validation par l'utilisateur $\to$ commit P09 réel $\to$ P10 (Cockpit unifié ou automatisation de session).

---

## 5. Sorties Brutes de Validation

### Sortie brute du dimensionnement de position (3 cas vérifiés à la main)

**Cas A : MNQ Standard (50 000 \$, risque 0.5 %, stop 30 pts)**
$$\text{Budget} = 50\,000 \times 0.005 = 250\,\$ \quad | \quad \text{Risque/contrat} = 30 \times 2 = 60\,\$ \implies \lfloor 250 / 60 \rfloor = 4 \text{ contrats } (240\,\$)$$

```text
PS C:\Users\pccom\Desktop\trading asistante> .venv\Scripts\python.exe -m nqcockpit.cli discipline sizing --account 50000 --risk-pct 0.5 --stop-pts 30 --instrument MNQ
=================================================================
  DIMENSIONNEMENT DE POSITION — MNQ
=================================================================
  Capital compte   : 50000.00 $ | Risque max : 0.50%
  Stop loss        : 30.00 pts | Valeur pt : 2.0 $/pt
  Budget alloué    : 250.00 $
  Risque / contrat : 60.00 $
  --> CONTRATS     : 4 contrat(s) (arrondi inférieur)
  --> Risque réel  : 240.00 $ (0.48%)
=================================================================
```

### Sortie brute d'un scénario complet (GO $\to$ Cooldown $\to$ STOP verrouillé)

```text
=== SCÉNARIO 1 : TOUTES CONDITIONS RÉUNIES (GO) ===
Statut machine à états : READY (can_trade=True)
Fenêtre active : trade1 | Trades restants : 2
VERDICT FINAL : GO (passed=True)
Taille autorisée : 4 contrats MNQ (budget=250.0$, risque réel=240.0$ / 0.48%)

=== SCÉNARIO 2 : COOLDOWN POST-SL EN COURS (PAUSE ACTIVE) ===
Statut machine à états : COOLDOWN_ACTIVE (can_trade=False)
Minuteur de pause : 07:00 restantes (420.0s)
  - Pause obligatoire active après SL : reste 07:00 avant toute nouvelle entrée (cooldown 15 min).

=== SCÉNARIO 3 : APRÈS 2 PERTES (-2.0R) -> SÉANCE VERROUILLÉE (STOP) ===
Statut machine à états : LOCKED_DAILY_LOSS (can_trade=False)
R réalisé jour : -2.00R | Trades restants : 0
VERDICT FINAL : STOP (passed=False)
Motifs de blocage :
  - [STOP] Limite de perte journalière atteinte (-2.00R <= -2.0R). Séance verrouillée.
```

### Sortie brute de `pytest -v` (15 tests P09 discipline)

```text
PS C:\Users\pccom\Desktop\trading asistante> .venv\Scripts\pytest.exe tests/test_p09_discipline.py -vv -o console_output_style=classic
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\pccom\Desktop\trading asistante\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\pccom\Desktop\trading asistante
configfile: pyproject.toml
plugins: anyio-4.15.1, dash-4.4.1, platformdirs-4.12.1
collecting ... collected 15 items
tests/test_p09_discipline.py::test_state_machine_ready_during_window PASSED
tests/test_p09_discipline.py::test_state_machine_out_of_window PASSED
tests/test_p09_discipline.py::test_state_machine_lock_after_trade1_loss PASSED
tests/test_p09_discipline.py::test_state_machine_cooldown_active_after_sl PASSED
tests/test_p09_discipline.py::test_state_machine_cooldown_expired PASSED
tests/test_p09_discipline.py::test_state_machine_max_trades_lockout PASSED
tests/test_p09_discipline.py::test_state_machine_daily_loss_limit PASSED
tests/test_p09_discipline.py::test_sizing_case_a_mnq_standard PASSED
tests/test_p09_discipline.py::test_sizing_case_b_nq_standard PASSED
tests/test_p09_discipline.py::test_sizing_case_c_insufficient_budget PASSED
tests/test_p09_discipline.py::test_sizing_prop_firm_constraints PASSED
tests/test_p09_discipline.py::test_checklist_verdict_go PASSED
tests/test_p09_discipline.py::test_checklist_verdict_stop_on_event_red PASSED
tests/test_p09_discipline.py::test_checklist_verdict_stop_missing_plan_or_p08 PASSED
tests/test_p09_discipline.py::test_zero_order_execution_in_discipline_code PASSED
============================= 15 passed in 0.15s ==============================
```
*(Totalité de la suite globale du projet : 207 tests passés).*

### Sortie brute de `ruff check`

```text
PS C:\Users\pccom\Desktop\trading asistante> .venv\Scripts\ruff.exe check .
All checks passed!
```

### Sortie brute de `git status` (aucun commit effectué)

```text
PS C:\Users\pccom\Desktop\trading asistante> git status
On branch master
Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   config.yaml
	modified:   src/nqcockpit/cli.py
	modified:   src/nqcockpit/config.py
	modified:   src/nqcockpit/discipline/__init__.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	reports/p09_discipline_report.md
	src/nqcockpit/discipline/engine.py
	src/nqcockpit/discipline/models.py
	src/nqcockpit/discipline/risk.py
	src/nqcockpit/ui/discipline_page.py
	tests/test_p09_discipline.py

no changes added to commit (use "git add" and/or "git commit -a")
```
