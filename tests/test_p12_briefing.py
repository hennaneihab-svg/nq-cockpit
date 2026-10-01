"""Tests unitaires pour le module Briefing du Matin & Alertes (P12).

Couvre :
1. Agrégation sans Gemini (fallback Markdown déterministe, zéro chiffre inventé).
2. Gemini mocké en cas normal (texte reformulé valide sans hallucination).
3. Gemini avec détection et rejet d'hallucination (nombre non présent en source).
4. Gemini en cas d'erreur API (fallback automatique sans blocage).
5. Envoi Telegram désactivé (pas de crash, statut DÉGRADÉ visible).
6. Envoi Telegram en mode dry-run.
7. Absence totale de vocabulaire directionnel (regex P08).
8. Intégration de la commande CLI nqcockpit briefing generate.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nqcockpit.briefing.engine import (
    extract_source_numbers,
    generate_briefing,
    validate_anti_hallucination,
)
from nqcockpit.briefing.gemini_client import generate_gemini_summary
from nqcockpit.briefing.models import GeminiResult
from nqcockpit.briefing.telegram_client import send_telegram_message
from nqcockpit.cli import main
from nqcockpit.config import load_config
from nqcockpit.events.models import EventRiskReport
from nqcockpit.levels.models import DataStatus, ExpectedMoveInfo, LevelsSnapshot
from nqcockpit.profile.engine import DayProfile


@pytest.fixture()
def sample_snapshot() -> LevelsSnapshot:
    """Fixture de snapshot de niveaux gamma factuels."""
    em_info = ExpectedMoveInfo(
        formula_move=150.0,
        straddle_move=150.0,
        straddle_move_nq=150.0,
        iv_atm=0.20,
        days_to_expiry=1.0,
        lower_bound_ndx=20700.0,
        upper_bound_ndx=21000.0,
        lower_bound_nq=20700.0,
        upper_bound_nq=21000.0,
    )
    return LevelsSnapshot(
        timestamp_utc=datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc),
        source_timestamp_utc=datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc),
        data_age_minutes=5.0,
        status=DataStatus.OK,
        spot_ndx=20800.0,
        spot_nq=20850.0,
        basis=50.0,
        basis_label="NQ - NDX",
        basis_status=DataStatus.OK,
        synthetic_basis=50.0,
        net_gex=1000000.0,
        regime="AMORTISSEUR (volatilité comprimée)",
        gamma_flip_ndx=20800.0,
        gamma_flip_nq=20850.0,
        call_wall_ndx=20950.0,
        call_wall_nq=21000.0,
        put_wall_ndx=20550.0,
        put_wall_nq=20600.0,
        expected_move=em_info,
    )


@pytest.fixture()
def sample_risk() -> EventRiskReport:
    """Fixture d'évaluation du risque événementiel."""
    return EventRiskReport(
        as_of_utc=datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc),
        risk_level="GREEN",
        reason="Aucun événement Tier 1 dans les 90 minutes.",
        next_event_countdown="Aucun événement Tier 1 imminent.",
    )


from nqcockpit.forecast.models import AmplitudeForecast, DayTypeProbability


@pytest.fixture()
def sample_forecast() -> AmplitudeForecast:
    """Fixture de prévisions d'amplitude."""
    dtp_range = DayTypeProbability(
        day_type="range", count=9, total_sessions=20, probability_pct=45.0,
        wilson_ci_low_pct=25.0, wilson_ci_high_pct=65.0, is_sufficient=False
    )
    dtp_trend = DayTypeProbability(
        day_type="trend", count=7, total_sessions=20, probability_pct=35.0,
        wilson_ci_low_pct=18.0, wilson_ci_high_pct=56.0, is_sufficient=False
    )
    dtp_vol = DayTypeProbability(
        day_type="volatile", count=4, total_sessions=20, probability_pct=20.0,
        wilson_ci_low_pct=8.0, wilson_ci_high_pct=41.0, is_sufficient=False
    )
    return AmplitudeForecast(
        as_of_utc=datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc),
        target_date="2026-09-30",
        spot_nq=20850.0,
        base_expected_move_pts=150.0,
        is_calibrated=False,
        calibration_status="non calibré (n=20 < 60)",
        calibration_reason="échantillon insuffisant",
        projected_amplitude_pts=150.0,
        range_low=20775.0,
        range_high=20925.0,
        day_type_probabilities=[dtp_range, dtp_trend, dtp_vol],
        status="OK",
    )


