"""Tests de validation empirique, durcissement et audit (P14).

Couvre :
- Registre immuable d'hypothèses et détection d'altération (H1 à H4).
- Barrière stricte d'échantillon (refus formel sous 60 séances ou 12 événements).
- Ajustement multi-tests FWER de Holm-Bonferroni.
- Génération du rapport de laboratoire reports/lab.md.
- Sauvegarde / restauration sécurisée SQLite.
- Résilience aux pannes réseau et dégradation contrôlée.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from nqcockpit.lab.validate import (
    HypothesisRegistry,
    StatisticalValidator,
    generate_lab_report,
)


def test_registry_loading_and_hypotheses():
    """Vérifie le chargement complet des 4 hypothèses figées et leur empreinte."""
    reg = HypothesisRegistry()
    assert reg.version == "1.0.0"
    assert len(reg.fingerprint) == 64  # SHA-256 hex string

    ids = reg.all_ids()
    assert ids == ["H1", "H2", "H3", "H4"]

    h1 = reg.get("H1")
    assert "Gamma Négatif" in h1.title
    assert h1.created_at == "2026-10-04T20:00:00Z"
    assert h1.frozen_parameters["min_sessions_required"] == 60
    assert h1.directional_bias == "NONE"

    for hid in ["H1", "H2", "H3", "H4"]:
        assert reg.get(hid).created_at == "2026-10-04T20:00:00Z"

    h4 = reg.get("H4")
    assert h4.frozen_parameters["min_touches_required"] == 60


def test_registry_tampering_and_unknown_id():
    """Vérifie la détection d'hypothèse inconnue et d'altération de fichier."""
    reg = HypothesisRegistry()
    with pytest.raises(KeyError):
        reg.get("H99_INCONNUE")

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write("version: '1.0.0'\ncreated_at: '2026-10-04'\nhypotheses: []")
        temp_path = f.name

    try:
        temp_reg = HypothesisRegistry(temp_path)
        assert temp_reg.all_ids() == []
        assert temp_reg.fingerprint != reg.fingerprint
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_h1_sample_size_guard():
    """Vérifie le refus de conclure sur H1 si n < 60 séances."""
    validator = StatisticalValidator()

    # Seulement 20 séances (10 négatif, 10 positif) -> < 60
    neg_ranges = [180.0, 210.0, 195.0, 220.0, 190.0, 205.0, 215.0, 198.0, 202.0, 210.0]
    pos_ranges = [110.0, 120.0, 105.0, 115.0, 125.0, 108.0, 112.0, 118.0, 122.0, 114.0]

    res = validator.validate_h1_gamma_regime(neg_ranges, pos_ranges)
    assert res.status == "INSUFFICIENT_SAMPLE"
    assert res.sample_size == 20
    assert "Interdiction de conclure" in res.details
    assert res.p_value_raw is None


def test_h1_sufficient_sample_confirmed():
    """Vérifie la confirmation statistique de H1 avec n >= 60 et grand effet."""
    validator = StatisticalValidator()
    rng = np.random.default_rng(42)

    # 35 négatif (moyenne 210) vs 35 positif (moyenne 120) -> n=70
    neg_ranges = rng.normal(loc=210.0, scale=25.0, size=35).tolist()
    pos_ranges = rng.normal(loc=120.0, scale=20.0, size=35).tolist()

    res = validator.validate_h1_gamma_regime(neg_ranges, pos_ranges)
    assert res.status == "CONFIRMED"
    assert res.sample_size == 70
    assert res.p_value_raw is not None
    assert res.p_value_raw < 0.001
    assert res.effect_size is not None
    assert res.effect_size > 1.5  # Très fort effet


def test_h2_sample_size_guard_and_validation():
    """Vérifie la barrière d'échantillon et le test sur H2."""
    validator = StatisticalValidator()

    # n < 60 -> refus
    res_small = validator.validate_h2_above_flip([100.0] * 15, [180.0] * 15)
    assert res_small.status == "INSUFFICIENT_SAMPLE"

    # n >= 60
    rng = np.random.default_rng(101)
    above = rng.normal(loc=115.0, scale=18.0, size=32).tolist()
    below = rng.normal(loc=175.0, scale=22.0, size=32).tolist()

    res_large = validator.validate_h2_above_flip(above, below)
    assert res_large.status == "CONFIRMED"
    assert res_large.sample_size == 64
    assert res_large.effect_size is not None
    assert res_large.effect_size < -0.5


def test_h3_tier1_event_threshold():
    """Vérifie le seuil strict de 12 événements Tier 1 pour H3."""
    validator = StatisticalValidator()

    # 8 événements Tier 1 même avec 55 séances régulières (total 63) -> refus car < 12 events
    t1_small = [240.0] * 8
    reg_large = [130.0] * 55
    res = validator.validate_h3_tier1_events(t1_small, reg_large)
    assert res.status == "INSUFFICIENT_SAMPLE"
    assert "8 événements Tier 1" in res.details

    # 14 événements Tier 1 + 50 régulières = 64 séances -> éligible
    rng = np.random.default_rng(202)
    t1_valid = rng.normal(loc=260.0, scale=35.0, size=14).tolist()
    reg_valid = rng.normal(loc=140.0, scale=20.0, size=50).tolist()

    res_valid = validator.validate_h3_tier1_events(t1_valid, reg_valid)
    assert res_valid.status == "CONFIRMED"
    assert res_valid.sample_size == 64


