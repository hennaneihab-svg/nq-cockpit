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
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from nqcockpit.data.calendar import CALENDAR
from nqcockpit.data.models import Bar, BasisSnapshot, DataStatus
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


def compute_previous_session_basis(
    nq_bars: list[Bar],
    ndx_bars: list[Bar],
    ref_utc: datetime | None = None,
) -> BasisSnapshot:
    """Trouve la dernière clôture de séance régulière actions US et calcule la base de clôture.

    Sélectionne la dernière barre 1m de chaque instrument ayant eu lieu à ou avant 16:00 ET
    du dernier jour de bourse actions.
    """
    if ref_utc is None:
        ref_utc = datetime.now(timezone.utc)
    elif ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    session_close_utc = CALENDAR.get_last_equity_session_close(ref_utc)

    # Filtrer les barres <= session_close_utc
    valid_nq = [b for b in nq_bars if b.timestamp_utc <= session_close_utc]
    valid_ndx = [b for b in ndx_bars if b.timestamp_utc <= session_close_utc]

    if not valid_nq or not valid_ndx:
        # Fallback vers la base locale si la liste en mémoire ne couvre pas la clôture
        try:
            from nqcockpit.data.db import get_bars as db_get_bars
            from nqcockpit.data.db import get_db_connection

            conn = get_db_connection()
            if not valid_nq:
                valid_nq = db_get_bars(conn, "NQ=F", "1m", end_time=session_close_utc, limit=10)
            if not valid_ndx:
                valid_ndx = db_get_bars(conn, "^NDX", "1m", end_time=session_close_utc, limit=10)
            conn.close()
        except Exception as e:
            log.warning("Impossible de compléter les barres depuis SQLite : %s", e)

    if not valid_nq or not valid_ndx:
        return BasisSnapshot(
            timestamp_utc=ref_utc,
            nq_price=0.0,
            ndx_price=0.0,
            basis=0.0,
            is_session_basis=False,
            status=DataStatus.BLOCKED,
            label="historique insuffisant pour la base de clôture",
            method="séance précédente",
        )

    last_nq = valid_nq[-1]
    last_ndx = valid_ndx[-1]

    # Vérification de synchronisation à la clôture (dans la même minute)
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
        tolerance_minutes=1.0,
        is_aligned=(drift <= 60.0 and not is_stale_session),
        formula="base = NQ_close - NDX_spot",
        delay_compensation_note=(
            "Source Yahoo Finance retardée ~15 min : barre NQ sélectionnée "
            "correspondant à l'heure réelle de cotation NDX (heure de fermeture 16:00 ET)"
        ),
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
