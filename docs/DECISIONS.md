# Registre des Décisions d'Architecture et de Conception (ADR)

Ce document consigne les choix structurants de conception, les arbitrages techniques et leurs justifications pour NQ Cockpit.

---

## ADR-001 : Remplacement du format Parquet par SQLite (`data/nqcockpit.db`)

- **Date** : 2026-09-29
- **Statut** : **Adopté** (P03)
- **Auteurs / Contexte** : P03 (Couche de données et archiveur de barres)

### Contexte & Problématique
La spécification initiale de P03 prévoyait un archivage des barres intraday (1m / 5m) au format Apache Parquet partitionné par symbole et date via `pyarrow` ou `fastparquet`.
Lors des tests d'import de dépendances sous l'environnement hôte Windows (Python 3.14.6), le chargement du composant binaire compilé `pyarrow._parquet` a échoué avec l'erreur système suivante :
```text
ImportError: The pyarrow installation is not built with support for the Parquet file format
(DLL load failed while importing _parquet: Une stratégie de contrôle d'application a bloqué ce fichier.)
```
Une stratégie locale de contrôle d'application Windows (Windows AppLocker / Smart App Control / WDAC) bloque l'exécution de la DLL native de Parquet, et `fastparquet` n'est pas disponible. Conformément aux consignes de sécurité, il est strictement interdit de modifier les paramètres de sécurité de l'OS hôte ou de changer l'interpréteur Python.

### Décision
1. **Abandon de Parquet** : L'utilisation de `pyarrow.parquet`, `fastparquet` et `pandas.to_parquet` est formellement proscrite.
2. **Adoption de SQLite standard** : Tout le stockage persistant local est unifié sous **SQLite 3** (`data/nqcockpit.db`), reposant exclusivement sur le module standard `sqlite3` de la bibliothèque standard Python (garanti 100 % multiplateforme, sans dépendance C externe vulnérable aux blocages OS).
3. **Configuration technique SQLite** :
   - Fichier unique : `data/nqcockpit.db` (exclu du contrôle de version Git via `.gitignore`).
   - Journalisation haute performance : activation du mode **WAL** (`PRAGMA journal_mode=WAL;`).
   - Synchronisation optimisée : `PRAGMA synchronous=NORMAL;` et `PRAGMA foreign_keys=ON;`.
   - Gestion des migrations et évolutions : table dédiée `schema_version`.
