# THE COCKPIT — Guide Complet du Projet

Ce document explique le fonctionnement de THE COCKPIT, son utilité quotidienne pour le trader, ses limites volontaires, ainsi que ce qui peut être personnalisé sans toucher au code source.

---

## 1. Ce que c'est

THE COCKPIT est une station de travail pré-séance et d'aide à la décision conçue sur-mesure pour le trading discrétionnaire des contrats à terme Nasdaq 100 (NQ et MNQ). 

Il sert à préparer sa séance avec rigueur, à identifier les risques économiques majeurs, à calculer précisément la taille de ses positions et à consigner ses trades pour progresser.

Ce qu'il n'est pas :
- **Pas un outil de signal** : il ne donne aucun conseil d'achat ou de vente et ne prédit pas la direction future du marché.
- **Pas un terminal d'exécution** : il n'envoie aucun ordre chez un courtier. L'exécution réelle se fait toujours manuellement sur votre plateforme de trading habituelle.

---

## 2. Ce que l'outil fait concrètement (Module par Module)

### P04 — Niveaux Clés & Murs d'Options (GEX)
- **Ce qu'il affiche** : le niveau de prix de référence (spot NQ), les niveaux pivots de la veille et de la nuit (Overnight High/Low), ainsi que les "murs" d'options (Call Wall et Put Wall) dérivés de l'indice NDX.
- **Pourquoi c'est utile** : les teneurs de marché sur options doivent couvrir leurs positions. Les gros murs d'options agissent fréquemment comme des zones d'attraction ou de blocage statistique du prix. Le module calcule automatiquement l'équivalence entre l'indice NDX et le contrat futur NQ.

### P05 — Radar d'Événements Macroéconomiques
- **Ce qu'il affiche** : le calendrier des publications économiques américaines à fort impact (CPI, NFP, réunions Fed, PCE, PIB) avec un compte à rebours précis.
- **Pourquoi c'est utile** : publier un chiffre d'inflation ou d'emploi provoque souvent des mèches violentes de 50 à 150 points en quelques secondes. Le radar signale ces publications pour éviter d'être pris au piège.

### P06 — Playbook Événementiel & Règles d'Écartement
- **Ce qu'il affiche** : des consignes strictes d'invalidation (drapeaux *No-Trade*) avant et après les événements majeurs.
- **Pourquoi c'est utile** : le système impose de rester à l'écart 5 minutes avant une annonce et 3 minutes après, avec une période de vigilance étendue (90 minutes) après les annonces ultra-critiques.

### P07 — Régime de Volatilité & Expected Move
- **Ce qu'il affiche** : l'amplitude attendue de la journée (*Expected Move* en points NQ, dérivé du prix des options) et le pourcentage de cette amplitude déjà consommé durant la nuit. Il indique également si le marché est en régime de volatilité positive ou négative.
- **Pourquoi c'est utile** : si 80 % de l'amplitude attendue est déjà faite avant 15h30, le potentiel restant est statistiquement réduit. Savoir si le gamma est positif (marché calme, propice au retour à la moyenne) ou négatif (marché nerveux, propice aux accélérations) permet d'adapter sa stratégie.

### P08 — Profil de Séance Consolidé
- **Ce qu'il affiche** : une synthèse globale en un seul coup d'œil, 15 minutes avant l'ouverture de Wall Street.
- **Pourquoi c'est utile** : il rassemble tous les signaux (risques, niveaux, météo macro) dans un bandeau vert ("Trading autorisé") ou rouge ("No-trade"). En 5 secondes, le trader sait s'il peut opérer ou s'il doit s'abstenir.

### P09 — Règles de Discipline & Gestion du Risque
- **Ce qu'il affiche** : un calculateur de position strict et un système de blocage pré-trade.
- **Pourquoi c'est utile** : il élimine le calcul mental sous stress. Il calcule le nombre exact de contrats (NQ ou MNQ) selon votre capital et la distance de votre stop loss, avec arrondi inférieur systématique. Il exige également une checklist et un plan écrit avant d'afficher un verdict "GO".

