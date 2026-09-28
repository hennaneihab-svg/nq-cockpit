# P05 · Radar d'événements
Contexte : skill event-playbook. Sources officielles d'abord.
Tâches :
1. Construis le calendrier à partir de : Fed (FOMC, minutes, discours via RSS), BLS (CPI, PPI, emploi, JOLTS), BEA (PIB, PCE), FRED (dates de publication), avec ForexFactory en contrôle croisé (consensus/précédent quand disponible). Signale toute divergence entre sources.
2. Classification Tier 1 / Tier 2 (config). Résultats des mégacaps de config.megacaps (yfinance ; dégradé proprement si absent).
3. Heures stockées en UTC, logique en ET, affichage en Alger. Compte à rebours. Aucun décalage codé en dur.
4. event_risk : RED si un Tier 1 tombe dans mes fenêtres d'Alger OU dans le tampon post-événement (config.events.post_event_buffer_minutes) ; AMBER si Tier 2, mégacap, ou Tier 1 juste avant/après mes fenêtres ; sinon GREEN. Explique toujours la raison.
5. Vérifie le calendrier des deux prochaines semaines et affiche-le en Alger (minutes FOMC du 7 octobre 14h00 ET, FOMC du 27-28 octobre, CPI du 14 octobre, etc. : compare aux sources officielles, ne les suppose pas).
Critères d'acceptation : tests sur le changement d'heure du 1er novembre ; un jour sans événement ; un jour avec deux événements ; sources divergentes.
