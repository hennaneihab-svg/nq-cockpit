# NQ Cockpit — Desk de Trading & Assistant Préparation / Discipline

Outil local de préparation, d'aide à la décision contextuelle, de contrôle de la discipline et de mesure pour le trading des contrats à terme Nasdaq (NQ / MNQ).

Conçu selon des principes stricts :
- **100 % gratuit** : aucune API payante requise, résilient et testé pour un accès depuis l'Algérie avec plans B / fallbacks intégrés.
- **Strictement non-directionnel** : aucun signal d'achat/vente ou biais haussier/baissier. Cartographie des régimes de volatilité, niveaux de gamma, probabilités empiriques et scénarios conditionnels « Si... Alors... ».
- **Honnêteté des données** : aucune valeur inventée ou extrapolée. Tout chiffre affiche sa source, son horodatage et son âge. En cas d'indisponibilité, le statut est explicitement affiché **DÉGRADÉ**.
- **Gestion temporelle multi-fuseaux** : logique de marché calculée en `America/New_York` (zoneinfo dynamique, gestion DST), restitution d'affichage en heure locale `Africa/Algiers`.

---

## Démarrage Rapide

Pour lancer à la fois le planificateur de tâches d'arrière-plan (APScheduler) et l'interface utilisateur unifiée :

```bash
python -m nqcockpit run
```

Options disponibles :
- `--port 8501` : Port d'écoute pour l'interface web (défaut : 8501).
- `--no-ui` : Exécute uniquement le planificateur en tâche de fond.
- `--dry-run` : Valide l'instanciation des tâches sans action bloquante.

Interface accessible sur : `http://localhost:8501`

---

## Routine Quotidienne d'Utilisation

Le workflow du trader s'articule autour de 4 rendez-vous clés calés sur les heures d'Alger (`Africa/Algiers`) :

| Heure (Alger) | Heure (New York) | Étape | Action & Objectif |
|---|---|---|---|
| **13h00** | 08h00 ET | **Lecture du Cockpit** | Consulter le briefing pré-séance, le profil du jour, les régimes Gamma (P04) et Volatilité (P07), ainsi que le radar d'événements Tier 1 (P05). |
| **14h45** | 09h45 ET | **Rafraîchissement Niveaux** | Observer l'Open US et le déplacement effectif des Call/Put Walls et du Gamma Flip. Consulter la consommation de l'Expected Move journalier. |
| **15h15** | 10h15 ET | **Checklist de Discipline** | Valider formellement la checklist pré-session avant la première Kill Zone (15h30–17h00). Contrôler le dimensionnement de position et le verrou de perte max journalière (-2R). |
| **Après la clôture** | Après 16h00 ET | **Journalisation & Coaching** | Enregistrer les trades exécutés dans le journal de bord (setup, respect du plan, R réalisé). Analyser les métriques de discipline et les alertes de tilt (P11). |

---

## Sections de l'Interface Multipage

1. **Cockpit Live** (`[01] COCKPIT LIVE`) :
   - Vue synthétique du profil de séance : statut autorisé vs NO-TRADE, compte à rebours macro, régime gamma, expected move.
   - Niveaux clés structuraux (Call Wall, Put Support, Gamma Flip, Overnight Range).
   - Carte de scénarios conditionnels « Si... Alors... » et fil de presse macro en direct.

2. **Journal de Bord** (`[02] JOURNAL DE BORD`) :
   - Enregistrement structuré des transactions (prix d'entrée, stop, cible, R réalisé, respect du plan).
   - Export CSV conforme ATAS / TradingView.

3. **Discipline & Sizing** (`[03] DISCIPLINE & SIZING`) :
   - Checklist pré-session bloquante.
   - Calculateur de taille de position selon le risque en capital (1R) et le stop en points.
   - Surveillance en direct du cooldown post-stop-loss et du verrou de perte max.

4. **Coaching & Analytics** (`[04] COACHING & ANALYTICS`) :
   - Mesure objective de l'edge (espérance, win rate, profit factor, intervalles de Wilson).
   - Détection automatique des comportements de tilt (vengeance trading, sur-trading, taille anormale).

5. **Briefing Pré-séance** (`[05] BRIEFING PRE-SEANCE`) :
   - Synthèse consolidée matinale pour préparer la journée de trading en quelques secondes.

---

## Commandes CLI Principales

```bash
# Vérification de l'état des sources de données gratuites
python -m nqcockpit check-sources

# Déclenchement d'un snapshot immédiat (niveaux gamma, chaînes CBOE, cours NQ)
python -m nqcockpit snapshot

# Calcul et affichage du profil de séance complet
python -m nqcockpit profile

# Radar des événements macroéconomiques
python -m nqcockpit events

# Statut de la porte de discipline
python -m nqcockpit discipline status

# Génération du briefing pré-séance en console
python -m nqcockpit briefing --dry-run
```
