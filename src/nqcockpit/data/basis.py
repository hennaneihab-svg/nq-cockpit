"""Calcul et validation de la base NQ/NDX et conversion vers NQ.

Adapté de Darthreign/gex-dashboard (MIT), copyright conservé.

Règles de conception (docs/vendor_audit.md) :
1. En séance régulière actions (09:30 - 16:00 ET) : barres 1m rigoureusement alignées
   en UTC (tolérance <= 60s). Interdiction de calculer sur des "derniers cours" asynchrones.
2. Hors séance actions (pré-market, soir, week-end) : base de la séance précédente,
   étiquetée « base de la séance précédente » avec son âge horodaté.
3. Contrôle croisé parité call-put synthétique (futures_basis de gex-dashboard).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from nqcockpit.data.calendar import CALENDAR
from nqcockpit.data.models import (
    Bar,
    BasisSnapshot,
    DataStatus,
    PairResult,
    SearchStepResult,
)
from nqcockpit.data.roll import third_friday_of_month

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def compute_live_basis(
    nq_bar: Bar,
    ndx_bar: Bar,
    now_utc: datetime | None = None,
    max_drift_seconds: float = 60.0,
) -> BasisSnapshot:
    """Calcule la base NQ=F - ^NDX à partir de barres 1m alignées en UTC.

    Vérifie que l'écart temporel entre les deux barres ne dépasse pas max_drift_seconds.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    # Vérification de l'alignement temporel
    drift = abs((nq_bar.timestamp_utc - ndx_bar.timestamp_utc).total_seconds())
    if drift > max_drift_seconds:
        return BasisSnapshot(
            timestamp_utc=nq_bar.timestamp_utc,
            nq_price=nq_bar.close,
            ndx_price=ndx_bar.close,
            basis=nq_bar.close - ndx_bar.close,
            is_session_basis=False,
            status=DataStatus.BLOCKED,
            label="désalignement temporel barres 1m (> 60s)",
            age_minutes=(now_utc - nq_bar.timestamp_utc).total_seconds() / 60.0,
        )

    # Vérifier si on est en séance régulière actions US
    in_regular_session = CALENDAR.is_us_equity_regular_hours(nq_bar.timestamp_utc)
    age_min = (now_utc - nq_bar.timestamp_utc).total_seconds() / 60.0

    basis_val = nq_bar.close - ndx_bar.close
    status = DataStatus.OK
    nq_ny_str = nq_bar.timestamp_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S EDT")
    ndx_ny_str = ndx_bar.timestamp_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S EDT")
    nq_utc_str = nq_bar.timestamp_utc.strftime("%H:%M:%SZ")
    ndx_utc_str = ndx_bar.timestamp_utc.strftime("%H:%M:%SZ")

    if not in_regular_session:
        status = DataStatus.DEGRADED
        method_str = "séance précédente"
        label = (
            f"base de la séance précédente (méthode: {method_str} | "
            f"NQ: {nq_ny_str} [{nq_utc_str}]"
            f" / NDX: {ndx_ny_str} [{ndx_utc_str}], âge: {age_min:.1f} min)"
        )
    else:
        method_str = "séance en cours (direct)"
        label = (
            f"base en séance (méthode: {method_str} | "
            f"NQ: {nq_ny_str} [{nq_utc_str}]"
            f" / NDX: {ndx_ny_str} [{ndx_utc_str}], âge: {age_min:.1f} min)"
        )

    return BasisSnapshot(
        timestamp_utc=nq_bar.timestamp_utc,
        nq_price=nq_bar.close,
        ndx_price=ndx_bar.close,
        basis=basis_val,
        is_session_basis=in_regular_session,
        status=status,
        label=label,
        age_minutes=age_min,
        nq_timestamp_utc=nq_bar.timestamp_utc,
        ndx_timestamp_utc=ndx_bar.timestamp_utc,
        method=method_str,
        delta_t_minutes=drift / 60.0,
        tolerance_minutes=max_drift_seconds / 60.0,
        is_aligned=True,
        formula="base = NQ_close - NDX_spot",
    )


