# P02 · Audit et intégration de la base GEX (code tiers)
Contexte : vendor/gex-dashboard est un dépôt tiers (MIT, projet jeune à un seul auteur). Lecture seule.
Tâches AVANT toute exécution :
1. Liste tous les appels réseau sortants, variables d'environnement lues, écritures disque, sous-processus, et le serveur MCP. Confirme l'absence de télémétrie ou d'exfiltration. Signale tout comportement suspect.
2. Identifie les modules optionnels payants (backfill/Databento, tt_auth/tastytrade) et confirme que rien ne les charge par défaut.
3. Ne modifie jamais vendor/. Ne lance pas le serveur MCP.
Puis : crée un venv isolé pour le dépôt tiers si ses dépendances entrent en conflit avec les nôtres, lance sa suite de tests (62 attendus), lance son dashboard et confirme qu'il affiche NDX.
Mappe ce qu'on réutilise (ingest, greeks, metrics) et ce qu'on réécrit ; documente les limites (endpoint CBOE non officiel, flux delta = proxy). Compare ses formules au skill gex-methodology et signale tout écart.
Critères d'acceptation : rapport d'audit docs/vendor_audit.md avec verdict (utilisable / à corriger / à écarter) et risques.