def test_h4_wall_reaction_binomial():
    """Vérifie le test binomial exact sur les touches de murs."""
    validator = StatisticalValidator()

    # touches < 60 -> refus
    res_small = validator.validate_h4_wall_reactions(reaction_count=20, total_touches=30)
    assert res_small.status == "INSUFFICIENT_SAMPLE"

    # 58 réactions sur 80 touches -> p-value significative vs 0.50
    res_large = validator.validate_h4_wall_reactions(
        reaction_count=58, total_touches=80, baseline_rate=0.50
    )
    assert res_large.status == "CONFIRMED"
    assert res_large.sample_size == 80
    assert res_large.p_value_raw is not None
    assert res_large.p_value_raw < 0.001
    assert res_large.effect_size is not None
    assert res_large.effect_size > 0.20


def test_holm_bonferroni_correction():
    """Vérifie le contrôle d'erreur FWER séquentiel de Holm."""
    # Hypothèses avec p-values brutes simulées
    raw = [0.01, 0.04, 0.005, 0.20]
    # Tri croissant : 0.005 (x4 = 0.02), 0.01 (x3 = 0.03), 0.04 (x2 = 0.08), 0.20 (x1 = 0.20)
    adj = StatisticalValidator.adjust_p_values_holm(raw)

    assert len(adj) == 4
    # La plus petite (index 2: 0.005) doit donner 0.02
    assert pytest.approx(adj[2], 0.001) == 0.02
    # La suivante (index 0: 0.01) doit donner 0.03
    assert pytest.approx(adj[0], 0.001) == 0.03
    # Propriété de monotonicité : adj[i] >= raw[i]
    for r, a in zip(raw, adj):
        assert a >= r


def test_generate_lab_report(tmp_path: Path):
    """Vérifie la génération complète du rapport reports/lab.md."""
    reg = HypothesisRegistry()
    validator = StatisticalValidator()

    # Créer un jeu mixte avec statut insuffisant et un résultat simulé
    r1 = validator.validate_h1_gamma_regime(
        [190.0, 195.0, 185.0, 200.0, 192.0],
        [110.0, 115.0, 108.0, 112.0, 114.0],
    )
    r2 = validator.validate_h2_above_flip(
        [120.0 + i for i in range(35)], [180.0 + i for i in range(35)]
    )
    r3 = validator.validate_h3_tier1_events(
        [250.0, 260.0, 245.0, 255.0], [130.0 + i for i in range(20)]
    )
    r4 = validator.validate_h4_wall_reactions(15, 25)

    out_file = tmp_path / "lab_test.md"
    generated = generate_lab_report([r1, r2, r3, r4], reg, output_path=out_file)

    assert generated.exists()
    content = generated.read_text(encoding="utf-8")
    assert "Laboratoire de Validation Empirique" in content
    assert reg.fingerprint in content
    assert "ÉCHANTILLON INSUFFISANT" in content
    assert "H1" in content
    assert "H4" in content


def test_sqlite_backup_and_integrity_restore(tmp_path: Path):
    """Durcissement : Sauvegarde SQLite, intégrité et restauration sans corruption."""
    db_file = tmp_path / "test_cockpit.db"
    backup_file = tmp_path / "test_cockpit_backup.db"

    # Création et remplissage de la base source
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("CREATE TABLE trades (id TEXT PRIMARY KEY, r_realized REAL);")
    cur.execute("INSERT INTO trades VALUES ('T001', 1.85);")
    cur.execute("INSERT INTO trades VALUES ('T002', -1.00);")
    conn.commit()
    conn.close()

    # Sauvegarde via sqlite3 backup API
    src = sqlite3.connect(db_file)
    dst = sqlite3.connect(backup_file)
    src.backup(dst)
    src.close()
    dst.close()

    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    # Vérification d'intégrité sur la sauvegarde restaurée
    check_conn = sqlite3.connect(backup_file)
    integrity = check_conn.execute("PRAGMA integrity_check;").fetchone()[0]
    assert integrity == "ok"

    rows = check_conn.execute("SELECT id, r_realized FROM trades ORDER BY id;").fetchall()
    assert len(rows) == 2
    assert rows[0] == ("T001", 1.85)
    assert rows[1] == ("T002", -1.00)
    check_conn.close()


def test_network_failure_resilience_and_graceful_degradation(tmp_path: Path):
    """Durcissement : Tolérance aux pannes réseau et repli dégradé sans crash."""
    from nqcockpit.data.cache import DiskCache
    from nqcockpit.data.fetcher import DataFetcher
    from nqcockpit.data.models import DataStatus

    fetcher = DataFetcher(cache=DiskCache(cache_dir=tmp_path))

    # Simulation d'un crash réseau complet (ex: coupure de connexion en Algérie)
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.side_effect = ConnectionError("Erreur réseau DNS / Timeout Algérie")

        # Doit intercepter l'erreur sans lever d'exception non gérée
        bars_container = fetcher.fetch_yahoo_bars("NQ=F", interval="1m", period="1d")
        assert bars_container.status in (DataStatus.DEGRADED, DataStatus.BLOCKED)
        assert len(bars_container.bars) == 0
