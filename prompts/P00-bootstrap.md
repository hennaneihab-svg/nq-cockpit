# P00 · Fondations du projet
Contexte : lis AGENTS.md, .agents/rules/00-core.md et tous les skills de .agents/skills/ avant de commencer. Spécification : docs/PRODUCT_SPEC.md.
Tâches :
1. Vérifie que .venv, requirements.txt, config.yaml, .env existent (sinon indique-moi de lancer setup/install).
2. Crée le paquet Python `nqcockpit` sous src/ avec les sous-paquets listés dans le skill engineering-standards, chacun avec __init__.py.
3. Implémente : chargement de config.yaml (validation, erreurs claires), chargement de .env, logging structuré avec rotation (logs/), utilitaires de temps (zoneinfo : conversion ET<->Alger, prochaine occurrence d'une heure d'Alger, test de fenêtre de trading) avec tests sur le changement d'heure US du 1er novembre 2026.
4. CLI : `python -m nqcockpit` avec sous-commandes vides (run, check-sources, snapshot, brief, ui).
5. pytest + ruff configurés, un test CI local (`pytest -q` doit passer).
Critères d'acceptation : les tests passent ; `python -m nqcockpit --help` s'affiche ; aucun secret dans le code.
Ne fais pas : aucune fonctionnalité métier, aucune source réseau à ce stade.
Livraison : rapport (fait / dégradé / risques / prochaine étape).
