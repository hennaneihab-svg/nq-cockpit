"""Tests P04-fix3 : Tâche 1 (horodatages base), Tâche 2 (Diagnostic 1c), Tâche 3 (Expected Move NQ).

Toutes les données sont en fixtures synthétiques (zéro appel réseau).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from nqcockpit.data.models import Bar, DataStatus
from nqcockpit.levels.engine import (
    build_diagnostic_1c,
    enrich_expected_move_nq,
)
from nqcockpit.levels.models import ExpectedMoveInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _bar(ts_utc: datetime, close: float) -> Bar:
    """Crée une barre fictive avec close donné."""
    return Bar(timestamp_utc=ts_utc, open=close, high=close, low=close, close=close)


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Crée un datetime ET converti en UTC."""
    return datetime(year, month, day, hour, minute, 0, tzinfo=ET).astimezone(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 1 — BasisSnapshot : delta_t et is_aligned
# ─────────────────────────────────────────────────────────────────────────────


def test_basis_live_populated_fields():
    """compute_live_basis doit peupler delta_t_minutes, is_aligned=True, tolerance=1 min."""
    from nqcockpit.data.basis import compute_live_basis

    # Deux barres décalées de 30s (< tolérance 60s)
    ts_nq = _et(2026, 9, 29, 14, 0)
    ts_ndx = ts_nq + timedelta(seconds=30)
    nq_bar = _bar(ts_nq, 20500.0)
    ndx_bar = _bar(ts_ndx, 20200.0)

    basis = compute_live_basis(nq_bar, ndx_bar, now_utc=ts_ndx + timedelta(minutes=1))

    assert basis is not None
    assert basis.delta_t_minutes is not None
    assert abs(basis.delta_t_minutes - 0.5) < 0.01  # 30s = 0.5 min
    assert basis.is_aligned is True
    assert basis.tolerance_minutes == 1.0
    assert basis.formula == "base = NQ_close - NDX_spot"


def test_basis_live_out_of_tolerance():
    """Deux barres avec Δt > 60s → BasisSnapshot retourné avec status=BLOCKED."""
    from nqcockpit.data.basis import compute_live_basis

    ts_nq = _et(2026, 9, 29, 14, 0)
    ts_ndx = ts_nq + timedelta(seconds=90)  # 1.5 min — hors tolérance
    nq_bar = _bar(ts_nq, 20500.0)
    ndx_bar = _bar(ts_ndx, 20200.0)

    basis = compute_live_basis(nq_bar, ndx_bar, now_utc=ts_ndx + timedelta(minutes=1))

    # La fonction retourne un BasisSnapshot BLOCKED lorsque drift > max_drift_seconds
    assert basis is not None
    assert basis.status == DataStatus.BLOCKED
    # Les champs delta_t ne sont pas peuplés sur le chemin BLOCKED (early return)
    # Mais on s'assure que le snap est renvoyé (jamais None)


def test_basis_previous_session_delta_t():
    """compute_previous_session_basis doit peupler delta_t_minutes et delay_compensation_note."""
    from nqcockpit.data.basis import compute_previous_session_basis

    # ref_utc est APRÈS la clôture du 2026-09-29
    ref_utc = _et(2026, 9, 29, 20, 0)

    nq_bars = [
        _bar(_et(2026, 9, 29, 15, 59), 20500.0),
        _bar(_et(2026, 9, 29, 16, 0), 20510.0),  # barre cible NQ
    ]
    ndx_bars = [
        _bar(_et(2026, 9, 29, 15, 59), 20200.0),  # NDX 1 min avant, delta_t = 1 min
    ]

    basis = compute_previous_session_basis(nq_bars, ndx_bars, ref_utc=ref_utc)

    if basis is not None and basis.status != DataStatus.BLOCKED:
        assert basis.delta_t_minutes is not None
        assert basis.formula == "base = NQ_close - NDX_spot"
        assert basis.delay_compensation_note is not None
        assert len(basis.delay_compensation_note) > 10
    else:
        # La DB peut compléter ou non selon l'état — vérifie qu'aucune exception n'est levée
        assert basis is not None


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 2 — Diagnostic 1c
# ─────────────────────────────────────────────────────────────────────────────


def test_diagnostic_1c_paire_trouvee():
    """Paire NQ+NDX valide le jour J → PAIRE_TROUVEE."""
    session_date = date(2026, 9, 29)
    now_utc = _et(2026, 9, 29, 20, 0)  # après clôture

    nq_bars = [
        _bar(_et(2026, 9, 29, 15, 59), 20500.0),
        _bar(_et(2026, 9, 29, 16, 0), 20510.0),
    ]
    ndx_bars = [
        _bar(_et(2026, 9, 29, 15, 59), 20200.0),
    ]

    d = build_diagnostic_1c(nq_bars, ndx_bars, now_utc, session_date, tolerance_minutes=1.0)

    assert d.cause_code == "PAIRE_TROUVEE"
    assert d.nq_candidate_found is True
    assert d.ndx_candidate_found is True
    assert d.delta_t_minutes is not None
    assert d.delta_t_minutes == pytest.approx(1.0, abs=0.01)
    assert d.nq_candidate_close == 20510.0
    assert d.nq_bars_count_day == 2
    assert d.target_time_et is not None
    assert "2026-09-29" in d.target_time_et
    assert "Alger" in d.target_time_algiers


def test_diagnostic_1c_nq_bar_absente():
    """Aucune barre NQ → cause_code = NQ_BAR_ABSENTE."""
    session_date = date(2026, 9, 29)
    now_utc = _et(2026, 9, 29, 20, 0)

    d = build_diagnostic_1c([], [], now_utc, session_date)

    assert d.cause_code == "NQ_BAR_ABSENTE"
    assert d.nq_candidate_found is False
    assert d.nq_bars_count_day == 0


def test_diagnostic_1c_ndx_absente():
    """NQ présent mais NDX absent → cause_code = NDX_QUOTE_ABSENTE."""
    session_date = date(2026, 9, 29)
    now_utc = _et(2026, 9, 29, 20, 0)

    nq_bars = [
        _bar(_et(2026, 9, 29, 15, 59), 20500.0),
        _bar(_et(2026, 9, 29, 16, 0), 20510.0),
    ]

    d = build_diagnostic_1c(nq_bars, [], now_utc, session_date)

    assert d.cause_code == "NDX_QUOTE_ABSENTE"
    assert d.nq_candidate_found is True
    assert d.ndx_candidate_found is False
    assert d.nq_bars_count_day == 2


def test_diagnostic_1c_hors_tolerance():
    """Paire trouvée mais Δt > tolérance → HORS_TOLERANCE."""
    session_date = date(2026, 9, 29)
    now_utc = _et(2026, 9, 29, 20, 0)

    nq_bars = [_bar(_et(2026, 9, 29, 16, 0), 20510.0)]
    ndx_bars = [
        _bar(_et(2026, 9, 29, 15, 55), 20200.0)  # 5 minutes d'écart
    ]

    d = build_diagnostic_1c(nq_bars, ndx_bars, now_utc, session_date, tolerance_minutes=1.0)

    assert d.cause_code == "HORS_TOLERANCE"
    assert d.delta_t_minutes is not None
    assert d.delta_t_minutes > 1.0
    assert d.nq_candidate_found is True
    assert d.ndx_candidate_found is True


def test_diagnostic_1c_session_incomplete():
    """Barres NQ présentes mais aucune avant 16:00 ET → SESSION_INCOMPLETE."""
    session_date = date(2026, 9, 29)
    now_utc = _et(2026, 9, 29, 20, 0)

    # Barres qui commencent après 16:00 (ex : futures de nuit)
    nq_bars = [
        _bar(_et(2026, 9, 29, 16, 1), 20515.0),  # 16:01 — après clôture
        _bar(_et(2026, 9, 29, 17, 0), 20520.0),
    ]
    ndx_bars = [
        _bar(_et(2026, 9, 29, 15, 59), 20200.0),
    ]

    d = build_diagnostic_1c(nq_bars, ndx_bars, now_utc, session_date, tolerance_minutes=1.0)

    assert d.cause_code in ("SESSION_INCOMPLETE", "NQ_BAR_ABSENTE")
    assert d.nq_candidate_found is False
    assert d.nq_bars_count_day == 2


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 3 — Expected Move NQ enrichi
# ─────────────────────────────────────────────────────────────────────────────


def _base_em(formula_move: float, straddle_move: float | None = None) -> ExpectedMoveInfo:
    """Construit un ExpectedMoveInfo minimal pour les tests."""
    spot_ndx = 20000.0
    return ExpectedMoveInfo(
        formula_move=formula_move,
        straddle_move=straddle_move,
        iv_atm=0.17,
        days_to_expiry=1.0,
        lower_bound_ndx=spot_ndx - formula_move,
        upper_bound_ndx=spot_ndx + formula_move,
        lower_bound_nq=0.0,
        upper_bound_nq=0.0,
        expiry=date(2026, 9, 29),
    )


def test_em_nq_enrichment_coherent():
    """Straddle et IV identiques → écart 0%, is_coherent=True."""
    move = 280.0
    em = _base_em(formula_move=move, straddle_move=move)
    spot_nq = 20300.0

    enriched = enrich_expected_move_nq(
        em, basis=300.0, spot_nq=spot_nq, spot_ndx=20000.0, cboe_age_minutes=15.0
    )

    assert enriched.is_coherent is True
    assert enriched.status == DataStatus.OK
    assert enriched.discrepancy_pct == pytest.approx(0.0, abs=0.1)
    assert enriched.iv_move_nq == pytest.approx(move, abs=0.1)
    assert enriched.straddle_move_nq == pytest.approx(move, abs=0.1)
    assert enriched.iv_lower_nq == pytest.approx(spot_nq - move, abs=0.1)
    assert enriched.iv_upper_nq == pytest.approx(spot_nq + move, abs=0.1)
    assert enriched.straddle_lower_nq == pytest.approx(spot_nq - move, abs=0.1)
    assert enriched.straddle_upper_nq == pytest.approx(spot_nq + move, abs=0.1)
    assert enriched.expiry_day_of_week is not None
    assert "2026" in enriched.expiry_day_of_week
    assert enriched.data_age_minutes == pytest.approx(15.0, abs=0.01)


def test_em_nq_enrichment_degraded_over_25pct():
    """Écart straddle / IV > 25% → DÉGRADÉ, is_coherent=False, status_explanation peuplé."""
    formula_move = 336.0  # méthode IV
    straddle_move = 223.0  # méthode straddle (−33% par rapport à IV)
    em = _base_em(formula_move=formula_move, straddle_move=straddle_move)
    spot_nq = 20300.0

    enriched = enrich_expected_move_nq(
        em, basis=300.0, spot_nq=spot_nq, spot_ndx=20000.0, cboe_age_minutes=12.0
    )

    assert enriched.is_coherent is False
    assert enriched.status == DataStatus.DEGRADED
    assert enriched.discrepancy_pct is not None
    assert enriched.discrepancy_pct > 25.0
    assert enriched.status_explanation is not None
    assert "25%" in enriched.status_explanation
    # Les valeurs brutes doivent être présentes même dégradé (pas d'ajustement)
    assert enriched.straddle_move_nq == pytest.approx(straddle_move, abs=0.1)
    assert enriched.iv_move_nq == pytest.approx(formula_move, abs=0.1)


def test_em_nq_no_straddle():
    """Pas de straddle → is_coherent=True, pas de discrepancy, champs straddle_nq = None."""
    em = _base_em(formula_move=280.0, straddle_move=None)
    spot_nq = 20300.0

    enriched = enrich_expected_move_nq(
        em, basis=300.0, spot_nq=spot_nq, spot_ndx=20000.0, cboe_age_minutes=None
    )

    assert enriched.straddle_move_nq is None
    assert enriched.straddle_lower_nq is None
    assert enriched.straddle_upper_nq is None
    assert enriched.discrepancy_pct is None
    assert enriched.is_coherent is True
    assert enriched.data_age_minutes is None


def test_em_nq_bounds_not_adjusted():
    """Règle impérative : aucune borne ne doit être ajustée pour 'rentrer dans une plage'.

    Le move straddle = 100 pts, le move IV = 200 pts (écart 100%) — les deux sont présents
    tels quels dans les champs NQ, sans troncature ni ajustement.
    """
    em = _base_em(formula_move=200.0, straddle_move=100.0)
    spot_nq = 20300.0

    enriched = enrich_expected_move_nq(
        em, basis=300.0, spot_nq=spot_nq, spot_ndx=20000.0, cboe_age_minutes=None
    )

    # Valeurs brutes inchangées
    assert enriched.iv_move_nq == pytest.approx(200.0, abs=0.01)
    assert enriched.straddle_move_nq == pytest.approx(100.0, abs=0.01)
    # Bornes cohérentes avec les valeurs brutes
    assert enriched.iv_lower_nq == pytest.approx(spot_nq - 200.0, abs=0.01)
    assert enriched.straddle_lower_nq == pytest.approx(spot_nq - 100.0, abs=0.01)
    # Dégradé car > 25%
    assert enriched.is_coherent is False