### P10 — Journal de Bord
- **Ce qu'il affiche** : un formulaire d'enregistrement de trade complet (prix d'entrée, stop, cible, émotions, respect du plan) et un historique détaillé de chaque transaction.
- **Pourquoi c'est utile** : il calcule automatiquement le résultat en multiple de risque (R-Multiple) et archive les observations pour garder une trace objective de sa discipline.

### P11 — Coaching Algorithmique & Statistiques
- **Ce qu'il affiche** : l'analyse des fuites de capital (overtrading, vengeance, non-respect du stop), ainsi que des graphiques interactifs (courbe d'équité, distribution des gains, taux de réussite selon l'heure).
- **Pourquoi c'est utile** : un trader a du mal à voir ses propres biais. L'algorithme montre noir sur blanc ce qui rapporte de l'argent et ce qui en détruit.

### P12 — Briefing Pré-Séance & Alertes
- **Ce qu'il affiche** : un rapport rédigé complet synthétisant toute la séance à venir.
- **Pourquoi c'est utile** : il peut être généré d'un clic, exporté en Markdown, résumé par l'IA Gemini (optionnel) et envoyé directement sur Telegram (optionnel).

### P13 — Interface Unifiée (Streamlit)
- **Ce qu'il affiche** : un tableau de bord sombre, moderne, lisible et compartimenté en 5 pages claires.
- **Pourquoi c'est utile** : double horloge Alger / New York toujours visible, design sombre reposant pour les yeux et navigation fluide sans surcharge visuelle.

### P14 — Robustesse & Résilience Réseau
- **Ce qu'il fait** : architecture technique conçue pour fonctionner de manière fiable depuis l'Algérie, sur des sources 100 % gratuites (Yahoo, CBOE, FRED, BLS).
- **Pourquoi c'est utile** : si un site bloque ou ne répond pas, le logiciel passe automatiquement sur une source alternative et affiche clairement un statut `DÉGRADÉ` plutôt que d'inventer un chiffre faux.

### P15 — Passerelle MetaTrader 5 (Lecture Seule)
- **Ce qu'il affiche** : récupération automatique de l'historique de trading et du solde de compte depuis MT5.
- **Pourquoi c'est utile** : vous n'avez pas besoin de recopier vos trades à la main. Le module est strictement en **lecture seule** : aucune fonction de passage d'ordre n'est présente dans le code, garantissant une sécurité totale de vos fonds.

### P16 — Application Desktop Native
- **Ce qu'il fait** : transforme l'interface web en une vraie application de bureau Windows (`NQCockpit.exe`) avec sa propre icône et sa fenêtre dédiée.
- **Pourquoi c'est utile** : plus besoin d'ouvrir un navigateur. L'application s'isole sur votre machine locale (`127.0.0.1`), sans aucune ouverture sur le réseau externe.

### P17 — Radar des Résultats Mega-Cap Tech
- **Ce qu'il affiche** : le calendrier des publications de résultats des 8 géants de la tech (Nvidia, Apple, Microsoft, Amazon, Alphabet, Meta, Broadcom, Tesla).
- **Pourquoi c'est utile** : ces actions représentent plus de 50 % du poids du Nasdaq 100. Une publication de résultats après la clôture ou avant l'ouverture peut décaler l'indice de plusieurs centaines de points.

---

## 3. Pourquoi c'est différent d'un terminal d'exécution

THE COCKPIT n'est pas conçu pour remplacer **NinjaTrader**, **TradingView** ou votre plateforme d'exécution habituelle :

1. **Aucune duplication des indicateurs de prix** : le Cockpit ne propose pas de carnet d'ordres (DOM), pas de footprint, pas de graphiques en ticks, ni de moyennes mobiles. NinjaTrader fait cela très bien.
2. **Une frontière claire** : NinjaTrader sert à **exécuter le trade** (entrer, placer un stop, sortir). THE COCKPIT sert à **décider si vous avez le droit de trader** et dans quel contexte statistique vous vous trouvez.
3. **La valeur ajoutée unique du Cockpit** :
   - Le contexte macroéconomique et événementiel.
   - La mécanique des options et du gamma (inconnue des indicateurs classiques).
   - Le cadre de discipline strict qui bloque le trading impulsif.

---

## 4. Ce qui est personnalisable sans casser le code

Certains réglages peuvent être ajustés directement par le propriétaire en modifiant des fichiers texte, sans aucune compétence de programmation.

### Dans `config.yaml`

- **Vos créneaux horaires de trading autorisés (Kill Zones)** :
  ```yaml
  trading_windows_algiers:
    - {name: trade1, start: "15:30", end: "17:00"}
    - {name: trade2, start: "17:00", end: "18:30"}
  ```
  *Vous pouvez changer les heures de début et de fin ou renommer les créneaux selon votre rythme.*

- **Vos règles de discipline et de gestion des pertes** :
  ```yaml
  rules:
    max_trades_per_day: 2               # Nombre maximum de trades autorisés par jour
    cancel_trade2_if_trade1_loss: true  # Interdire le trade 2 si le trade 1 est perdant
    cooldown_after_sl_minutes: 15       # Pause obligatoire en minutes après un stop touché
    daily_loss_limit_r: 2.0             # Perte maximale par jour en multiple de risque (R)
  ```

- **Vos paramètres de prévention du tilt** :
  ```yaml
  rules:
    tilt:
      vengeance_minutes: 30             # Délai de détection d'un trade de vengeance
      size_multiplier_threshold: 1.5     # Détection d'une augmentation anormale de taille
      frequency_max_trades: 3           # Alerte si trop de trades dans un court intervalle
      frequency_window_minutes: 45
  ```

- **Votre capital et instrument par défaut** :
  ```yaml
  risk:
    instrument: MNQ                     # MNQ ($2/point) ou NQ ($20/point)
    risk_per_trade_pct: 0.5             # Pourcentage de risque par trade (ex: 0.5% ou 1.0%)
    account_size: 50000                 # Taille de votre compte ($)
  ```

- **Les marges d'attente autour des événements** :
  ```yaml
  events:
    stand_aside_before_minutes: 5       # Minutes d'arrêt avant une annonce Tier 1
    wait_after_minutes: 3               # Minutes d'attente après l'annonce
    post_event_buffer_minutes: 90       # Période de prudence étendue
  ```

- **La liste des grandes valeurs tech surveillées (P17)** :
  ```yaml
  events:
    megacaps: [NVDA, MSFT, AAPL, AMZN, GOOGL, META, AVGO, TSLA]
  ```

### Dans le fichier secret `.env`

- Clé Google Gemini (`GEMINI_API_KEY`) pour activer la synthèse IA du briefing.
- Paramètres Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) pour recevoir le briefing sur votre smartphone.
- Identifiants de lecture MT5 (`MT5_LOGIN`, `MT5_SERVER`, `MT5_PATH`) si vous utilisez plusieurs comptes.

