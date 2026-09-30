"""Tests P06 — Event Playbook.

Couvre :
- ReactionStats : is_sufficient=False si n < 12 (test_reaction_stats_insufficient_sample)
- ReactionStats : statistiques calculées si n >= 12 (test_reaction_stats_sufficient_sample)
- validate_llm_output : rejette un nombre halluciné (test_llm_validator_rejects_hallucinated_number)
- validate_llm_output : accepte une sortie valide (test_llm_validator_accepts_valid_output)
- diff_statements : détecte les ajouts/retraits (test_fomc_diff_adds_removes)
- generate_card : fiche NFP avec échantillon insuffisant (test_card_generation_nfp)
- Migration 2 : colonnes p06 ajoutées idempotement (test_migration2_p06_columns)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_in_memory_db_v1() -> sqlite3.Connection:
    """Crée une DB :memory: avec le schéma migration 1 uniquement."""
    from nqcockpit.data.db import MIGRATIONS, get_db_connection

    conn = get_db_connection(":memory:")
    # Appliquer seulement la migration 1
    migration_1 = [(v, n, stmts) for v, n, stmts in MIGRATIONS if v == 1]
    for version, name, statements in migration_1:
        with conn:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now(UTC).isoformat()),
            )
    return conn


def _make_in_memory_db_full() -> sqlite3.Connection:
    """Crée une DB :memory: avec toutes les migrations appliquées."""
    from nqcockpit.data.db import apply_migrations, get_db_connection

    conn = get_db_connection(":memory:")
    apply_migrations(conn)
    return conn


def _insert_fake_event(conn: sqlite3.Connection, event_id: str, name: str) -> None:
    """Insère un événement fictif dans la table events."""
    conn.execute(
        """
        INSERT OR IGNORE INTO events
            (event_id, timestamp_utc, name, currency, impact, source, status, created_at_utc)
        VALUES (?, ?, ?, 'USD', 'HIGH', 'test', 'OK', ?)
        """,
        (event_id, datetime.now(UTC).isoformat(), name, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def _insert_fake_reaction(
    conn: sqlite3.Connection,
    event_id: str,
    pre: float,
    post_1m: float,
    post_5m: float,
    post_15m: float,
    post_60m: float,
) -> None:
    """Insère une réaction fictive dans event_reactions (schéma P06)."""
    conn.execute(
        """
        INSERT INTO event_reactions
            (event_id, pre_price, post_1m_price, post_5m_price, post_15m_price,
             post_60m_price, max_favorable, max_adverse, recorded_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            pre,
            post_1m,
            post_5m,
            post_15m,
            post_60m,
            abs(post_60m - pre),
            None,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Test 1 : échantillon insuffisant (n < 12)
# ---------------------------------------------------------------------------


def test_reaction_stats_insufficient_sample():
    """Si n < 12, is_sufficient=False et note='échantillon insuffisant'."""
    from nqcockpit.playbook.reaction import compute_reaction_stats

    conn = _make_in_memory_db_full()
    _insert_fake_event(conn, "NFP-2026-10-02", "NFP")

    # Insérer seulement 5 réactions (< 12)
    for i in range(5):
        _insert_fake_reaction(conn, "NFP-2026-10-02", 20000.0, 20010.0, 20020.0, 20030.0, 20050.0)

    stats = compute_reaction_stats("NFP", [], conn, min_event_samples=12)

    for horizon in ["+1m", "+5m", "+15m", "+60m"]:
        assert horizon in stats, f"Horizon {horizon} manquant"
        rs = stats[horizon]
        assert rs.is_sufficient is False, f"{horizon}: is_sufficient devrait être False"
        assert "insuffisant" in rs.note, f"{horizon}: note incorrecte: {rs.note!r}"
        assert rs.median_pts is None, f"{horizon}: median_pts devrait être None"

    conn.close()


# ---------------------------------------------------------------------------
# Test 2 : échantillon suffisant (n >= 12)
# ---------------------------------------------------------------------------


def test_reaction_stats_sufficient_sample():
    """Si n >= 12, is_sufficient=True et statistiques calculées."""
    from nqcockpit.playbook.reaction import compute_reaction_stats

    conn = _make_in_memory_db_full()
    _insert_fake_event(conn, "NFP-2026-test", "NFP")

    # Insérer 15 réactions avec des mouvements connus
    base = 20000.0
    for i in range(15):
        delta = float(i * 10)  # +0, +10, +20 … +140 pts
        _insert_fake_reaction(
            conn,
            "NFP-2026-test",
            base,
            base + delta * 0.2,
            base + delta * 0.5,
            base + delta * 0.8,
            base + delta,
        )

    stats = compute_reaction_stats("NFP", [], conn, min_event_samples=12)

    for horizon in ["+5m", "+15m", "+60m"]:
        rs = stats[horizon]
        assert rs.is_sufficient is True, f"{horizon}: is_sufficient devrait être True (n={rs.n})"
        assert rs.n >= 12, f"{horizon}: n={rs.n} < 12"
        assert rs.median_pts is not None, f"{horizon}: median_pts ne devrait pas être None"
        assert rs.q25_pts is not None
        assert rs.q75_pts is not None

    conn.close()


# ---------------------------------------------------------------------------
# Test 3 : garde-fou LLM — rejette un nombre halluciné
# ---------------------------------------------------------------------------


def test_llm_validator_rejects_hallucinated_number():
    """Un nombre absent du JSON source doit être rejeté par validate_llm_output."""
    from nqcockpit.playbook.fed_intelligence import validate_llm_output

    source_json = {
        "added_count": 3,
        "removed_count": 1,
        "tone": "neutre",
    }
    # Texte qui contient 99999 — absent du JSON
    hallucinated_text = "Le taux attendu est de 99999 points de base selon notre analyse."
    result = validate_llm_output(hallucinated_text, source_json)
    assert result is False, "Le garde-fou devrait rejeter le nombre halluciné 99999"


# ---------------------------------------------------------------------------
# Test 4 : garde-fou LLM — accepte une sortie valide
# ---------------------------------------------------------------------------


def test_llm_validator_accepts_valid_output():
    """Un texte ne contenant que des nombres présents dans le JSON est accepté."""
    from nqcockpit.playbook.fed_intelligence import validate_llm_output

    source_json = {
        "added_count": 5,
        "removed_count": 2,
        "dgs2_rate": 4.32,
    }
    valid_text = "Le diff contient 5 phrases ajoutées et 2 retirées."
    result = validate_llm_output(valid_text, source_json)
    assert result is True, "Le garde-fou devrait accepter ce texte valide"


# ---------------------------------------------------------------------------
# Test 5 : diff_statements (sur textes locaux, pas de réseau)
# ---------------------------------------------------------------------------


def test_fomc_diff_adds_removes():
    """diff_statements détecte les phrases ajoutées et retirées correctement."""
    from nqcockpit.playbook.fed_intelligence import _split_sentences, _word_diff

    prev = (
        "Inflation remains elevated above the Committee's longer-run goal. "
        "The labor market remains tight."
    )
    curr = (
        "Inflation has eased over the past year. "
        "The labor market remains tight. "
        "The Committee will continue to monitor incoming data carefully."
    )

    prev_s = _split_sentences(prev)
    curr_s = _split_sentences(curr)
    added, removed = _word_diff(prev_s, curr_s)

    assert any("eased" in s.lower() for s in added), (
        "La phrase sur l'inflation apaisée doit être détectée comme ajoutée"
    )
    assert any("elevated" in s.lower() for s in removed), (
        "La phrase sur l'inflation élevée doit être détectée comme retirée"
    )
    assert any("monitor" in s.lower() for s in added), (
        "La phrase sur le monitoring doit être ajoutée"
    )


# ---------------------------------------------------------------------------
# Test 6 : generate_card NFP — fiche avec échantillon insuffisant
# ---------------------------------------------------------------------------


def test_card_generation_nfp():
    """Fiche NFP générée correctement avec échantillon insuffisant (n=0)."""
    from datetime import timedelta

    from nqcockpit.events.models import CalendarEvent, DataStatus
    from nqcockpit.playbook.card import generate_card

    now_utc = datetime.now(UTC)
    # Simuler un NFP dans 2 jours (J-2)
    nfp_utc = now_utc + timedelta(days=2, hours=3)

    event = CalendarEvent(
        name="NFP",
        tier=1,
        scheduled_utc=nfp_utc,
        source="bls",
        consensus="200K",
        previous="177K",
        consensus_source="ForexFactory",
        time_provenance="table versionnée BLS (08:30 ET)",
        verified=True,
        status=DataStatus.OK,
    )

    conn = _make_in_memory_db_full()
    card = generate_card(
        event=event,
        levels_snapshot=None,
        bars_nq_1m=[],
        db_conn=conn,
        min_event_samples=12,
        stand_aside_before_minutes=5,
        wait_after_minutes=3,
        post_event_buffer_minutes=90,
        now_utc=now_utc,
    )
    conn.close()

    assert card.event_name == "NFP"
    assert card.tier == 1
    assert card.generation_trigger == "J-2"
    assert card.consensus == "200K"
    assert card.previous == "177K"

    # Positionnement DÉGRADÉ (pas de LevelsSnapshot)
    assert card.positioning is not None
    assert card.positioning.status == "DÉGRADÉ"

    # Réactions insuffisantes (n=0)
    for h in ["+1m", "+5m", "+15m", "+60m"]:
        assert h in card.reaction_stats
        rs = card.reaction_stats[h]
        assert rs.is_sufficient is False
        assert rs.n == 0

    # 3 scénarios (en_ligne, chaud, froid)
    labels = [s.label for s in card.scenarios]
    assert "en_ligne" in labels
    assert "chaud" in labels
    assert "froid" in labels

    # Protocole présent
    for sc in card.scenarios:
        assert "Stand aside" in sc.protocol

    assert card.consensus_status == "OK"
    assert card.previous_status == "OK"

    # JSON sérialisable
    from nqcockpit.playbook.card import card_to_dict

    d = card_to_dict(card)
    assert d["event_name"] == "NFP"
    assert d["consensus_status"] == "OK"
    assert d["previous_status"] == "OK"
    assert d["positioning"]["status"] == "DÉGRADÉ"


# ---------------------------------------------------------------------------
# Test 6b : consensus ou previous null -> statut explicite (jamais de null nu)
# ---------------------------------------------------------------------------


def test_card_generation_null_consensus_has_explicit_status():
    """Quand consensus ou previous est null, consensus_status/previous_status est explicite."""
    from datetime import timedelta

    from nqcockpit.events.models import CalendarEvent, DataStatus
    from nqcockpit.playbook.card import card_to_dict, generate_card

    now_utc = datetime.now(UTC)

    # 1. Événement sans consensus par nature (FOMC Minutes)
    min_event = CalendarEvent(
        name="FOMC Minutes",
        tier=1,
        scheduled_utc=now_utc + timedelta(days=5),
        source="fed_html",
        consensus=None,
        previous=None,
        status=DataStatus.OK,
    )
    conn = _make_in_memory_db_full()
    card_min = generate_card(event=min_event, levels_snapshot=None, bars_nq_1m=[], db_conn=conn)
    d_min = card_to_dict(card_min)
    assert d_min["consensus"] is None
    assert "non fourni pour ce type d'événement" in d_min["consensus_status"]
    assert d_min["previous"] is None
    assert "non fourni pour ce type d'événement" in d_min["previous_status"]

    # 2. Événement économique (NFP) où ForexFactory est indisponible (HTTP 429)
    nfp_event = CalendarEvent(
        name="NFP",
        tier=1,
        scheduled_utc=now_utc + timedelta(days=2),
        source="static",
        consensus=None,
        previous=None,
        status=DataStatus.OK,
    )
    source_health = {"forexfactory": "HTTP Error 429: Too Many Requests"}
    card_nfp = generate_card(
        event=nfp_event,
        levels_snapshot=None,
        bars_nq_1m=[],
        db_conn=conn,
        source_health_map=source_health,
    )
    d_nfp = card_to_dict(card_nfp)
    assert d_nfp["consensus"] is None
    assert "HTTP Error 429" in d_nfp["consensus_status"]
    assert d_nfp["previous"] is None
    assert "HTTP Error 429" in d_nfp["previous_status"]
    conn.close()


# ---------------------------------------------------------------------------
# Test 7 : migration 2 — colonnes P06 ajoutées idempotement
# ---------------------------------------------------------------------------


def test_migration2_p06_columns():
    """Migration 2 : post_1m_price, surprise, range_vs_expected_move ajoutés idempotement."""
    from nqcockpit.data.db import apply_migrations, get_db_connection

    conn = get_db_connection(":memory:")

    # Appliquer toutes les migrations deux fois — doit être idempotent
    apply_migrations(conn)
    n2 = apply_migrations(conn)

    assert n2 == 0, f"La deuxième passe devrait ne rien appliquer (appliqué: {n2})"

    # Vérifier que les colonnes existent
    cur = conn.execute("PRAGMA table_info(event_reactions)")
    cols = {row[1] for row in cur.fetchall()}

    assert "post_1m_price" in cols, "post_1m_price manquant"
    assert "surprise" in cols, "surprise manquant"
    assert "range_vs_expected_move" in cols, "range_vs_expected_move manquant"

    conn.close()
