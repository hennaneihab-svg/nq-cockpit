# P06 · Anticipation des news (Event Playbook) et lecture des textes de la Fed
Contexte : skill event-playbook, en entier.
Tâches :
1. Fiche d'événement (JSON + vue UI) générée à J-2, J-1, T-30 min : quand, attendu, positionnement (expected move, gamma, VIX/VXN), historique de réaction du NQ (n, médiane, quantiles à +5/+15/+60 min, part de retournements ; "échantillon insuffisant" si n < 12), scénarios conditionnels (en ligne / chaud / froid selon des seuils de surprise configurables), protocole d'action (config).
2. Historique de réaction : reconstruis ce que tu peux depuis les barres disponibles ; alimente ensuite la base à chaque nouvel événement (mesure post-événement à +1/+5/+15/+60 min, surprise, range vs expected move).
3. Intelligence Fed : télécharge les deux derniers communiqués FOMC, produis un diff mot à mot (ajouts/retraits), puis une lecture de ton via LLM (Gemini si dispo, sinon gabarit sans LLM) avec extraits courts. Fiche "minutes à surveiller" avant publication (thèmes, discours depuis, rendement 2 ans FRED) ; à la publication des minutes, résumé structuré (inflation, emploi, taux, bilan, divergences). Étiquette : "aide de lecture, pas un signal".
4. Garde-fou LLM : le modèle ne reçoit que du JSON et du texte source ; un validateur rejette toute sortie contenant un nombre absent des entrées.
Critères d'acceptation : fiche complète générée pour le prochain événement Tier 1 ; diff de communiqués fonctionnel sur données réelles ; tests du validateur avec sortie piégée.
