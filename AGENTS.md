# NQ Cockpit — instructions agent
Lis d'abord .agents/rules/00-core.md et les skills de .agents/skills/. Résumé impératif :
- Produit 100 % gratuit, sans clé ni service payant. Fonctionne depuis l'Algérie : toute source doit être testée, avec plan B.
- AUCUN biais directionnel haussier/baissier. Le produit décrit : risque événementiel, régime de volatilité/gamma, niveaux, expected move, scénarios conditionnels (si... alors...), drapeaux no-trade.
- Aucun chiffre inventé : tout nombre affiché vient d'une donnée horodatée avec son âge. Source manquante = statut DÉGRADÉ visible, jamais masqué.
- Heures : logique de marché en America/New_York (zoneinfo), affichage en Africa/Algiers. Jamais de décalage codé en dur (le DST US change le 1er novembre 2026).
- Tests pytest pour chaque module, config dans config.yaml, secrets dans .env, logs structurés.
- Ne modifie jamais vendor/. Adapte dans src/.
- Avant chaque livraison : lance les tests, résume ce qui marche, ce qui est dégradé, et les risques.
