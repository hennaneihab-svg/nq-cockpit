# Règles noyau — NQ Cockpit
1. Gratuit d'abord : aucune API ou donnée payante. Si une fonctionnalité exige du payant, propose une alternative gratuite ou marque-la "hors périmètre".
2. Honnêteté des données : chaque valeur porte source, horodatage, âge, statut (OK/DÉGRADÉ/BLOQUÉ). Interdit d'interpoler ou d'inventer.
3. Pas de direction : aucun score haussier/baissier. Scénarios conditionnels et statistiques empiriques avec n et intervalle seulement.
4. Statistiques : aucune conclusion sous 60 séances ou 12 occurrences d'un événement. Afficher "échantillon insuffisant".
5. Heures : America/New_York pour la logique, Africa/Algiers pour l'affichage. Utiliser zoneinfo.
6. Sécurité : pas de secret en dur, pas de télémétrie, ne jamais exécuter du code tiers sans audit. vendor/ en lecture seule.
7. Qualité : fonctions typées, modules courts, tests pytest, logs, gestion d'erreurs explicite (timeout, retry avec backoff, cache).
8. Livraison : après chaque tâche, exécute les tests et rends un rapport (fait / dégradé / risques / prochaine étape).
9. Le trader garde la décision : l'outil prépare, contrôle la discipline et mesure. Il n'exécute aucun ordre.
