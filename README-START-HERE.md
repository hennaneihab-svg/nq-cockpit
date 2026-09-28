# NQ Cockpit — kit de démarrage Antigravity

Produit visé : un cockpit pré-marché + accompagnement de trading pour le NQ, 100 % gratuit,
conçu pour fonctionner depuis l'Algérie. Décrit : docs/PRODUCT_SPEC.md. Termes techniques (R, win rate, GEX…) : docs/GLOSSAIRE.md.

## Installation (15 minutes)

1. Installe Python 3.11+ et git (python.org, git-scm.com).
2. Dézippe ce kit dans un dossier `nq-cockpit` (le dossier contient déjà .agents/, AGENTS.md, GEMINI.md).
3. Ouvre un terminal dans ce dossier puis :
   - Windows (PowerShell) : `powershell -ExecutionPolicy Bypass -File setup\install.ps1`
   - macOS/Linux : `bash setup/install.sh`
   Le script crée l'environnement Python, installe les dépendances et clone les dépôts dans `vendor/`.
4. Copie `.env.example` en `.env` et renseigne (tout est gratuit, aucun paiement) :
   - FRED_API_KEY : inscription gratuite sur fred.stlouisfed.org (e-mail seulement)
   - GEMINI_API_KEY : optionnel, clé gratuite d'AI Studio (à tester depuis l'Algérie)
   - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID : optionnel (créer un bot avec @BotFather)
5. Copie `config.example.yaml` en `config.yaml` et vérifie tes fenêtres de trading et tes règles.
6. Ouvre le dossier dans Antigravity comme espace de travail. Les règles (.agents/rules) et
   skills (.agents/skills) sont chargés automatiquement. Redémarre la session si besoin.
   Si ta version lit GEMINI.md ou AGENTS.md, ils sont déjà à la racine.
7. Lance les prompts dans l'ordre : prompts/P00 -> P14. Un prompt à la fois.
   Ne passe au suivant qu'après avoir vérifié les critères d'acceptation du précédent.

## Règles d'or
- Ne saute pas P01 : il teste quelles sources sont accessibles depuis chez toi.
- Vérifie chaque livrable (lance les tests, ouvre l'interface) avant de continuer.
- Ne colle jamais tes clés dans le code ni dans le chat : uniquement dans .env.
- Le dépôt vendor/gex-dashboard est du code tiers : l'audit de P02 est obligatoire avant exécution.
- Outil d'aide à la préparation et à la discipline. Ce n'est ni un conseil d'investissement ni un signal.