def test_briefing_aggregation_without_gemini(
    tmp_path: Path, sample_snapshot, sample_risk, sample_forecast
):
    """Agrégation de pré-séance sans Gemini -> Fallback Markdown déterministe."""
    cfg = load_config()
    now_utc = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    out_dir = tmp_path / "briefings"

    briefing = generate_briefing(
        now_utc=now_utc,
        config=cfg,
        levels_snap=sample_snapshot,
        risk_assess=sample_risk,
        forecast=sample_forecast,
        use_gemini=False,
        use_telegram=False,
        output_dir=out_dir,
    )

    assert briefing.status == "OK"
    assert briefing.session_date_ny == "2026-09-30"
    assert "Briefing Pré-Séance NQ" in briefing.markdown_briefing
    assert "20850.00" in briefing.markdown_briefing or "20850" in briefing.markdown_briefing
    assert briefing.output_path is not None
    assert briefing.output_path.is_file()
    assert briefing.output_path.name == "briefing_2026-09-30.md"


def test_anti_hallucination_validator_normal_case():
    """Anti-hallucination : nombres autorisés issus des sources -> Valide."""
    source_nums = {20850.0, 21000.0, 20600.0, 150.0, 0.45, "2026-09-30"}
    extracted_set = extract_source_numbers(source_nums)

    text = "Le gamma flip est à 20850 et le Call Wall est à 21000. Expected move de 150 points."
    is_valid, warn = validate_anti_hallucination(text, extracted_set)

    assert is_valid is True
    assert warn is None


def test_anti_hallucination_validator_hallucination_detected():
    """Anti-hallucination : nombre non présent en source (ex: 29999.9) -> Rejet."""
    source_nums = {20850.0, 21000.0, 20600.0, 150.0}
    extracted_set = extract_source_numbers(source_nums)

    text = "Nouveau niveau inventé à 29999.9 points non présent dans le JSON."
    is_valid, warn = validate_anti_hallucination(text, extracted_set)

    assert is_valid is False
    assert warn is not None
    assert "29999.9" in warn