---

## 5. Ce qui n'est PAS personnalisable sans développement

Pour ces modifications, **ne tentez pas de modifier les fichiers de configuration** : elles nécessitent un nouveau chantier de développement structuré.

1. **Ajouter un autre actif (ex: Gold GC, Pétrole CL, S&P 500 ES, Euro 6E)** :
   Le moteur d'options, le scraping CBOE, les calculs de conversion de prix et les formules de gamma sont spécifiquement conçus pour le couple NDX/NQ.
2. **Modifier la formule mathématique du GEX ou du Gamma Flip** :
   Ces algorithmes sont codés dans la logique interne (`src/nqcockpit/levels/`).
3. **Connecter un courtier pour passer des ordres en direct (Interactive Brokers, Tradovate, Rithmic)** :
   Le logiciel est architecturalement dépourvu de module de passage d'ordre par mesure de sécurité.
4. **Modifier l'agencement graphique ou ajouter de nouvelles pages** :
   Les pages de l'interface graphique sont structurées dans `src/nqcockpit/ui/`.
5. **Intégrer une nouvelle source payante d'options (ex: SpotGamma, MenthorQ, Volland)** :
   Le produit est volontairement bâti sur des flux 100 % gratuits avec des mécanismes de tolérance aux pannes.

---

## 6. Roadmap en attente

Ces chantiers ont été validés sur le principe mais restent à lancer :

1. **Baromètre CME FedWatch en direct** :
   Scraping direct des probabilités de décision de taux de la Réserve Fédérale sans passer par une API payante.
2. **Panel de Sentiment et de Positionnement** :
   Intégration du ratio Put/Call actions CBOE, des sondages de sentiment des investisseurs particuliers (AAII), et du score composite Fear & Greed.
