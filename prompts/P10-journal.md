# P10 · Journal de trading et auto-contexte
Tâches :
1. Modèle de trade (champs du skill performance-coaching) dans SQLite ; saisie rapide dans l'UI ; import CSV (fournis un modèle CSV et un import tolérant : colonnes manquantes signalées, fuseau horaire explicite) compatible avec un export de plateforme et un export Notion.
2. Auto-tag du contexte à partir des snapshots archivés au moment du trade : event_risk, régime gamma/volatilité, distance au flip/mur, jour de la semaine, fenêtre. Si aucun snapshot n'existe pour la date, marque "contexte inconnu" sans inventer.
3. Lien vers capture d'écran (chemin local), tags de setup (liste configurable), notes.
4. Sauvegarde quotidienne de la base (copie datée, rotation).
Critères d'acceptation : tests d'import (fichier propre, fichier avec erreurs, doublons) ; page Journal fonctionnelle ; 20 trades fictifs générés pour la démo, clairement marqués "démo" et supprimables.
