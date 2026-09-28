# P04 · Moteur de niveaux (gamma → NQ)
Contexte : skill gex-methodology ; base auditée en P02.
Tâches : module sans interface qui produit data/levels/levels_YYYYMMDD_HHMM.json (et une ligne SQLite) avec : net GEX, régime, zero gamma (peut être absent), murs GEX1-5, call/put wall, niveaux 0DTE séparés, IV ATM, expected move (formule IV ET straddle), max pain, puis conversion en prix NQ via la base NQ=F − ^NDX mesurée au snapshot. Chaque niveau : horodatage, âge, drapeau "OI de la veille", statut.
Planification APScheduler aux heures d'Alger de config.snapshots_algiers. Comparaison entre le snapshot du matin et le suivant (niveaux qui bougent).
Détection d'anomalies : donnée périmée, base NDX/NQ anormale, chaîne vide, flip absent.
Critères d'acceptation : tests unitaires (conversion, flip absent, chaîne vide, roll) ; `nqcockpit snapshot` produit un JSON valide ; un tableau lisible en console.
