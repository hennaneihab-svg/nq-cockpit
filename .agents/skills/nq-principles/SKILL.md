---
name: nq-principles
description: Principes produit et règles de trading du cockpit NQ. À lire avant toute décision de conception ou de fonctionnalité.
---
# Principes
- Le cockpit PRÉPARE, CONTRÔLE LA DISCIPLINE et MESURE. Il n'exécute aucun ordre et ne prédit pas la direction.
- "Prévision" = prévision de volatilité/amplitude, scénarios conditionnels (si X alors plan Y), et statistiques empiriques historiques avec n et intervalle de confiance. Jamais "le NQ va monter/baisser".
- Sorties du jour : risque événementiel (GREEN/AMBER/RED), régime de volatilité, régime de gamma, niveaux en points NQ, expected move, drapeaux NO-TRADE, checklist pré-trade.
# Règles du trader (source : config.yaml)
- Fenêtres (heure d'Alger) : trade 1 15h30-17h00, trade 2 17h00-18h30. Aucune entrée hors fenêtre.
- Max 2 trades/jour ; trade 2 annulé si trade 1 perdant ; pause 15 min après un SL.
- Entrée : confirmation CHoCH/BOS (M15/M5) + déclencheur IFVG ; SL au-delà de la zone 0.618-0.786 ; TP1 0.382 (50 %, puis BE), TP2 0.0.
- Le cockpit ne juge pas le setup technique : il vérifie le CONTEXTE et le RESPECT DES RÈGLES.
# Interdits
- Score haussier/baissier, "signal", "probabilité de hausse".
- Donnée sans horodatage. Statistique sans n. Conclusion sous les seuils de validation.