def test_briefing_with_gemini_mock_ok(
    tmp_path: Path, monkeypatch, sample_snapshot, sample_risk, sample_forecast
):
    """Gemini mocké retournant une reformulation valide -> Gemini utilisé."""
    cfg = load_config()
    now_utc = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)

    mock_text = (
        "# Briefing NQ Synthétique\n"
        "- Gamma Flip à 20850.0\n"
        "- Call Wall à 21000.0\n"
        "- Statut du marché : neutre et conditionnel."
    )

    def mock_post(*args, **kwargs):
        class MockResp:
            def read(self):
                return json.dumps({
                    "candidates": [
                        {"content": {"parts": [{"text": mock_text}]}}
                    ]
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
        return MockResp()

    import json
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_post)
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_123")

    briefing = generate_briefing(
        now_utc=now_utc,
        config=cfg,
        levels_snap=sample_snapshot,
        risk_assess=sample_risk,
        forecast=sample_forecast,
        use_gemini=True,
        use_telegram=False,
        output_dir=tmp_path / "briefings",
    )

    assert briefing.is_gemini_used is True
    assert briefing.gemini_result is not None
    assert briefing.gemini_result.status == "OK"
    assert briefing.markdown_briefing == mock_text


def test_briefing_with_gemini_hallucination_rejected(
    tmp_path: Path, monkeypatch, sample_snapshot, sample_risk, sample_forecast
):
    """Gemini retourne un prix inventé -> Rejeté et fallback Markdown utilisé."""
    cfg = load_config()
    now_utc = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)

    # Contient 99999.99 (n'existe pas dans les sources)
    hallucinated_text = "# Briefing\nNiveau cible inventé : 99999.99 points."

    def mock_post(*args, **kwargs):
        class MockResp:
            def read(self):
                return json.dumps({
                    "candidates": [
                        {"content": {"parts": [{"text": hallucinated_text}]}}
                    ]
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
        return MockResp()

    import json
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_post)
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_123")

    briefing = generate_briefing(
        now_utc=now_utc,
        config=cfg,
        levels_snap=sample_snapshot,
        risk_assess=sample_risk,
        forecast=sample_forecast,
        use_gemini=True,
        use_telegram=False,
        output_dir=tmp_path / "briefings",
    )

    assert briefing.is_gemini_used is False
    assert briefing.gemini_result is not None
    assert briefing.gemini_result.status == "REJECTED_HALLUCINATION"
    assert briefing.status == "DÉGRADÉ"
    assert any("Hallucination" in w for w in briefing.status_warnings)
    # Contenu de fallback déterministe
    assert "Briefing Pré-Séance NQ" in briefing.markdown_briefing


def test_briefing_with_gemini_api_error(
    tmp_path: Path, monkeypatch, sample_snapshot, sample_risk, sample_forecast
):
    """Erreur API Gemini (ex: panne réseau) -> Fallback propre sans crash."""
    cfg = load_config()
    now_utc = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)

    def mock_error(*args, **kwargs):
        raise urllib.error.URLError("Network unreachable")

    import urllib.error
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_error)
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_123")

    briefing = generate_briefing(
        now_utc=now_utc,
        config=cfg,
        levels_snap=sample_snapshot,
        risk_assess=sample_risk,
        forecast=sample_forecast,
        use_gemini=True,
        use_telegram=False,
        output_dir=tmp_path / "briefings",
    )

    assert briefing.is_gemini_used is False
    assert briefing.gemini_result is not None
    assert briefing.gemini_result.status == "FAILED"
    assert briefing.status == "DÉGRADÉ"
    assert "Briefing Pré-Séance NQ" in briefing.markdown_briefing


def test_telegram_client_disabled():
    """Telegram sans identifiants dans .env -> Statut DISABLED sans erreur."""
    res = send_telegram_message("Test message", bot_token_override="", chat_id_override="")
    assert res.status == "DISABLED"
    assert res.sent is False


def test_telegram_client_dry_run():
    """Telegram avec dry_run=True -> Statut DRY_RUN sans appel réseau."""
    res = send_telegram_message(
        "Test message",
        dry_run=True,
        bot_token_override="fake_token",
        chat_id_override="12345",
    )
    assert res.status == "DRY_RUN"
    assert res.sent is False
    assert "DRY-RUN" in (res.message or "")


def test_no_directional_vocabulary_in_generated_briefing(
    tmp_path: Path, sample_snapshot, sample_risk, sample_forecast
):
    """Garantie stricte : le texte du briefing ne contient AUCUN terme directionnel interdit."""
    cfg = load_config()
    now_utc = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)

    briefing = generate_briefing(
        now_utc=now_utc,
        config=cfg,
        levels_snap=sample_snapshot,
        risk_assess=sample_risk,
        forecast=sample_forecast,
        use_gemini=False,
        use_telegram=False,
        output_dir=tmp_path / "briefings",
    )

    banned_regex = (
        r"\b(viser|cibler|objectif haussier|objectif baissier|"
        r"tendance haussière|tendance baissière|signal d\'achat|signal de vente)\b"
    )
    match = re.search(banned_regex, briefing.markdown_briefing, re.IGNORECASE)
    assert match is None, f"Terme directionnel interdit détecté dans le briefing : '{match.group(0)}'"


def test_cli_briefing_generate(tmp_path: Path, monkeypatch, capsys):
    """Test de la commande CLI nqcockpit briefing generate --dry-run --no-gemini."""
    out_dir = tmp_path / "cli_briefings"

    code = main([
        "briefing", "generate",
        "--dry-run",
        "--no-gemini",
        "--output-dir", str(out_dir),
    ])

    assert code == 0
    captured = capsys.readouterr().out
    assert "NQ COCKPIT — BRIEFING PRÉ-SÉANCE" in captured
    assert "Briefing Pré-Séance NQ" in captured
    assert len(list(out_dir.glob("briefing_*.md"))) == 1
