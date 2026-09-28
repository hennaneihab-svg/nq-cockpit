---
name: engineering-standards
description: Standards d'ingénierie du projet : structure, tests, qualité, exploitation.
---
- Python 3.11+, typage, docstrings courtes, ruff pour le lint, pytest pour les tests.
- Arborescence : src/{sources,data,levels,events,playbook,macro,forecast,profile,discipline,risk,journal,coaching,briefing,alerts,ui,lab}, tests/, data/, reports/, logs/.
- Données : Parquet pour séries et snapshots, SQLite pour journal et logs d'événements. Schémas versionnés.
- Un module = une responsabilité ; interfaces claires entre modules via JSON/dataclasses ; pas de logique métier dans l'UI.
- Tests : fixtures pour chaque parseur externe ; cas limites (chaîne vide, flip absent, jour férié, changement d'heure, source bloquée).
- Exploitation : commande unique `python -m nqcockpit run`, planificateur APScheduler, logs tournants, sauvegarde quotidienne de la base, mode --dry-run.
- UI Streamlit multipage, thème sombre, lisible en 5 secondes : feux tricolores, tableau de niveaux en points NQ, compte à rebours, statut des sources.
- Chaque prompt se termine par : tests verts, README de module, rapport de livraison.