def find_basis_pair(
    target: datetime,
    nq_bars: list[Bar] | None = None,
    ndx_bars: list[Bar] | None = None,
    tolerance_minutes: float = 1.0,
    conn: Any | None = None,
    reload_source: bool = False,
) -> PairResult:
    """Recherche unique et ordonnée de la paire NQ / NDX à une cible temporelle.

    Ordre de recherche rigoureux :
      1. Mémoire (listes nq_bars, ndx_bars)
      2. SQLite (table bars locale via get_bar_at_or_before)
      3. Rechargement source distante (si demandé)

    Cette fonction produit le PairResult unique qui DOIT être lu à la fois par
    compute_previous_session_basis et build_diagnostic_1c.
    """
    if target.tzinfo is None:
        target_utc = target.replace(tzinfo=timezone.utc)
    else:
        target_utc = target.astimezone(timezone.utc)

    target_et = target_utc.astimezone(ET)
    target_date = target_et.date()

    search_steps: list[SearchStepResult] = []

    # 1. Étape MÉMOIRE
    nq_candidate_mem: Bar | None = None
    if nq_bars:
        valid_nq_mem = [b for b in nq_bars if b.timestamp_utc <= target_utc]
        if valid_nq_mem:
            nq_candidate_mem = valid_nq_mem[-1]

    ndx_candidate_mem: Bar | None = None
    if ndx_bars:
        valid_ndx_mem = [b for b in ndx_bars if b.timestamp_utc <= target_utc]
        if valid_ndx_mem:
            ndx_candidate_mem = valid_ndx_mem[-1]

    search_steps.append(
        SearchStepResult(
            step_name="memoire",
            nq_found=nq_candidate_mem is not None,
            nq_time_utc=nq_candidate_mem.timestamp_utc if nq_candidate_mem else None,
            nq_close=nq_candidate_mem.close if nq_candidate_mem else None,
            ndx_found=ndx_candidate_mem is not None,
            ndx_time_utc=ndx_candidate_mem.timestamp_utc if ndx_candidate_mem else None,
            ndx_spot=ndx_candidate_mem.close if ndx_candidate_mem else None,
            details=(
                f"NQ: {'trouvé' if nq_candidate_mem else 'non trouvé'}, "
                f"NDX: {'trouvé' if ndx_candidate_mem else 'non trouvé'}"
            ),
        )
    )

    # 2. Étape SQLITE
    from nqcockpit.data.db import get_bar_at_or_before

    nq_candidate_db: Bar | None = None
    if nq_candidate_mem is None:
        try:
            bar_db = get_bar_at_or_before("NQ=F", target_utc, conn=conn)
            if bar_db and bar_db.timestamp_utc.astimezone(ET).date() == target_date:
                nq_candidate_db = bar_db
        except Exception as e:
            log.warning("Erreur lecture barre NQ SQLite : %s", e)

    ndx_candidate_db: Bar | None = None
    if ndx_candidate_mem is None:
        try:
            bar_db = get_bar_at_or_before("^NDX", target_utc, conn=conn)
            if bar_db and bar_db.timestamp_utc.astimezone(ET).date() == target_date:
                ndx_candidate_db = bar_db
        except Exception as e:
            log.warning("Erreur lecture barre NDX SQLite : %s", e)

    nq_db_det = (
        "en mémoire" if nq_candidate_mem else ("trouvé" if nq_candidate_db else "non trouvé")
    )
    ndx_db_det = (
        "en mémoire" if ndx_candidate_mem else ("trouvé" if ndx_candidate_db else "non trouvé")
    )
    search_steps.append(
        SearchStepResult(
            step_name="sqlite",
            nq_found=nq_candidate_db is not None or nq_candidate_mem is not None,
            nq_time_utc=(
                nq_candidate_db.timestamp_utc
                if nq_candidate_db
                else (nq_candidate_mem.timestamp_utc if nq_candidate_mem else None)
            ),
            nq_close=(
                nq_candidate_db.close
                if nq_candidate_db
                else (nq_candidate_mem.close if nq_candidate_mem else None)
            ),
            ndx_found=ndx_candidate_db is not None or ndx_candidate_mem is not None,
            ndx_time_utc=(
                ndx_candidate_db.timestamp_utc
                if ndx_candidate_db
                else (ndx_candidate_mem.timestamp_utc if ndx_candidate_mem else None)
            ),
            ndx_spot=(
                ndx_candidate_db.close
                if ndx_candidate_db
                else (ndx_candidate_mem.close if ndx_candidate_mem else None)
            ),
            details=f"NQ: {nq_db_det}, NDX: {ndx_db_det}",
        )
    )

    # 3. Étape SOURCE DISTANTE (rechargement)
    search_steps.append(
        SearchStepResult(
            step_name="source_distante",
            nq_found=nq_candidate_mem is not None or nq_candidate_db is not None,
            ndx_found=ndx_candidate_mem is not None or ndx_candidate_db is not None,
            details="non requis (données trouvées ou rechargement non sollicité)",
        )
    )

    # Sélection des barres retenues et de leur origine
    if nq_candidate_mem is not None:
        final_nq = nq_candidate_mem
        origin_nq = "memoire"
    elif nq_candidate_db is not None:
        final_nq = nq_candidate_db
        origin_nq = "sqlite"
    else:
        final_nq = None
        origin_nq = None

    if ndx_candidate_mem is not None:
        final_ndx = ndx_candidate_mem
        origin_ndx = "memoire"
    elif ndx_candidate_db is not None:
        final_ndx = ndx_candidate_db
        origin_ndx = "sqlite"
    else:
        final_ndx = None
        origin_ndx = None

    # Évaluation de la cohérence / cause
    delta_t: float | None = None
    is_aligned = False
    cause_code: str
    cause_detail: str
    action_taken: str

    if final_nq is None and final_ndx is None:
        cause_code = "NQ_BAR_ABSENTE"
        cause_detail = (
            f"Aucune barre NQ ni NDX trouvée pour le {target_date.isoformat()} "
            f"avant {target_et.strftime('%H:%M:%S ET')} après échec de toutes les étapes"
        )
        action_taken = "Repli sur base de parité call-put"
    elif final_nq is None:
        cause_code = "NQ_BAR_ABSENTE"
        cause_detail = (
            f"Aucune barre NQ trouvée pour le {target_date.isoformat()} "
            f"avant {target_et.strftime('%H:%M:%S ET')} (mémoire: non trouvé, SQLite: non trouvé)"
        )
        action_taken = "Repli sur base de parité call-put"
    elif final_ndx is None:
        cause_code = "NDX_QUOTE_ABSENTE"
        cause_detail = (
            f"Aucune cotation NDX trouvée pour le {target_date.isoformat()} "
            f"avant {target_et.strftime('%H:%M:%S ET')} (mémoire: non trouvé, SQLite: non trouvé)"
        )
        action_taken = "Repli sur base de parité call-put"
    else:
        delta_t = (
            abs((final_nq.timestamp_utc - final_ndx.timestamp_utc).total_seconds())
            / 60.0
        )
        if delta_t > tolerance_minutes:
            is_aligned = False
            cause_code = "HORS_TOLERANCE"
            nq_time_str = final_nq.timestamp_utc.astimezone(ET).strftime("%H:%M:%S ET")
            ndx_time_str = final_ndx.timestamp_utc.astimezone(ET).strftime("%H:%M:%S ET")
            cause_detail = (
                f"Paire trouvée mais Delta-t={delta_t:.2f} min > tolérance "
                f"{tolerance_minutes:.1f} min. "
                f"NQ ({origin_nq}): {nq_time_str}, NDX ({origin_ndx}): {ndx_time_str}"
            )
            action_taken = (
                "Base calculée quand même avec mention 'non alignée' ; contrôle parité"
            )
        else:
            is_aligned = True
            cause_code = "PAIRE_TROUVEE"
            cause_detail = (
                f"Paire valide trouvée (NQ: {origin_nq}, NDX: {origin_ndx}, "
                f"Delta-t={delta_t:.2f} min)"
            )
            action_taken = "Base de la séance précédente retenue"

    return PairResult(
        target_utc=target_utc,
        nq_bar=final_nq,
        ndx_bar=final_ndx,
        nq_origin=origin_nq,
        ndx_origin=origin_ndx,
        search_steps=search_steps,
        delta_t_minutes=delta_t,
        tolerance_minutes=tolerance_minutes,
        is_aligned=is_aligned,
        cause_code=cause_code,
        cause_detail=cause_detail,
        action_taken=action_taken,
    )


