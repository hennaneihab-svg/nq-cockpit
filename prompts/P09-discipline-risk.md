# P09 · Porte de discipline et gestionnaire de risque
Contexte : skill nq-principles (règles du trader) et performance-coaching.
Tâches :
1. Machine à états de la journée : trades pris, résultats, fenêtre active, pause après SL avec compte à rebours, annulation du trade 2 si le trade 1 est perdant, limite de perte journalière (R), verrouillage automatique.
2. Checklist pré-trade interactive (fenêtre, nombre de trades, contexte du jour lu, event_risk, plan écrit en une phrase, risque calculé). Le statut GO / STOP dépend UNIQUEMENT de la checklist et des règles.
3. Gestionnaire de risque : taille de position depuis le risque en % du compte et la distance du stop (NQ 20 $/pt, MNQ 2 $/pt), arrondi au contrat, avertissement si le risque dépasse la limite ; suivi optionnel des règles prop (perte journalière max, drawdown glissant) avec paramètres saisis par l'utilisateur.
4. Page UI "Discipline" et intégration dans le Cockpit.
Critères d'acceptation : tests de la machine à états (scénarios : deux pertes, SL puis nouvelle entrée à 10 min, hors fenêtre) ; calculs de taille vérifiés à la main dans les tests ; aucune exécution d'ordre.
