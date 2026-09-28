# P11 · Analytics de performance et coaching
Contexte : skill performance-coaching, en entier.
Tâches :
1. Métriques avec n et intervalle de confiance : espérance en R, profit factor, win rate (Wilson), gain/perte moyens, distribution des R, drawdown max en R, séries, courbe d'équité, heatmap heure × jour, performance par setup / événement / régime gamma / volatilité.
2. Discipline : détection des violations de mes règles (config.rules) sur les trades importés ; taux de conformité ; performance conformes vs non conformes.
3. Tilt : 2 pertes consécutives, entrée < 15 min après un SL, taille augmentée après une perte.
4. Rapports hebdo et mensuel en Markdown (reports/) : top 3 fuites chiffrées, une règle à renforcer, une force à conserver, objectifs mesurables de la semaine suivante ; ton factuel ; "échantillon insuffisant" sous 60 trades ou 12 occurrences d'un motif.
5. Page UI "Coaching" avec graphiques Plotly.
Critères d'acceptation : tests de chaque métrique sur un jeu de données calculé à la main ; rapport généré sur les données démo ; aucune conclusion affichée sous les seuils.
