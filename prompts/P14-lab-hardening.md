# P14 · Laboratoire de validation, durcissement, audit final
Tâches :
1. hypotheses.yaml : H1 (gamma négatif ↔ amplitude / expected move plus élevée), H2 (prix au-dessus du flip ↔ amplitude plus faible), H3 (jours d'événement Tier 1 ↔ amplitude plus large), H4 (réaction mesurable aux murs : retournement ou cassure dans N minutes). Seuils et définitions FIGÉS avant toute donnée, avec date de création.
2. validate.py : statistiques avec n, intervalle, taille d'effet ; refuse de conclure sous 60 séances ; corrige pour tests multiples ; rapport hebdo reports/lab.md ; registre des hypothèses (pas d'ajout a posteriori sans horodatage).
3. Durcissement : revue de sécurité (secrets, entrées externes, dépendances), gestion des pannes de chaque source, tests de bout en bout avec sources simulées, sauvegarde/restauration de la base, journaux.
4. Audit final : liste ce qui est prêt / dégradé / manquant, dette technique, risques, et propose la feuille de route suivante (par ex. Black-76 sur options de futures, pont ATAS).
Critères d'acceptation : `pytest -q` vert ; `ruff` sans erreur ; rapport d'audit docs/final_audit.md honnête, sans embellir.