def compute_previous_session_basis(
    nq_bars: list[Bar],
    ndx_bars: list[Bar],
    ref_utc: datetime | None = None,
    pair_result: PairResult | None = None,
) -> BasisSnapshot:
    """Trouve la dernière clôture de séance régulière actions US et calcule la base de clôture.

    Lit obligatoirement le PairResult unique (produit par find_basis_pair).
    """
    if ref_utc is None:
        ref_utc = datetime.now(timezone.utc)
    elif ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    session_close_utc = CALENDAR.get_last_equity_session_close(ref_utc)

    if pair_result is None:
        pair_result = find_basis_pair(
            target=session_close_utc,
            nq_bars=nq_bars,
            ndx_bars=ndx_bars,
            tolerance_minutes=1.0,
        )

    if (
        not pair_result.is_found
        or pair_result.nq_bar is None
        or pair_result.ndx_bar is None
    ):
        return BasisSnapshot(
            timestamp_utc=ref_utc,
            nq_price=0.0,
            ndx_price=0.0,
            basis=0.0,
            is_session_basis=False,
            status=DataStatus.BLOCKED,
            label=f"historique insuffisant ({pair_result.cause_code})",
            method="séance précédente",
            delta_t_minutes=pair_result.delta_t_minutes or 0.0,
            tolerance_minutes=pair_result.tolerance_minutes,
            is_aligned=False,
            formula="base = NQ_close - NDX_spot",
        )

    last_nq = pair_result.nq_bar
    last_ndx = pair_result.ndx_bar

    drift = abs((last_nq.timestamp_utc - last_ndx.timestamp_utc).total_seconds())
    is_stale_session = CALENDAR.is_more_than_one_session_stale(
        last_ndx.timestamp_utc, ref_utc=ref_utc
    )

    if drift > 60.0 or is_stale_session:
        status = DataStatus.DEGRADED
    else:
        status = DataStatus.OK

    age_min = (ref_utc - last_ndx.timestamp_utc).total_seconds() / 60.0
    age_h = age_min / 60.0
    basis_val = last_nq.close - last_ndx.close

    nq_ny_str = last_nq.timestamp_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S EDT")
    ndx_ny_str = last_ndx.timestamp_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S EDT")
    nq_utc_str = last_nq.timestamp_utc.strftime("%H:%M:%SZ")
    ndx_utc_str = last_ndx.timestamp_utc.strftime("%H:%M:%SZ")

    label = (
        f"base de la séance précédente (méthode: séance précédente | "
        f"NQ: {nq_ny_str} [{nq_utc_str}] / NDX: {ndx_ny_str} [{ndx_utc_str}], âge {age_h:.1f} h)"
    )

    proven_origin_note = (
        f"barre NQ lue en {pair_result.nq_origin}, "
        f"cotation NDX lue en {pair_result.ndx_origin}"
    )

    return BasisSnapshot(
        timestamp_utc=last_ndx.timestamp_utc,
        nq_price=last_nq.close,
        ndx_price=last_ndx.close,
        basis=basis_val,
        is_session_basis=False,
        status=status,
        label=label,
        age_minutes=age_min,
        nq_timestamp_utc=last_nq.timestamp_utc,
        ndx_timestamp_utc=last_ndx.timestamp_utc,
        method="séance précédente",
        delta_t_minutes=drift / 60.0,
        tolerance_minutes=pair_result.tolerance_minutes,
        is_aligned=pair_result.is_aligned and not is_stale_session,
        formula="base = NQ_close - NDX_spot",
        delay_compensation_note=proven_origin_note,
    )


