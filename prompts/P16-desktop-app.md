# P16 - Desktop App Native

## Ce qui a été fait
1. **Ajout de pywebview et pyinstaller** : Intégrés dans `pyproject.toml` comme dépendances.
2. **Icône personnalisée** : Extraction du logo depuis l'image fournie par l'utilisateur, suppression de l'arrière-plan, et génération d'une icône `.ico` multi-résolutions dans `assets/icon.ico`.
3. **Nouvelle commande CLI** : Ajout de la sous-commande `desktop` dans `src/nqcockpit/cli.py` (`python -m nqcockpit desktop`). Cette commande lance un serveur Streamlit lié **exclusivement** à `127.0.0.1` en arrière-plan, puis ouvre une fenêtre native via `pywebview`. L'ancienne commande `ui` reste fonctionnelle pour une utilisation classique via navigateur.
4. **Script de lancement** : Création du script `launch_desktop.py` comme point d'entrée simple pour PyInstaller.
5. **Empaquetage** : Utilisation de PyInstaller pour générer l'exécutable dans le dossier `dist/NQCockpit`, incluant l'icône, toutes les dépendances de Streamlit, webview et l'ensemble du package `nqcockpit` via `--collect-all nqcockpit` et `--add-data "src/nqcockpit/ui;nqcockpit/ui"` (avec `--onedir` et `--windowed`). Commande exacte : `pyinstaller --noconfirm --clean --onedir --windowed --name "NQCockpit" --icon "assets/icon.ico" --collect-all streamlit --collect-all webview --collect-all nqcockpit --add-data "src/nqcockpit/ui;nqcockpit/ui" launch_desktop.py`.

## Exécutable généré
Le dossier généré est `dist/NQCockpit/` et l'exécutable est `dist/NQCockpit/NQCockpit.exe`. 
Pour le lancer, double-cliquez sur `NQCockpit.exe`.

## Preuves et Critères d'Acceptation

### 1. Liaison réseau locale uniquement (127.0.0.1)
Le serveur Streamlit est lancé avec `--server.address 127.0.0.1`. Validation (netstat ou équivalent) montrant aucune exposition externe :
```
  TCP    127.0.0.1:8501         0.0.0.0:0              LISTENING       9024
```

### 2. Tests
Les 337 tests existants continuent de passer sans problème.
_Sortie de pytest :_
```
........................................................................ [ 21%]
........................................................................ [ 42%]
........................................................................ [ 64%]
........................................................................ [ 85%]
.................................................                        [100%]
============================== warnings summary ===============================
tests/test_p04fix6.py::test_p04fix6b_prior_session_target_tolerance_and_remote_fallback
tests/test_p04fix6.py::test_p04fix6b_prior_session_target_tolerance_and_remote_fallback
  <string>:7: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
337 passed, 2 warnings in 58.75s
```

### 3. Ruff 
Aucun problème de linting majeur introduit.
_Sortie de ruff :_
```
> ruff check launch_desktop.py src/nqcockpit/cli.py
Found 5 errors (5 fixed, 0 remaining).
```
