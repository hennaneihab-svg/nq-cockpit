---
name: event-playbook
description: Méthode d'anticipation des événements et news (FOMC, minutes, CPI, NFP, discours) : fiches scénarios, stats de réaction, lecture des textes de la Fed.
---
# Fiche d'événement (générer pour chaque Tier 1/2 à J-2, J-1, T-30 min)
1. Quoi/quand : nom, heure ET et Alger, compte à rebours, statut Tier.
2. Attendu : consensus et précédent (si dispo), écart-type historique de la surprise.
3. Positionnement : expected move du jour, régime gamma, distance aux murs, VIX/VXN.
4. Historique de réaction NQ : distribution des mouvements à +5/+15/+60 min sur les occurrences passées (n, médiane, quantiles, part des retournements). Si n < 12 : "échantillon insuffisant".
5. Scénarios conditionnels (en-ligne / chaud / froid selon seuils de surprise) : ce qu'on observe, pas ce qu'on prédit. Chaque scénario liste les niveaux à surveiller et le protocole (rester à l'écart avant/après, attendre la clôture de la première bougie M5, réduire la taille).
6. Protocole : stand_aside_before_minutes, wait_after_minutes, post_event_buffer_minutes (config).
# Textes de la Fed (gratuits, sources primaires)
- Comparer le dernier communiqué FOMC au précédent : diff mot à mot (ajouts/retraits), puis lecture de ton (hawkish/neutre/dovish) par LLM avec extraits courts. Étiqueter "aide de lecture, pas un signal".
- Minutes (3 semaines après la réunion, 14h00 ET) : avant, fiche "à surveiller" (thèmes du dernier communiqué, discours depuis) ; à la publication, résumé structuré (inflation, emploi, trajectoire des taux, bilan, divergences entre participants). Rendement 2 ans (FRED DGS2) comme proxy des anticipations de taux.
- Discours : flux RSS de la Fed ; extraire orateur, date, thèmes ; comparer au discours précédent du même orateur.
# Après l'événement
- Mesurer surprise (réel - consensus), réaction NQ à +1/+5/+15/+60 min, range vs expected move ; alimenter la base pour améliorer les stats.
# Garde-fous
- Le LLM ne calcule aucun chiffre : il reçoit un JSON et n'écrit que ce qui s'y trouve. Un validateur vérifie que chaque nombre du texte existe dans le JSON.