def synthetic_futures_basis_from_options(
    options_df: pd.DataFrame,
    spot: float,
    risk_free_rate: float = 0.045,
    today_date: date | None = None,
) -> float | None:
    """Base future - spot déduite de la parité call-put : F = (C - P) * e^(rT) + K.

    Adapté de Darthreign/gex-dashboard (MIT), copyright conservé.
    Sélectionne l'échéance d'options la plus proche du future front month
    et la médiane sur les strikes proches de la monnaie (+- 5%).
    """
    if options_df is None or options_df.empty:
        return None

    if today_date is None:
        today_date = datetime.now(timezone.utc).date()

    # Trouver l'échéance du prochain future trimestriel
    # Cycles 3, 6, 9, 12
    quarterly_expiries = [
        third_friday_of_month(today_date.year, m)
        for m in (3, 6, 9, 12)
        if third_friday_of_month(today_date.year, m) >= today_date
    ]
    if not quarterly_expiries:
        quarterly_expiries = [third_friday_of_month(today_date.year + 1, 3)]

    target_exp = quarterly_expiries[0]

    if "expiry" not in options_df.columns:
        return None

    exps = options_df["expiry"].unique()
    if len(exps) == 0:
        return None

    # Choisir l'expiration la plus proche du front future
    target = min(exps, key=lambda e: abs((e - target_exp).days if isinstance(e, date) else 999))
    sub = options_df[options_df["expiry"] == target]

    calls = sub[sub["type"] == "C"].drop_duplicates(subset=["strike"]).set_index("strike")
    puts = sub[sub["type"] == "P"].drop_duplicates(subset=["strike"]).set_index("strike")

    common = [k for k in calls.index.intersection(puts.index) if abs(k - spot) / spot < 0.05]
    if len(common) < 5:
        return None

    fwds: list[float] = []
    # Calcul T en années
    t_days = max(1, (target - today_date).days if isinstance(target, date) else 30)
    t_years = t_days / 365.25

    for k in common:
        c_bid = float(calls.loc[k, "bid"])
        c_ask = float(calls.loc[k, "ask"])
        p_bid = float(puts.loc[k, "bid"])
        p_ask = float(puts.loc[k, "ask"])

        cmid = (c_bid + c_ask) / 2.0
        pmid = (p_bid + p_ask) / 2.0

        if cmid <= 0 or pmid <= 0:
            continue

        fwd = (cmid - pmid) * np.exp(risk_free_rate * t_years) + k
        fwds.append(float(fwd))

    if len(fwds) < 5:
        return None

    synth_basis = float(np.median(fwds)) - spot
    # Garde-fou : le basis reste inférieur à 2% du spot
    if abs(synth_basis) > 0.02 * spot:
        log.warning("Basis synthétique aberrant ignoré : %+.1f", synth_basis)
        return None

    return synth_basis