4. **Schéma de stockage des barres (`bars`)** :
   - Clé primaire / unicité : `(symbol, interval, timestamp_utc)` garantissant l'absence totale de doublons (insertion idempotente via `INSERT OR REPLACE` ou `INSERT OR IGNORE`).
   - Horodatages : stockés rigoureusement en **UTC** (format ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` ou epoch Unix entier) ; toute restitution pour l'utilisateur est convertie à la volée en `America/New_York` (ou `Africa/Algiers` pour les fenêtres de kill zones de l'opérateur).
   - Indexation : index composite systématique `idx_bars_symbol_time` sur `(symbol, timestamp_utc)` pour garantir des requêtes de fenêtres temporelles sous la milliseconde.
   - Métadonnées de traçabilité obligatoires sur chaque enregistrement :
     - `source` : identifiant de la source (`yfinance`, `cboe`, `fred`, etc.)
     - `fetched_at_utc` : horodatage UTC du pull réseau.
     - `status` : statut de santé de la donnée (`OK`, `DEGRADED`, `BLOCKED`).
5. **Stratégie de test** :
   - Exécution des tests unitaires et d'intégration avec des bases SQLite éphémères en mémoire (`:memory:`) pour une isolation absolue et des temps d'exécution quasi-instantanés, sans dépendre du disque ni du réseau.

### Conséquences
- **Avantages** : Zéro dépendance native instable, portabilité totale, requêtes SQL relationnelles riches, schéma versionné, transactions ACID, gestion native de la concurrence en lecture (WAL).
- **Inconvénients** : Légère perte de compression par rapport à Parquet sur des dizaines de millions de lignes, largement négligeable sur l'historique intraday cible du cockpit NQ.

---

## ADR-002 : Substitution de `scipy.stats` par `math.erf` vectorisé (Contraintes Windows AppLocker)

- **Date** : 2026-09-29
- **Statut** : **Adopté** (P04)
- **Auteurs / Contexte** : P04 (Moteur de niveaux et grecs Black-Scholes)

### Contexte & Problématique
Sous l'environnement hôte Windows (Python 3.14.6), l'import de `scipy.stats` échoue avec l'erreur système suivante :
```text
ImportError: DLL load failed while importing _bglu_dense: Une stratégie de contrôle d'application a bloqué ce fichier.
```
La politique locale de contrôle d'application Windows (Windows AppLocker / Smart App Control / WDAC) bloque les binaires compilés C/Rust non signés ou spécifiques à SciPy (`_bglu_dense.pyd`, `_distance_pybind.pyd`). Conformément aux règles de sécurité, il est strictement interdit de modifier la politique de sécurité de l'OS hôte.

### Décision
1. **Abandon de `scipy.stats`** : Ne plus importer `scipy.stats` pour le calcul des grecs et distributions normales.
2. **Implémentation analytique directe dans `src/nqcockpit/levels/greeks.py`** :
   - Fonction de répartition normale $\Phi(x)$ via `math.erf` de la bibliothèque standard Python :
     $$\Phi(x) = \frac{1}{2} \left[1 + \text{erf}\left(\frac{x}{\sqrt{2}}\right)\right]$$
   - Densité normale $\phi(x)$ :
     $$\phi(x) = \frac{1}{\sqrt{2\pi}} e^{-\frac{x^2}{2}}$$
   - Fonctions vectorisées avec NumPy (`_INV_SQRT_2PI * np.exp(-0.5 * x**2)`).
3. **Équivalence mathématique** : Précision exacte machine identique à `scipy.stats.norm.cdf` et `norm.pdf`, avec zéro dépendance binaire externe C.

### Conséquences
- **Avantages** : Robustesse totale sur l'environnement hôte, aucun crash de DLL, performance vectorielle NumPy optimale, conformité aux règles de sécurité.
- **Inconvénients** : Nécessite de maintenir une implémentation explicite de 50 lignes de code mathématique dans le projet.

---

## ADR-003 : Définition rigoureuse de l'Expected Move en jours de bourse effectifs (Base 252)

- **Date** : 2026-09-29
- **Statut** : **Adopté** (P04)
- **Auteurs / Contexte** : P04 (Moteur de niveaux, Expected Move et calibration de volatilité)

### Contexte & Problématique
La formule théorique de l'Expected Move 1-sigma issue du modèle Black-Scholes est :
$$\text{Expected Move}_{1\sigma} = S \times IV_{ATM} \times \sqrt{\frac{\text{jours}}{252}}$$
Une erreur classique consiste à injecter des jours calendaires (ex: 3 jours entre vendredi soir et lundi) tout en divisant par 252 (qui est le nombre de jours ouvrés de bourse par an). Cela surestime artificiellement l'amplitude attendue du mouvement pendant le week-end et la veille de jours fériés.

### Décision
1. **Définition stricte de « jours »** :
   Dans la formule avec dénominateur 252, la variable « jours » désigne **exclusivement** les **jours de BOURSE effectifs** restants jusqu'à l'échéance selon le calendrier officiel du marché (`pandas_market_calendars`, calendrier NASDAQ).
2. **Gestion des jours non ouvrés** :
   - Du vendredi soir (après 16:00 ET) au lundi suivant : exactement **1,0 jour de bourse** (la séance du lundi).
   - Veille de jour férié (ex: mercredi soir avant Thanksgiving) pour une échéance le vendredi : exactement **1,0 jour de bourse** (le jeudi férié étant exclu).
3. **Fraction de séance pour le 0DTE (échéance le jour même)** :
   - Avant l'ouverture (avant 09:30 ET) : 1,0 jour de bourse.
   - En séance régulière (09:30 - 16:00 ET) : fraction continue de séance restante $\frac{\text{secondes restantes}}{6.5 \times 3600}$.
   - Après la clôture (après 16:00 ET) : fraction minimale $\epsilon = 0.001$.
4. **Contrôle croisé systématique** :
   L'Expected Move analytique $1\sigma$ est comparé au prix du straddle ATM du front month ($C_{ATM} + P_{ATM}$) pour valider la cohérence de marché.

---

## ADR-004 : Filtrage du bruit administratif et procédural dans le fil Live Wire (Fed RSS)

- **Date** : 2026-10-05
- **Statut** : **Adopté** (feat/dashboard-news)
- **Auteurs / Contexte** : Chef de produit / Dashboard Live Wire

### Contexte & Problématique
Le flux RSS officiel de la Réserve Fédérale (`https://www.federalreserve.gov/feeds/press_all.xml`) remonte un flux continu de dépêches. Parmi celles-ci figurent de nombreuses notifications purement administratives ou réglementaires locales sans aucun impact macroéconomique ni volatilité sur le Nasdaq (ex. : *"extend comment period on Regulation O proposal"*, *"enforcement action with Ontario Bancorporation"*, contentieux avec d'anciens employés de banques communautaires, corrections typographiques de tableaux, renouvellements de conseils consultatifs régionaux).
Ces dépêches saturaient le quota de dépêches affichées dans le bandeau Live Wire sans apporter aucune valeur décisionnelle au trader, risquant même de masquer les annonces de politique monétaire majeures.

### Décision
1. **Filtre par motifs d'exclusion explicites (liste blanche implicite par défaut)** :
   - Par défaut, toute dépêche est conservée (politique de taux, décisions FOMC, discours de gouverneurs votants, Beige Book, minutes, projections économiques SEP, bilans).
   - Seules les dépêches contenant explicitement des motifs textuels administratifs/procéduraux identifiés (`FED_ADMIN_EXCLUDE_PATTERNS`) sont écartées (`is_relevant_fed_wire_item`).
2. **Collecte exhaustive jusqu'au quota** :
   - Dans `fetch_live_news_wire`, le flux RSS est désormais parcouru jusqu'à accumuler le nombre requis de dépêches pertinentes (`max_items_per_source`), évitant ainsi qu'une série de communiqués procéduraux en tête de flux n'assèche le fil.
3. **Respect des principes du projet** :
   - Aucun biais directionnel : le filtre ne juge pas du caractère haussier ou baissier, mais uniquement de la nature opérationnelle vs macroéconomique de l'annonce.
   - Zéro donnée inventée, traçabilité et horodatage stricts préservés.

### Conséquences
- **Avantages** : Ratio signal/bruit considérablement amélioré dans le cockpit, élimination des fausses alertes sans pertinence pour le trading du contrat NQ.
- **Inconvénients / Maintenance** : La liste des motifs d'exclusion doit être enrichie si la Fed adopte de nouveaux intitulés procéduraux spécifiques.

