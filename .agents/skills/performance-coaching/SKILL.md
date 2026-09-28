---
name: performance-coaching
description: Journal, discipline, analytics et coaching pour améliorer les performances de trading.
---
# Données par trade
date/heure Alger, instrument, sens, setup (tag), entrée, SL, TP1/TP2, sortie, R réalisé, frais, fenêtre, notes, capture (chemin), et contexte auto-taggé : event_risk, régime gamma, régime de volatilité, distance au flip/mur, jour de la semaine.
# Métriques (toutes avec n et intervalle de confiance, ex. Wilson pour le win rate)
espérance en R, profit factor, win rate, gain/perte moyens, distribution des R, drawdown max en R, séries de pertes, courbe d'équité, heatmap heure x jour, performance par setup / événement / régime gamma / volatilité.
# Discipline (la métrique la plus importante)
- Détecter les violations : hors fenêtre, > 2 trades, trade 2 après trade 1 perdant, entrée < 15 min après un SL, SL déplacé, sortie anticipée, risque > limite.
- Taux de conformité, et performance des trades conformes VS non conformes.
- Alertes de tilt : 2 pertes consécutives, entrée rapide après perte, taille augmentée après perte.
# Coaching
- Rapport hebdo et mensuel : top 3 fuites (leaks) chiffrées, 1 règle à renforcer, 1 force à conserver, objectifs mesurables de la semaine suivante.
- Ton factuel, sans jugement émotionnel. Chaque conseil s'appuie sur des chiffres du journal. Pas de conclusion sous 60 trades ou 12 occurrences d'un motif.
- Risque : sizing par risque fixe en % ; limite de perte journalière ; suivi drawdown prop si activé (paramètres utilisateur uniquement).

# Unités et honnêteté des données
- Afficher chaque résultat en R, en points NQ ET en dollars. Le R = risque initial d'un trade (distance entrée-stop) pris comme unité.
- Les statistiques ne reposent QUE sur les trades enregistrés dans le journal. Ne jamais supposer un win rate, une espérance ou une cause d'erreur avant d'avoir les données ; sous les seuils, afficher "échantillon insuffisant".
