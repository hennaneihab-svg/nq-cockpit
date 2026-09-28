# P12 · Briefing du matin et alertes
Tâches :
1. Brief du matin (texte court structuré) généré à partir du JSON du jour : risque événementiel, régime, niveaux, expected move, scénarios, drapeaux. Moteur : Gemini API gratuit si accessible, sinon modèle local ou gabarit sans LLM. Validateur : chaque nombre du texte doit exister dans le JSON, sinon régénération puis repli sur le gabarit.
2. Alertes : brief à l'heure choisie, T-30 et T-5 min avant chaque événement Tier 1/2, proximité d'un niveau (avec avertissement "données différées"), début/fin de pause après SL, verrouillage de discipline. Canaux : Telegram (si testé OK en P01) + notifications locales ; repli documenté sinon.
3. Planificateur unique APScheduler pour snapshots, brief, alertes, archiveur, sauvegardes ; mode --dry-run.
Critères d'acceptation : tests du validateur (nombre inventé rejeté) ; simulation d'une journée en dry-run avec journal des alertes ; secrets uniquement dans .env.
