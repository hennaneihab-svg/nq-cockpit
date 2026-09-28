# P07 · Contexte macro et prévisions d'amplitude
Contexte : skill nq-principles (pas de direction).
Tâches :
1. Contexte : US10Y, 2 ans, DXY, VIX/VXN (niveau, percentile 1 an, variation 5 jours), range et gap de la nuit du NQ, COT hebdomadaire (contexte seulement).
2. Prévision d'amplitude du jour : expected move de base ; ajustement empirique par régime (gamma, volatilité, événement) UNIQUEMENT quand les seuils de validation sont atteints, sinon afficher la valeur de base avec "non calibré".
3. Probabilités empiriques de type de journée (range / tendance / volatile) avec n et intervalle de confiance ; définitions du type de journée figées dans config avant calcul.
4. Suivi de calibration : couverture des bandes 1 sigma (attendu ~68 %), courbe de couverture, score de calibration, stockage quotidien dans la table forecasts.
Interdit : toute prévision de sens.
Critères d'acceptation : tests statistiques (Wilson, couverture) ; rapport reports/calibration.md ; la page affiche l'amplitude prévue et l'état de calibration.
