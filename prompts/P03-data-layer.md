# P03 · Couche de données et archiveur de barres
Tâches :
1. Module de récupération avec cache disque, retry/backoff, statut et âge pour : barres (NQ=F, ^NDX, ^VIX, ^VXN, ^TNX, DX-Y.NYB), séries FRED (DGS2, DGS10).
2. Archiveur planifié : sauvegarde quotidienne des barres intraday disponibles (1 m / 5 m) en Parquet partitionné par symbole et date, sans doublons, pour constituer notre propre historique.
3. SQLite (schéma versionné) : tables snapshots, events, event_reactions, trades, daily_state, forecasts. Migrations simples.
4. Détection de roll du contrat NQ (trimestriel) et marquage.
5. Jours fériés/sessions via pandas_market_calendars.
Critères d'acceptation : tests avec fixtures (données vides, source coupée, doublons, jour férié) ; une exécution réelle produit des fichiers Parquet ; aucun appel réseau dans les tests.
