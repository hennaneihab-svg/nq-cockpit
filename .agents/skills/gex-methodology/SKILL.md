---
name: gex-methodology
description: Formules et conventions GEX, gamma flip, expected move et conversion NDX vers NQ.
---
- GEX ($ par 1 %) = gamma x OI x 100 x spot^2 x 0.01 ; calls +, puts - (convention naïve : dealers longs calls, courts puts). Modèle, pas un fait : l'afficher comme tel.
- Zero gamma : recalculer le GEX net sur une grille de spots (+/-8 %), interpoler le passage par zéro le plus proche. Flip absent = résultat valide (régime très positif).
- Régimes : GEX net > 0 => hedging amortisseur (tendance à revenir vers la moyenne) ; < 0 => amplificateur (amplitudes plus grandes). C'est un lien de VOLATILITÉ, pas de direction.
- Murs : call wall = plus fort GEX call au-dessus du spot ; put wall = plus fort GEX put en dessous. 0DTE séparé du reste.
- Expected move 1 sigma = prix x IV ATM x sqrt(jours/252) ; ~68 % des cas, pas un plafond. Comparer au straddle ATM du front.
- Conversion : niveau NQ = niveau NDX + base ; base = NQ=F - ^NDX mesurée au snapshot ; toujours afficher la base et l'heure. Gérer le roll trimestriel.
- Dollars : NQ = 20 $/point, MNQ = 2 $/point (pas le multiplicateur 100 des options actions). Options sur futures => Black-76 (amélioration future, pas MVP).
- L'open interest n'est publié qu'une fois par jour : marquer "OI de la veille". Le flux intraday est un proxy, pas de l'order flow signé.
- Toujours signaler donnée périmée (config levels.stale_data_minutes).
