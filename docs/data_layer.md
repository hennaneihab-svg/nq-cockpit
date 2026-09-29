# Couche de Données et Persistance Locale (P03)

Ce document décrit l'architecture, le schéma relationnel, les protocoles d'alignement temporel et les procédures d'archivage de la couche de données de NQ Cockpit.

---

## 1. Choix Technologiques & Décisions d'Architecture

- **Moteur de stockage unifié** : SQLite 3 (`data/nqcockpit.db`), remplaçant le format Parquet suite au blocage par stratégie Windows de la DLL native `pyarrow._parquet` (voir [`docs/DECISIONS.md`](file:///c:/Users/pccom/Desktop/trading%20asistante/docs/DECISIONS.md) pour l'ADR-001).
- **Mode d'écriture** : Journalisation **WAL** (*Write-Ahead Logging*) pour des écritures non bloquantes et des lectures concurrentes rapides.
- **Règles d'horodatage** :
  - **Stockage interne** : Rigoureusement en **UTC** (format ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` ou epoch entier).
  - **Affichage & Reporting** : Converti en `America/New_York` pour les logiques de marché US, et en `Africa/Algiers` pour les fenêtres opérationnelles du trader.
- **Traçabilité obligatoire** : Chaque donnée stockée porte systématiquement son statut de santé (`OK`, `DEGRADED`, `BLOCKED`), son horodatage de source, et son heure de capture réseau.

---

## 2. Schéma Relationnel Versionné (`schema_version`)

### Table `schema_version`
Gère les migrations incrémentales :
```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
```

### Table `bars` (Barres OHLCV intraday et quotidiennes)
Clé composite d'unicité `(symbol, interval, timestamp_utc)` garantissant une idempotence totale sans doublons :
```sql
CREATE TABLE bars (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL DEFAULT 0.0,
    source TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, timestamp_utc)
);

CREATE INDEX idx_bars_symbol_time ON bars (symbol, timestamp_utc);
CREATE INDEX idx_bars_symbol_interval_time ON bars (symbol, interval, timestamp_utc);
```

### Table `snapshots`
Stocke les niveaux structuraux de marché (GEX, murs, gamma flip, expected move, base) :
```sql
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    spot REAL,
    regime TEXT,
    gamma_flip REAL,
    call_wall REAL,
    put_support REAL,
    expected_move REAL,
    basis REAL,
    synthetic_basis REAL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX idx_snapshots_time ON snapshots (timestamp_utc);
```

### Table `events` et `event_reactions`
Gestion du calendrier macroéconomique et des réactions de prix post-annonces (Tier 1 : FOMC, CPI, NFP, PCE) :
```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    timestamp_utc TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    impact TEXT NOT NULL,
    actual TEXT,
    forecast TEXT,
    previous TEXT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE event_reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    pre_price REAL,
    post_5m_price REAL,
    post_15m_price REAL,
    post_60m_price REAL,
    max_favorable REAL,
    max_adverse REAL,
    recorded_at_utc TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events (event_id)
);
```

### Table `trades` (Journal d'exécution)
Enregistrement objectif des opérations de trading, calcul du R-multiple et respect des règles :
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE NOT NULL,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    pnl REAL NOT NULL,
    r_multiple REAL NOT NULL,
    setup TEXT,
    rules_respected INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at_utc TEXT NOT NULL
);
```

### Tables `daily_state` et `forecasts`
- `daily_state` : État consolidé de la séance (régime de volatilité, biais conditionnel, niveaux clés).
- `forecasts` : Prévisions et fourchettes attendues comparées aux mouvements réels.

---

## 3. Synchronisation et Conversion NDX vers NQ (Base Future-Spot)

Conformément aux décisions de `docs/vendor_audit.md` (Section 3.1) :
1. **Séance régulière actions (09:30 - 16:00 ET)** :
   - Calcul de la base $NQ=F - \text{^NDX}$ autorisé **uniquement** sur des barres 1m synchronisées en UTC avec un écart temporel maximal $\le 60$ secondes.
   - Interdiction stricte de calculer la base sur des « derniers cours » asynchrones.
2. **Hors séance actions (pré-market, overnight, week-end)** :
   - Base de référence = dernière base de clôture régulière ($\le$ 16:00:00 ET).
   - Statut obligatoirement étiqueté : **`« base de la séance précédente »`** accompagné de son âge horodaté.
3. **Contrôle croisé par parité Call-Put synthétique** :
   - Calcul parallèle $F = (C - P)e^{rT} + K$ adapté de Darthreign/gex-dashboard (MIT) pour détecter les anomalies de cotation.

---

## 4. Détection Trimestrielle de Roll de Contrat NQ

- **Codes de contrat** : H (Mars), M (Juin), U (Septembre), Z (Décembre).
- **Date d'expiration** : 3ème vendredi du mois de fin de contrat à 09:30 ET.
- **Fenêtre de roll** : s'active 8 jours avant l'expiration (semaine du roll) pour alerter le trader de la migration des volumes vers le contrat suivant.
- **Module** : [`nqcockpit.data.roll`](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/data/roll.py).

---

## 5. Commandes CLI pour la Couche de Données

```powershell
# Appliquer les migrations du schéma SQLite
.\.venv\Scripts\python.exe -m nqcockpit data migrate

# Consulter l'état de roll du contrat NQ en cours
.\.venv\Scripts\python.exe -m nqcockpit data roll

# Archiver les barres intraday dans SQLite
.\.venv\Scripts\python.exe -m nqcockpit data archive

# Afficher les statistiques de la base locale
.\.venv\Scripts\python.exe -m nqcockpit data status
```

---

## 6. Retard Mesuré et Logique de Péremption Unifiée

- **Retard mesuré sur `NQ=F` (Yahoo Finance)** :
  - En séance et continu, l'endpoint gratuit de Yahoo Finance sur `NQ=F` accuse un retard structurel mesuré de **10 à 15 minutes** par rapport au temps réel CME Globex.
  - Ce retard est une caractéristique inhérente du flux gratuit public, et ne constitue pas une panne réseau.
- **Règle de péremption unifiée** :
  - Configuration : `symbols_expected_delay_minutes: {"NQ=F": 15}` et `delay_margin_minutes: 10`.
  - Tolérance totale admissible : $15 + 10 = 25\text{ minutes}$.
  - Si l'âge de la dernière barre $\le 25\text{ min}$ : statut **`OK`** avec mention explicite `« source retardée d'environ N min »`.
  - Si l'âge dépasse $25\text{ min}$ : statut **`DÉGRADÉ`** avec mention `« donnée périmée »`.
  - Si aucune donnée n'est récupérée : statut **`BLOQUÉ`**.
