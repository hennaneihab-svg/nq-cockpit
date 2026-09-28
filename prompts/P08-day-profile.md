# P08 · Profil de journée, carte de scénarios, drapeaux NO-TRADE
Tâches :
1. Profil du jour combinant : event_risk, régime de volatilité, régime gamma (signe du net GEX, distance au flip), consommation de l'expected move, contexte macro. Sortie : type de journée probable AVEC raisons, niveaux clés en points NQ, statut de chaque donnée.
2. Carte "si… alors…" : pour chaque niveau clé (flip, murs, extrêmes de nuit, PDH/PDL, VWAP), conditions d'observation et plan associé, sans prédire le sens.
3. Drapeaux NO-TRADE : événement RED (fenêtres ou tampon), prix coincé entre deux murs à moins de config.levels.wall_proximity_points, donnée périmée, base NDX/NQ anormale, limite de perte atteinte. Chaque drapeau explique sa cause.
4. Export CSV des niveaux (TradingView/ATAS).
5. UI Streamlit (page Cockpit) : lisible en 5 secondes, thème sombre, feux tricolores, tableau de niveaux, compte à rebours du prochain événement, bandeau de santé des sources.
INTERDIT : score haussier/baissier.
Critères d'acceptation : tests des drapeaux (chaque cas) ; la page Cockpit se lance ; capture d'écran fournie dans le rapport.
