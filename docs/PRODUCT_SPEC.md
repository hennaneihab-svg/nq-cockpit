# NQ Cockpit — spécification produit complète

Version 1.0 · 28 septembre 2026 · Usage : préparation, discipline et mesure du trading NQ. Ce n'est ni un signal ni un conseil d'investissement.

> Glossaire des termes (R, win rate, expected move, GEX…) : docs/GLOSSAIRE.md

## 1. Vision
Un cockpit local, 100 % gratuit, qui accompagne le trader sur tout le cycle : **préparer** (contexte, niveaux, événements), **anticiper** (fiches scénarios, prévisions d'amplitude), **contrôler** (discipline, risque), **mesurer** (journal, analytics), **s'améliorer** (coaching chiffré, validation statistique).

## 2. Principes non négociables
1. Gratuit : aucune donnée ni API payante. Testé depuis l'Algérie, avec un plan B pour chaque source.
2. Pas de direction : aucun score haussier/baissier. Prévisions = amplitude/volatilité, scénarios conditionnels, statistiques empiriques avec n et intervalle.
3. Transparence : chaque chiffre a source, horodatage, âge, statut ; le GEX est présenté comme un modèle.
4. Discipline avant information : le feu vert du jour dépend de la checklist et des règles, pas d'un indicateur.
5. Rigueur statistique : hypothèses figées à l'avance ; aucune conclusion sous 60 séances / 12 occurrences.
6. Le trader décide : aucune exécution d'ordre.

## 3. Modules et fonctionnalités

### M1 · Santé des sources et couche de données
- Test de connectivité de toutes les sources (statut OK/DÉGRADÉ/BLOQUÉ, latence, âge) ; page "Santé".
- Cache disque, retry, backoff ; archiveur de barres (NQ=F, ^NDX, ^VIX, ^VXN, ^TNX, DX-Y.NYB) en Parquet pour constituer un historique intraday propre au fil du temps (yfinance limite l'historique fin).
- Base SQLite (journal, événements, snapshots, logs).

### M2 · Moteur de structure d'options (gamma)
- À partir de la chaîne NDX (CBOE différé) : GEX/DEX par strike, net GEX, régime, zero gamma (peut être absent), murs GEX1-5, call/put wall, niveaux 0DTE séparés, vanna/charm si disponibles.
- Expected move du jour (IV ATM et straddle), max pain.
- Conversion en prix NQ via la base NQ=F − ^NDX ; roll trimestriel géré.
- Deux snapshots planifiés (matin, avant la kill zone) avec comparaison de l'évolution des niveaux.

### M3 · Radar d'événements
- Calendrier construit depuis sources officielles : Fed (FOMC, minutes, discours), BLS (CPI, PPI, NFP, JOLTS), BEA (PIB, PCE), FRED, avec ForexFactory en contrôle croisé.
- Classification Tier 1 / Tier 2, résultats des mégacaps (NVDA, MSFT, AAPL, AMZN, GOOGL, META, AVGO, TSLA).
- Heures en ET et en Alger, DST-safe. Compte à rebours et statut GREEN / AMBER / RED selon tes fenêtres et un tampon post-événement.
- Exemple de radar (à vérifier par l'app auprès des sources officielles) : JOLTS 29 sept 10h00 ET ; PCE + PIB T2 30 sept 8h30 ET ; ISM manufacturier 1er oct 10h00 ET ; emploi (NFP) 2 oct 8h30 ET ; **minutes FOMC 7 oct 14h00 ET** ; CPI 14 oct 8h30 ET ; PPI et ventes au détail 15 oct 8h30 ET ; **FOMC 27-28 oct, décision 14h00 ET, conférence de presse 14h30 ET**.
- À titre d'illustration, tant que l'heure d'été US est en vigueur (jusqu'au 1er novembre), 8h30 ET = 13h30 à Alger et 14h00 ET = 19h00 à Alger : les publications de 8h30 précèdent ta première fenêtre, celles de 10h00 ET (15h00 Alger) la précèdent de 30 minutes, et les minutes/FOMC de 14h00 ET tombent après ta seconde fenêtre. L'app doit calculer cela elle-même, et gérer le changement d'heure du 1er novembre.

### M4 · Anticipation des news (Event Playbook)
- **Fiche d'événement** générée à J-2, J-1 et T-30 min : quand, attendu (consensus/précédent), positionnement (expected move, régime gamma, VIX/VXN), historique de réaction du NQ (n, médiane, quantiles à +5/+15/+60 min, part de retournements), scénarios conditionnels (en ligne / chaud / froid selon la surprise), protocole d'action (à l'écart avant/après, attendre la clôture de la première M5, réduire la taille).
- **Intelligence Fed** : diff mot à mot des communiqués FOMC consécutifs ; lecture de ton hawkish/neutre/dovish avec extraits courts ; fiche "minutes à surveiller" avant publication (thèmes du dernier communiqué, discours depuis, rendement 2 ans FRED comme proxy des attentes de taux) ; résumé structuré à la publication (inflation, emploi, taux, bilan, divergences) ; suivi des discours via flux RSS de la Fed.
- **Post-événement** : surprise (réel − consensus), réaction à +1/+5/+15/+60 min, range vs expected move, mise à jour des statistiques.
- Toute lecture de texte est une aide de lecture, pas un signal.

### M5 · Contexte macro et cross-asset
- US10Y, rendement 2 ans, DXY, VIX/VXN (niveau, percentile 1 an, variation 5 jours), range et gap de la nuit du NQ, COT hebdomadaire en contexte.

### M6 · Prévisions d'amplitude et calibration
- Prévision de l'amplitude du jour : expected move, ajusté par régime (gamma, volatilité, événement) à partir de tes propres statistiques accumulées.
- Probabilités empiriques du type "jour de range / tendance / volatil" présentées avec n et intervalle.
- Suivi de calibration : les bandes à 1 sigma contiennent-elles bien ~68 % des clôtures ? Courbe de couverture et score de calibration.
- Aucune prévision directionnelle. Si, plus tard, l'analyse de tes données révèle une tendance statistiquement solide, elle apparaîtra uniquement comme "tendance historique observée (n, IC)", jamais comme signal.

### M7 · Profil de journée et carte des scénarios
- Profil : event_risk, régime de volatilité, régime gamma, consommation de l'expected move, type de journée probable avec raisons.
- Carte "si… alors…" : conditions relatives aux niveaux (flip, murs, extrêmes de nuit, PDH/PDL) et plan associé, sans prédire le sens.
- Drapeaux NO-TRADE : événement RED dans tes fenêtres ou leur tampon, prix coincé entre deux murs, donnée périmée, base NDX/NQ anormale, limite de perte atteinte.
- Export CSV des niveaux pour TradingView/ATAS.

### M8 · Porte de discipline
- Checklist pré-trade liée à ton rulebook : fenêtre, nombre de trades, trade 2 annulé si trade 1 perdant, pause après SL, contexte du jour lu, plan écrit.
- Machine à états de la journée (trades, résultats, verrouillage automatique avec compte à rebours de la pause). Le "GO" vient uniquement de la checklist.

### M9 · Gestionnaire de risque
- Taille de position depuis le risque en % et la distance du stop (NQ 20 $/pt, MNQ 2 $/pt), limite de perte journalière en R, suivi des règles prop (perte journalière max, drawdown glissant) selon les paramètres que tu saisis.

### M10 · Journal et import
- Import CSV (export de plateforme ou Notion) et saisie rapide ; capture d'écran liée.
- Étiquetage automatique du contexte (event_risk, régime gamma/volatilité, distance aux niveaux, jour, fenêtre) à partir des snapshots archivés.

### M11 · Analytics et coaching de performance
- Espérance en R, profit factor, win rate avec intervalle de Wilson, distribution des R, drawdown, séries, courbe d'équité, heatmap heure × jour, performance par setup / événement / régime.
- **Conformité** : détection des violations de tes règles ; performance conformes vs non conformes.
- **Tilt** : pertes consécutives, entrée rapide après un SL, taille augmentée après une perte.
- Rapports hebdo et mensuel : top 3 fuites chiffrées, une règle à renforcer, une force à conserver, objectifs mesurables. Ton factuel.
- Question centrale à laquelle le module répond : "où est-ce que je perds de l'argent, et est-ce l'information ou l'exécution ?"

### M12 · Briefing et alertes
- Brief du matin en texte (Gemini gratuit ou modèle local ou gabarit sans LLM) **fondé uniquement sur le JSON calculé** ; un validateur vérifie que chaque chiffre du texte existe dans les données.
- Alertes Telegram (si accessible) et notifications locales : brief du matin, T-30 et T-5 min avant un événement, proximité d'un niveau (avec avertissement de retard des données), verrouillage de discipline.

### M13 · Laboratoire de validation
- Hypothèses H1-H4 figées avant collecte : gamma négatif ↔ amplitude supérieure à l'expected move ; prix au-dessus du flip ↔ amplitude plus faible ; jours d'événement majeur ↔ amplitude plus large ; réaction mesurable aux murs.
- Rapports avec n, intervalle, taille d'effet ; refus de conclure sous 60 séances. Walk-forward simple. Registre des hypothèses pour éviter la pêche aux corrélations.

### M14 · Pont order flow (optionnel, phase tardive)
- Fichier de niveaux importable dans ATAS/TradingView ; règles de confirmation que tu définis (absorption, delta) documentées pour ton usage manuel.

### M15 · Exploitation
- Une commande de lancement, planificateur, journaux, sauvegarde quotidienne, mode dry-run, tests, thème sombre, page Santé.

## 4. Sources (toutes gratuites) et risques
| Bloc | Source | Risque |
|---|---|---|
| Options NDX | CBOE différé (endpoint non documenté) | Format qui change ; repli manuel |
| Prix, VIX, taux | yfinance | Instable, historique intraday limité ; archiveur + cache |
| Macro | FRED (clé gratuite) | Aucun notable |
| Événements | Fed, BLS, BEA officiels + ForexFactory JSON | ForexFactory non officiel |
| COT | CFTC via cot_reports | Publication hebdomadaire |
| Textes Fed | federalreserve.gov (communiqués, minutes, RSS) | Structure des pages |
| Briefing | Gemini API gratuit / local | Accès et quotas depuis l'Algérie à tester |
| Alertes | Telegram Bot API | Accès depuis l'Algérie à tester |

## 5. Roadmap et critères
| Sprint | Prompts | Livrable |
|---|---|---|
| 1 | P00-P04 | Fondations, santé des sources, audit de la base, données, niveaux NQ |
| 2 | P05-P07 | Radar d'événements, playbook + Fed, macro + prévisions d'amplitude |
| 3 | P08-P09 | Profil de journée, porte de discipline, risque |
| 4 | P10-P11 | Journal, analytics et coaching |
| 5 | P12-P13 | Briefing, alertes, interface finale |
| 6 | P14 | Laboratoire de validation, durcissement, audit final |

Porte d'arrêt : après le sprint 3, si le cockpit n'a pas amélioré la préparation (temps de prépa, respect de la checklist), on simplifie. Après 60 séances, le laboratoire dit ce qui a une valeur mesurable.

## 6. Limites assumées
- Le GEX est un modèle aux hypothèses fragiles ; son lien le mieux établi est avec la volatilité, pas la direction.
- Les données gratuites sont différées ; l'open interest est quotidien ; la conversion NDX→NQ est une approximation.
- Le cockpit ne suppose rien sur tes performances passées : ses statistiques ne reposent que sur les trades que tu y enregistres. Un outil d'information seul ne suffit pas à améliorer un trading : c'est pourquoi la discipline (M8) et la mesure (M10-M11) sont au cœur du produit.
