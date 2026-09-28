# P01 · Santé des sources (depuis ma connexion en Algérie)
Contexte : skill sources-fallbacks. Aucune source payante.
Tâches : écris `nqcockpit check-sources`. Il teste avec timeout 10 s, retry x3, et rapporte OK / DÉGRADÉ / BLOQUÉ, latence, âge de la donnée, dans reports/source_check.json et un tableau console :
- CBOE https://cdn.cboe.com/api/global/delayed_quotes/options/_NDX.json
- yfinance : NQ=F, ^NDX, ^VIX, ^VXN, ^TNX, DX-Y.NYB
- FRED (FRED_API_KEY) : séries DGS2, DGS10
- CFTC via cot_reports
- Fed : https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm et les flux RSS de la Fed (trouve l'URL officielle de la page des flux)
- BLS : https://www.bls.gov/schedule/news_release/
- ForexFactory : https://nfs.faireconomy.media/ff_calendar_thisweek.json (non officiel)
- Gemini API (si GEMINI_API_KEY présent) : un appel minimal
- Telegram Bot API (si token présent) : getMe
Pour chaque source BLOQUÉE ou DÉGRADÉE, propose dans le rapport un plan B gratuit concret. Ne devine jamais : si une URL échoue, affiche l'erreur exacte.
Critères d'acceptation : je vois quelles sources marchent chez moi ; un test avec source simulée en échec ; le rapport contient les plans B.
Livraison : rapport + le fichier reports/source_check.json.
