# Rapport de validation P06 — Event Playbook & Intelligence Fed

### 1. Prochain Tier 1 : Fiche NFP 02/10 (`nqcockpit playbook card --json`)
```json
{
  "event_name": "NFP",
  "tier": 1,
  "scheduled_utc": "2026-10-02T12:30:00+00:00",
  "scheduled_et": "2026-10-02 08:30 ET",
  "scheduled_algiers": "2026-10-02 13:30 Alger",
  "countdown": "dans 1j 18h 1m",
  "generation_trigger": "J-2",
  "generated_at_utc": "2026-09-30T18:28:38.395677+00:00",
  "consensus": "90K",
  "consensus_status": "OK",
  "previous": "162K",
  "previous_status": "OK",
  "consensus_source": "ForexFactory",
  "date_origin": "ForexFactory",
  "time_provenance": "ForexFactory (08:30 ET)",
  "stand_aside_before_minutes": 5,
  "wait_after_minutes": 3,
  "post_event_buffer_minutes": 90,
  "positioning": {
    "status": "DÉGRADÉ",
    "status_detail": "LevelsSnapshot non disponible"
  },
  "reaction_stats": {
    "+1m": {"n": 0, "is_sufficient": false, "note": "échantillon insuffisant"},
    "+5m": {"n": 0, "is_sufficient": false, "note": "échantillon insuffisant"},
    "+15m": {"n": 0, "is_sufficient": false, "note": "échantillon insuffisant"},
    "+60m": {"n": 0, "is_sufficient": false, "note": "échantillon insuffisant"}
  },
  "scenarios": [
    {
      "label": "en_ligne",
      "protocol": "Stand aside 5 min avant. Attendre 3 min après. Buffer 90 min. Attendre clôture bougie M5."
    },
    {
      "label": "chaud",
      "protocol": "Stand aside 5 min avant. Attendre 3 min après. Buffer 90 min. Attendre M5. Réduire taille si vol > expected move."
    },
    {
      "label": "froid",
      "protocol": "Stand aside 5 min avant. Attendre 3 min après. Buffer 90 min. Attendre M5. Réduire taille si vol > expected move."
    }
  ],
  "status": "DÉGRADÉ"
}
```

### 2. Diff FOMC réel (`federalreserve.gov` : 29/07/2026 vs 16/09/2026)
* **Phrases ajoutées :**
  - `[+] The FOMC approved the following statement for release by a 12 – 0 vote`
  - `[+] While uncertainty remains elevated owing, in part, to geopolitical developments, domestic spending has been resilient.`
  - `[+] Productivity growth is strong, and capital investment is robust.`
  - `[+] Inflation remains elevated.`
  - `[+] Today's policy action will support a timelier return to the Committee's 2 percent goal.`
* **Phrases retirées :**
  - `[-] The FOMC approved the following statement for release by a 9 – 3 vote`
  - `[-] ...elevated uncertainty that owes, in part, to the conflict in the Middle East.`
  - `[-] Productivity growth and capital investment are strong.`
  - `[-] Inflation remains elevated relative to the Committee's 2 percent goal, in part reflecting supply shocks...`
  - `[-] Voting against the monetary policy action were Beth M. Hammack, Neel Kashkari, and Lorie K. Logan...`

### 3. Lecture de ton (Gabarit sans LLM)
* **Ton :** `neutre`
* **Mention obligatoire :** `"aide de lecture, pas un signal"`
* **Extrait justificatif :** `"[+] Inflation remains elevated."`

### 4. Fiche Minutes (`nqcockpit playbook minutes-watch`)
* **Publication :** 2026-10-07 14:00 ET | 2026-10-07 19:00 Alger (DST/fuseaux dynamiques via `ZoneInfo`)
* **Taux DGS2 (proxy anticipations) :** `4.92%` (date d'observation : 2026-09-28, extrait direct FRED)
* **Statut :** `OK`
* **Thèmes :** `• Inflation remains elevated.`

### 5. Validateur anti-hallucination (Garde-fou testé)
```python
# Entrée JSON
source_json = {"added_count": 9, "removed_count": 10, "tone": "neutre"}

# 1. Texte conforme -> True
validate_llm_output("Le diff contient 9 phrases ajoutees et 10 retirees.", source_json)
# => True

# 2. Texte piégé (5.75% et 42000 absents de la source) -> False
validate_llm_output("Le taux cible est à 5.75% avec un risque de 42000 points.", source_json)
# => False (Log: "GARDE-FOU LLM — nombres absents du JSON source: ['42000', '5.75']")
```

### 6. Paramètres de protocole (`config.yaml:19-23`)
```yaml
events:
  post_event_buffer_minutes: 90
  stand_aside_before_minutes: 5
  wait_after_minutes: 3
```

### 7. Contrôles qualité & Commit
* `pytest -v` : **147 passed** (13.02s)
* `ruff check` : **0 error**
* `Commit` : `36c43db` (`P06: Event Playbook & Intelligence Fed avec validation anti-hallucination et statuts explicites`)
* `git status` : `working tree clean`

### 8. Confirmation protocoles « chaud » vs « froid »
Les protocoles de gestion du risque sont identiques par conception (réduction de taille si volatilité > expected move dans les deux sens de surprise, symétrie stricte sans biais directionnel), tandis que la différenciation réside dans ce qui est surveillé (Call Wall et borne haute vs Put Support et borne basse).
