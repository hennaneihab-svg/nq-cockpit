from datetime import datetime, timezone
from unittest.mock import patch

from nqcockpit.events.earnings import _fetch_yfinance_earnings, _get_tier
from nqcockpit.events.models import DataStatus, EarningsEvent, EventRiskReport
from nqcockpit.events.radar import render_console

UTC = timezone.utc

def test_get_tier_classification() -> None:
    """Vérifie la classification Tier 1 et Tier 2 selon les poids NDX."""
    # Tier 1
    assert _get_tier("NVDA") == 1
    assert _get_tier("AAPL") == 1
    assert _get_tier("MSFT") == 1
    # Tier 2
    assert _get_tier("AMZN") == 2
    assert _get_tier("META") == 2
    assert _get_tier("TSLA") == 2
    assert _get_tier("AVGO") == 2
    assert _get_tier("INCONNU") == 2

def test_yfinance_degraded_on_failure() -> None:
    """Vérifie qu'une erreur yfinance bascule l'événement en DÉGRADÉ sans inventer de date."""
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.side_effect = Exception("Erreur réseau")
        ev = _fetch_yfinance_earnings("AAPL")

        assert ev.status == DataStatus.DEGRADED
        assert ev.scheduled_utc is None  # Aucune date inventée
        assert ev.tier == 1
        assert "yfinance erreur: Erreur réseau" in str(ev.error_msg)

def test_earnings_confirmed_vs_estimated_display() -> None:
    """Vérifie l'affichage [confirmée] ou [estimée] dans le radar."""
    now_utc = datetime.now(UTC)

    # 1. Événement estimé
    ev_est = EarningsEvent(
        ticker="META",
        scheduled_utc=now_utc,
        tier=2,
        confirmed=False,
        status=DataStatus.OK,
    )

    # 2. Événement confirmé
    ev_conf = EarningsEvent(
        ticker="NVDA",
        scheduled_utc=now_utc,
        tier=1,
        confirmed=True,
        status=DataStatus.OK,
    )

    # Rapport factice
    report = EventRiskReport(
        as_of_utc=now_utc,
        risk_level="GREEN",
        reason="Test",
        events_14d=[],
        earnings_14d=[ev_est, ev_conf],
    )

    output = render_console(report)

    # Vérification des balises dans l'affichage
    assert "[T2 | estimée |" in output
    assert "[T1 | confirmée |" in output


def test_degraded_status_never_duplicates_word() -> None:
    """Vérifie qu'un statut DÉGRADÉ avec motif n'a jamais 'DÉGRADÉ' dupliqué consécutivement."""
    import re

    from nqcockpit.macro.news_radar import MacroRadarCard
    from nqcockpit.ui.cockpit_page import _render_radar_card_html

    # 1. Vérification du nettoyage de chaîne contre la duplication consécutive
    test_cases = [
        ("DÉGRADÉ: DÉGRADÉ", "DÉGRADÉ"),
        ("DÉGRADÉ : DÉGRADÉ", "DÉGRADÉ"),
        ("DÉGRADÉ: DÉGRADÉ: source CBOE différée", "DÉGRADÉ: source CBOE différée"),
        ("DÉGRADÉ: Retard cotations CBOE 2.2 min", "DÉGRADÉ: Retard cotations CBOE 2.2 min"),
    ]
    for raw_status, _ in test_cases:
        display_status = re.sub(r"(DÉGRADÉ\s*[:—\-]\s*)+DÉGRADÉ", "DÉGRADÉ", raw_status)
        chip_text = f"Niveaux Gamma & Options NDX (P04) : {display_status}"
        assert "DÉGRADÉ: DÉGRADÉ" not in chip_text
        assert "DÉGRADÉ : DÉGRADÉ" not in chip_text
        assert not re.search(r"DÉGRADÉ\s*[:—\-]\s*DÉGRADÉ", chip_text)

    # 2. Vérification dans _render_radar_card_html avec degraded_reason
    card = MacroRadarCard(
        category="MEGA-CAPS TECH",
        title="Résultats Megacaps",
        main_value="INDISPONIBLE",
        sub_value="Calendrier non reçu",
        source="Yahoo Finance / SEC Filings",
        timestamp_utc=datetime.now(UTC),
        observation_date="2026-10-12",
        age_str="Scan en direct",
        status="DÉGRADÉ",
        is_ok=False,
        details=[],
        degraded_reason="DÉGRADÉ: Échec récupération pour: NVDA",
    )
    card_html = _render_radar_card_html(card, delay_idx=0)
    assert "<b>[DÉGRADÉ]</b> DÉGRADÉ" not in card_html
    assert "DÉGRADÉ: DÉGRADÉ" not in card_html


def test_gamma_component_health_degraded_status_formatting(tmp_path) -> None:
    """Vérifie que build_day_profile extrait le motif et n'affiche jamais 'DÉGRADÉ: DÉGRADÉ'."""
    import sqlite3

    from nqcockpit.data.db import apply_migrations, insert_snapshot
    from nqcockpit.profile.engine import build_day_profile

    db_path = tmp_path / "test_cockpit.db"
    conn = sqlite3.connect(str(db_path))
    apply_migrations(conn)

    # Insérer un snapshot dégradé avec motif réel dans anomalies
    insert_snapshot(
        conn=conn,
        timestamp_utc=datetime.now(UTC),
        spot=20000.0,
        regime="POSITIVE_GAMMA",
        gamma_flip=20100.0,
        call_wall=20500.0,
        put_support=19500.0,
        expected_move=150.0,
        basis=10.0,
        synthetic_basis=12.0,
        source="CBOE",
        status="DÉGRADÉ",
        payload={"anomalies": ["DÉGRADÉ : Retard cotations CBOE 2.2 min > seuil 1.0 min"]},
    )

    profile = build_day_profile(conn=conn)
    gamma_health = profile.component_statuses.get("gamma")
    assert gamma_health is not None
    assert "DÉGRADÉ: DÉGRADÉ" not in gamma_health.status
    assert "DÉGRADÉ : DÉGRADÉ" not in gamma_health.status
    assert gamma_health.status.startswith("DÉGRADÉ: ")
    assert "Retard cotations CBOE" in gamma_health.status
    conn.close()

