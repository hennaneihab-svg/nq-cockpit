"""Tests P08 — Profil de journée, carte de scénarios et drapeaux NO-TRADE.

Un cas de test par drapeau NO-TRADE (y compris le cas "aucun drapeau").
Critères : tests des drapeaux, export CSV, schéma de profil et scénarios conditionnels.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from nqcockpit.profile.engine import (
    build_scenario_map,
    evaluate_no_trade_flags,
    export_levels_to_csv,
)
from nqcockpit.profile.models import (
    ComponentHealth,
    KeyLevel,
    NoTradeFlagCode,
)

UTC = timezone.utc
NOW_UTC = datetime(2026, 9, 30, 14, 30, 0, tzinfo=UTC)


def _make_levels(spot: float = 20000.0) -> list[KeyLevel]:
    """Helper : crée une liste minimale de niveaux clés."""
    return [
        KeyLevel(
            name="Call Wall",
            symbol="NQ=F",
            price=spot + 200.0,
            level_type="GAMMA",
            distance_pts=200.0,
            distance_pct=1.0,
            source="CBOE",
            description="Test Call Wall",
        ),
        KeyLevel(
            name="Gamma Flip",
            symbol="NQ=F",
            price=spot - 50.0,
            level_type="GAMMA",
            distance_pts=-50.0,
            distance_pct=-0.25,
            source="CBOE",
            description="Test Gamma Flip",
        ),
        KeyLevel(
            name="Put Support",
            symbol="NQ=F",
            price=spot - 300.0,
            level_type="GAMMA",
            distance_pts=-300.0,
            distance_pct=-1.5,
            source="CBOE",
            description="Test Put Support",
        ),
        KeyLevel(
            name="Overnight High",
            symbol="NQ=F",
            price=spot + 100.0,
            level_type="OVERNIGHT",
            distance_pts=100.0,
            distance_pct=0.5,
            source="CME",
            description="High de nuit",
        ),
        KeyLevel(
            name="Expected Move Haut (+1σ)",
            symbol="NQ=F",
            price=spot + 150.0,
            level_type="EXPECTED_MOVE",
            distance_pts=150.0,
            distance_pct=0.75,
            source="CBOE ACT/365",
            description="Borne haute",
        ),
    ]


# ---------------------------------------------------------------------------
# Tests des drapeaux NO-TRADE
# ---------------------------------------------------------------------------


def test_no_trade_flag_event_red():
    """Drapeau EVENT_RED déclenché quand event_risk_level = RED."""
    assessment = evaluate_no_trade_flags(
        event_risk_level="RED",
        event_risk_reason="NFP Tier 1 dans 3 minutes",
        spot_nq=20000.0,
    )
    assert assessment.is_trading_allowed is False
    assert assessment.active_flags_count >= 1

    event_flag = next(f for f in assessment.all_flags if f.code == NoTradeFlagCode.EVENT_RED)
    assert event_flag.triggered is True
    assert "NFP" in event_flag.reason or "Tier 1" in event_flag.reason
    assert event_flag.severity == "BLOCKING"


def test_no_trade_flag_wall_compression():
    """Drapeau WALL_COMPRESSION déclenché quand spot coincé entre deux murs
    à moins de wall_proximity_points."""
    assessment = evaluate_no_trade_flags(
        event_risk_level="GREEN",
        spot_nq=20000.0,
        call_wall=20010.0,  # seulement 10 pts de distance
        put_support=19992.0,  # seulement 8 pts de distance
        wall_proximity_points=40.0,
    )
    wall_flag = next(f for f in assessment.all_flags if f.code == NoTradeFlagCode.WALL_COMPRESSION)
    assert wall_flag.triggered is True
    assert assessment.is_trading_allowed is False
    assert "murs gamma" in wall_flag.reason.lower() or "40" in wall_flag.reason


def test_no_trade_flag_stale_data():
    """Drapeau STALE_DATA déclenché quand une source est périmée (age_minutes > seuil)."""
    stale_components = {
        "gamma": ComponentHealth(
            name="Niveaux Gamma",
            status="OK",
            age_minutes=45.0,  # > seuil de 30 min
        ),
    }
    assessment = evaluate_no_trade_flags(
        event_risk_level="GREEN",
        spot_nq=20000.0,
        component_statuses=stale_components,
        stale_data_minutes=30.0,
    )
    stale_flag = next(f for f in assessment.all_flags if f.code == NoTradeFlagCode.STALE_DATA)
    assert stale_flag.triggered is True
    assert assessment.is_trading_allowed is False
    assert "gamma" in stale_flag.reason.lower() or "45.0" in stale_flag.reason


def test_no_trade_flag_abnormal_basis():
    """Drapeau ABNORMAL_BASIS déclenché si basis_anomaly=True avec cause explicite."""
    assessment = evaluate_no_trade_flags(
        event_risk_level="GREEN",
        spot_nq=20000.0,
        basis_anomaly=True,
        basis_anomaly_detail="Écart basis (120.0) vs synthétique (5.0) > 100 pts",
    )
    basis_flag = next(f for f in assessment.all_flags if f.code == NoTradeFlagCode.ABNORMAL_BASIS)
    assert basis_flag.triggered is True
    assert "100" in basis_flag.reason
    assert assessment.is_trading_allowed is False


def test_no_trade_flag_daily_loss_limit():
    """Drapeau DAILY_LOSS_LIMIT déclenché quand daily_loss_r <= -daily_loss_limit_r."""
    assessment = evaluate_no_trade_flags(
        event_risk_level="GREEN",
        spot_nq=20000.0,
        daily_loss_r=-2.5,
        daily_loss_limit_r=2.0,
    )
    loss_flag = next(f for f in assessment.all_flags if f.code == NoTradeFlagCode.DAILY_LOSS_LIMIT)
    assert loss_flag.triggered is True
    assert assessment.is_trading_allowed is False
    assert "-2.5" in loss_flag.reason


def test_no_trade_flag_p09_degraded():
    """Quand daily_loss_r=None (P09 non livré), drapeau DAILY_LOSS_LIMIT
    est DÉGRADÉ mais non-bloquant."""
    assessment = evaluate_no_trade_flags(
        event_risk_level="GREEN",
        spot_nq=20000.0,
        daily_loss_r=None,  # P09 non encore livré
    )
    loss_flag = next(f for f in assessment.all_flags if f.code == NoTradeFlagCode.DAILY_LOSS_LIMIT)
    assert loss_flag.triggered is False
    assert "DÉGRADÉ" in loss_flag.status
    # Non-bloquant : il ne bloque pas le trading si tout le reste est OK
    assert loss_flag not in assessment.blocking_flags


def test_no_trade_all_clear():
    """Cas 'aucun drapeau' : toutes les conditions sûres → trading autorisé."""
    assessment = evaluate_no_trade_flags(
        event_risk_level="GREEN",
        event_risk_reason="Aucun événement",
        spot_nq=20000.0,
        call_wall=20300.0,  # 300 pts de distance
        put_support=19700.0,  # 300 pts de distance
        wall_proximity_points=40.0,
        component_statuses={
            "gamma": ComponentHealth(
                name="Gamma",
                status="OK",
                age_minutes=5.0,  # frais
            )
        },
        stale_data_minutes=30.0,
        basis_anomaly=False,
        daily_loss_r=-0.5,  # bien en deçà de la limite
        daily_loss_limit_r=2.0,
    )
    assert assessment.is_trading_allowed is True
    assert assessment.active_flags_count == 0
    assert assessment.blocking_flags == []
    # Tous les 5 drapeaux présents
    assert len(assessment.all_flags) == 5


# ---------------------------------------------------------------------------
# Test de la carte de scénarios
# ---------------------------------------------------------------------------


def test_scenario_map_non_directional():
    """Les scénarios générés ne doivent jamais contenir de biais directionnel
    ni de vocabulaire directif fixant des cibles de cours."""
    levels = _make_levels(spot=20000.0)
    scenarios = build_scenario_map(levels, gamma_regime="POSITIVE_GAMMA", base_em_pts=150.0)

    forbidden_terms = [
        "va monter", "va baisser", "haussier", "baissier",
        "bullish", "bearish", "will go up", "will go down",
        "viser", "cibler", "privilégier", "favoriser", "cible",
        "privilégier les longs", "privilégier les shorts",
    ]
    for sc in scenarios:
        combined = (sc.if_condition + sc.then_plan + sc.context_notes).lower()
        for word in forbidden_terms:
            assert word not in combined, (
                f"Scénario '{sc.level_name}' contient du vocabulaire interdit/directif : '{word}'"
            )
        # Formulation conditionnelle obligatoire
        assert sc.if_condition.startswith("Si"), (
            f"La condition doit commencer par 'Si' : {sc.if_condition!r}"
        )
        assert "alors" in sc.then_plan.lower(), (
            f"Le plan doit contenir 'alors' : {sc.then_plan!r}"
        )


# ---------------------------------------------------------------------------
# Test de l'export CSV
# ---------------------------------------------------------------------------


def test_export_levels_to_csv(tmp_path: Path):
    """Vérifie que l'export CSV contient toutes les lignes attendues et l'en-tête standard."""
    levels = _make_levels(spot=20000.0)
    csv_path = tmp_path / "nq_levels_test.csv"
    csv_text = export_levels_to_csv(levels, filepath=csv_path, now_utc=NOW_UTC)

    # Fichier créé
    assert csv_path.exists()

    lines = csv_text.strip().split("\n")
    # En-tête présent
    assert "Symbol" in lines[0]
    assert "Level_Name" in lines[0]
    assert "Price_NQ" in lines[0]
    # Une ligne par niveau + en-tête
    assert len(lines) == len(levels) + 1
    # Call Wall présent
    assert any("Call Wall" in line for line in lines)
    # Distance en points signée
    assert any("+200" in line or "+200.00" in line for line in lines)


# ---------------------------------------------------------------------------
# Test de structure du DayProfile
# ---------------------------------------------------------------------------


def test_day_profile_structure():
    """Vérifie la structure complète du DayProfile via build_day_profile (sans DB)."""
    from nqcockpit.profile.engine import build_day_profile

    profile = build_day_profile(conn=None, config=None, now_utc=NOW_UTC)

    # Champs obligatoires
    assert isinstance(profile.as_of_utc, str)
    assert isinstance(profile.target_date, str)
    assert isinstance(profile.spot_nq, float) and profile.spot_nq > 0
    assert profile.event_risk_level in ("GREEN", "AMBER", "RED")
    assert profile.gamma_regime in ("POSITIVE_GAMMA", "NEGATIVE_GAMMA", "NEUTRAL")
    assert profile.base_expected_move_pts > 0

    # Statuts composants toujours présents, jamais vide
    assert len(profile.component_statuses) > 0
    for key, comp in profile.component_statuses.items():
        assert comp.status != "", f"Composant {key} a un statut vide"

    # No-trade a toujours les 5 drapeaux
    assert len(profile.no_trade.all_flags) == 5

    # Export JSON ne plante pas
    d = profile.to_dict()
    assert "no_trade" in d
    assert "key_levels" in d
    assert "scenarios" in d
    assert "component_statuses" in d


# ---------------------------------------------------------------------------
# Test Streamlit AppTest — la page se charge sans erreur
# ---------------------------------------------------------------------------


def test_streamlit_cockpit_no_error():
    """Vérifie que la page Cockpit Streamlit se charge sans levée d'exception."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    page = Path(__file__).parent.parent / "src" / "nqcockpit" / "ui" / "cockpit_page.py"
    at = AppTest.from_file(str(page), default_timeout=30)
    at.run()
    assert not at.exception, f"Streamlit a levé une exception : {at.exception}"
