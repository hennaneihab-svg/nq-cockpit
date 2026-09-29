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
