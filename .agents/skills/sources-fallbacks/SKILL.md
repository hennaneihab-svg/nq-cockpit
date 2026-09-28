---
name: sources-fallbacks
description: Sources gratuites, tests depuis l'Algérie, statuts de santé et plans B.
---
- Sources : CBOE différé (NDX), yfinance, FRED (clé gratuite), CFTC COT (cot_reports), calendrier Fed + flux RSS Fed, calendrier BLS/BEA, flux ForexFactory hebdo (non officiel), Gemini API (clé gratuite), Telegram Bot API.
- Toute source peut être bloquée depuis l'Algérie : tester, mesurer la latence, consigner dans reports/source_check.json.
- Chaque appel : timeout 10 s, retry avec backoff exponentiel (3 essais), cache disque, statut OK / DÉGRADÉ / BLOQUÉ.
- Plans B : CBOE bloqué => repli documenté (autre chaîne gratuite ou saisie manuelle des niveaux dans l'UI) ; yfinance en échec => cache + avertissement ; Telegram bloqué => notifications locales + e-mail ; Gemini bloqué => modèle local ou briefing template sans LLM.
- Jamais de clé en dur. Toute clé dans .env. Ne jamais journaliser une clé.
- Les endpoints non officiels (CBOE cdn, ForexFactory JSON) peuvent changer : isoler chaque parseur, tester avec fixtures, alerter si le schéma change.
