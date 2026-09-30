# Rapport P10 Reliquat — Élément 3/3 : Sauvegarde transactionnelle et politique de rétention SQLite

**Date :** 30 septembre 2026  
**Branche :** `master`  
**Statut :** Validé (231/231 tests passés, ruff 0 défaut) — en attente de validation utilisateur avant commit.

---

## 1. Objectifs & Exigences Réalisées

1. **Sauvegarde transactionnelle sécurisée (`sqlite3` backup API) :**
   - Évite les risques de corruption liés à une simple copie de fichier sous mode WAL (`PRAGMA journal_mode=WAL`).
   - Effectue un checkpoint WAL passif et s'appuie sur `src_conn.backup(dest_conn)` pour transférer proprement les pages de la base active vers un fichier temporaire isolé.
   - Nom de fichier normalisé et horodaté par session : `nqcockpit_YYYY-MM-DD.db` (basé sur la timezone d'affichage `Africa/Algiers`).

2. **Vérification d'intégrité post-sauvegarde (`PRAGMA integrity_check`) :**
   - Avant toute promotion de la sauvegarde temporaire, ouverture de la destination et exécution de `PRAGMA integrity_check`.
   - Si le résultat diffère de `[('ok',)]` :
     - Statut **DÉGRADÉ** immédiat avec message d'erreur explicite.
     - Suppression immédiate du fichier temporaire altéré.
     - Aucune ancienne sauvegarde n'est purgée.
     - Si une sauvegarde valide du jour existait déjà, elle est préservée intacte.

3. **Idempotence & Remplacement atomique (`os.replace`) :**
   - Si la commande de sauvegarde est exécutée plusieurs fois le même jour, aucun fichier doublon n'est créé.
   - La sauvegarde existante est remplacée atomiquement uniquement après validation complète de l'intégrité de la nouvelle copie.

4. **Politique de rétention configurable (`backup_retention_days`) :**
   - Configuration centralisée dans [config.yaml](file:///c:/Users/pccom/Desktop/trading%20asistante/config.yaml) sous `data.backup_retention_days` (défaut : 30 jours) et `data.backup_dir` (défaut : `data/backups`).
   - Surcharge possible par variable d'environnement (`NQ_DATA_BACKUP_DIR`) pour l'isolation parfaite des tests.
   - Les sauvegardes strictement antérieures à `target_date - retention_days` sont purgées, et leur liste est retournée dans le résumé.
   - Les fichiers ne respectant pas le motif `nqcockpit_*.db` sont strictement ignorés.

5. **Interface en ligne de commande :**
   - Commande : `nqcockpit journal backup [--dir DOSSIER] [--retention-days JOURS]`.
   - Résumé clair affichant le statut (OK / DÉGRADÉ), chemin absolu, taille en octets/KB, résultat d'intégrité, mode (création / remplacement idempotent) et nombre de fichiers purgés.

---

## 2. Fichiers Modifiés & Créés

- [config.yaml](file:///c:/Users/pccom/Desktop/trading%20asistante/config.yaml) : ajout de `backup_dir` et `backup_retention_days` dans la section `data`.
- [src/nqcockpit/config.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/config.py) : support de `backup_dir` et `backup_retention_days` dans `DataConfig` avec validation `>= 1` et prise en charge de `NQ_DATA_BACKUP_DIR`.
- [src/nqcockpit/journal/backup.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/journal/backup.py) : nouveau module implémentant `create_journal_backup` et `BackupResult`.
- [src/nqcockpit/journal/__init__.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/journal/__init__.py) : export public de `BackupResult` et `create_journal_backup`.
- [src/nqcockpit/cli.py](file:///c:/Users/pccom/Desktop/trading%20asistante/src/nqcockpit/cli.py) : intégration du sous-parseur `backup` et du gestionnaire d'affichage associé.
- [tests/test_p10_backup.py](file:///c:/Users/pccom/Desktop/trading%20asistante/tests/test_p10_backup.py) : 7 tests unitaires dédiés.

---

## 3. Matrice de Tests (Module `tests/test_p10_backup.py`)

| Test | Scénario | Résultat |
| :--- | :--- | :--- |
| `test_backup_valid_integrity_ok` | Sauvegarde normale, vérification d'intégrité `ok`, cohérence des trades | ✅ Validé |
| `test_backup_idempotent_overwrite` | 2 sauvegardes le même jour : remplacement atomique sans fichier doublon | ✅ Validé |
| `test_backup_retention_policy_prunes_strictly_older` | Purge des sauvegardes > 30 jours, conservation des récentes et autres fichiers | ✅ Validé |
| `test_backup_integrity_failure_degraded_and_no_prune` | Détection de corruption, statut DÉGRADÉ, aucune purge effectuée | ✅ Validé |
| `test_backup_source_missing_degraded` | Source SQLite inexistante -> statut DÉGRADÉ propre | ✅ Validé |
| `test_backup_cli_success` | Appel CLI `nqcockpit journal backup`, sortie console et code 0 | ✅ Validé |
| `test_backup_cli_degraded` | Appel CLI avec source inexistante, sortie DÉGRADÉ et code 1 | ✅ Validé |

---

## 4. Bilan Global du Reliquat P10

Avec ce 3e élément, les 3 éléments du reliquat P10 sont achevés :
1. ✅ **Élément 1/3 (Import CSV) :** import avec tolérance aux colonnes optionnelles, mapping `entry_time_ny`/`exit_time_ny` et dédoublonnage contextuel.
2. ✅ **Élément 2/3 (Captures d'écran) :** attachement CLI / CSV / Streamlit, normalisation absolue, statut dégradé explicite si fichier introuvable.
3. ✅ **Élément 3/3 (Sauvegarde & Rétention SQLite) :** copie transactionnelle en ligne, vérification d'intégrité, idempotence et purge automatique configurable.
