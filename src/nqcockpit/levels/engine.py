"""Moteur de calcul des niveaux de gamma (GEX, murs, flip, expected move) et conversion NQ.

Adapté de Darthreign/gex-dashboard (MIT), copyright conservé.

Règles de conformité :
- .agents/skills/gex-methodology/SKILL.md
- docs/vendor_audit.md (Section 3)
- docs/THIRD_PARTY_LICENSES.md
- Aucun biais directionnel haussier/baissier : uniquement des niveaux et des faits de volatilité.
- Chaque chiffre porte source, horodatage, âge, statut et drapeau "OI de la veille".
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from nqcockpit.config import load_config
from nqcockpit.data.basis import (
    compute_live_basis,
    compute_previous_session_basis,
    find_basis_pair,
    synthetic_futures_basis_from_options,
)
from nqcockpit.data.calendar import CALENDAR
from nqcockpit.data.cboe import OCC_RE, CboeChainSnapshot
from nqcockpit.data.db import apply_migrations, get_db_connection, insert_snapshot
from nqcockpit.data.models import Bar, BasisSnapshot, DataStatus, PairResult
from nqcockpit.levels import greeks
from nqcockpit.levels.models import (
    Diagnostic1cInfo,
    ExpectedMoveInfo,
    GammaWall,
    LevelsSnapshot,
    StraddleDiagnostic,
    StraddleLegInfo,
    StraddleStrikeNeighbor,
)

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
TZ_ALGIERS = ZoneInfo("Africa/Algiers")
_ALGIERS_FMT = "%Y-%m-%d %H:%M:%S (Alger)"
_ET_FMT = "%Y-%m-%d %H:%M:%S ET"


def _fmt_et(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(ET).strftime(_ET_FMT)


def _fmt_algiers(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(TZ_ALGIERS).strftime(_ALGIERS_FMT)


def _format_quote_time(val: Any) -> tuple[str | None, str | None]:
    """Formate une date/heure de cotation CBOE en ET et Alger."""
    if not val or not isinstance(val, str):
        return None, None
    clean = val.strip().replace("Z", "")
    try:
        if "T" in clean:
            dt_raw = datetime.fromisoformat(clean)
        else:
            dt_raw = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        if dt_raw.tzinfo is None:
            dt_utc = dt_raw.replace(tzinfo=ET).astimezone(timezone.utc)
        else:
            dt_utc = dt_raw.astimezone(timezone.utc)
        et_str = dt_utc.astimezone(ET).strftime(_ET_FMT)
        alg_str = dt_utc.astimezone(TZ_ALGIERS).strftime(_ALGIERS_FMT)
        return et_str, alg_str
    except Exception:
        return str(val), str(val)


CONTRACT_MULTIPLIER = 100.0  # Multiplicateur d'options sur indice NDX
ZG_RANGE = 0.08  # Grille +/- 8%
ZG_STEPS = 101


def compute_gamma_exposure(
    df: pd.DataFrame,
    spot: float,
) -> pd.DataFrame:
    """Calcule le GEX par contrat selon la méthodologie standard ($ par 1% de variation).

    Formule : sign * gamma * OI * 100 * spot^2 * 0.01 (Calls +, Puts -).
    """
    if df.empty:
        return df

    d = df.copy()
    sign = np.where(d["type"] == "C", 1.0, -1.0)
    oi = d["open_interest"].fillna(0.0).to_numpy()
    gamma_val = d["gamma"].fillna(0.0).to_numpy()

    d["gex"] = sign * gamma_val * oi * CONTRACT_MULTIPLIER * (spot**2) * 0.01
    return d


def calculate_gamma_profile(
    df: pd.DataFrame,
    spot: float,
    risk_free_rate: float = 0.045,
    today_date: date | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Recalcule le GEX net sur une grille de spots hypothétiques (+/- 8%)."""
    if df.empty:
        return None

    valid = df[(df["iv"] > 1e-4) & (df["open_interest"] > 0)].copy()
    if valid.empty:
        return None

    if today_date is None:
        today_date = datetime.now(timezone.utc).date()

    # Calcul du temps à expiration en années pour chaque contrat
    if "t_years" not in valid.columns:
        valid["t_years"] = valid["expiry"].apply(
            lambda exp: max(1, (exp - today_date).days if isinstance(exp, date) else 1) / 365.25
        )

    grid = np.linspace(spot * (1 - ZG_RANGE), spot * (1 + ZG_RANGE), ZG_STEPS)

    k = valid["strike"].to_numpy()[:, None]
    t = valid["t_years"].to_numpy()[:, None]
    iv = valid["iv"].to_numpy()[:, None]
    oi = valid["open_interest"].to_numpy()[:, None]
    sign = np.where(valid["type"].to_numpy()[:, None] == "C", 1.0, -1.0)

    # Gamma vectorisé sur la grille
    g = greeks.gamma(grid[None, :], k, t, risk_free_rate, iv)
    profile = (sign * g * oi * CONTRACT_MULTIPLIER * (grid[None, :] ** 2) * 0.01).sum(axis=0)

    return grid, profile


def calculate_zero_gamma(
    grid: np.ndarray,
    profile: np.ndarray,
    spot: float,
) -> float | None:
    """Interpole le passage par zéro le plus proche du spot actuel.

    Retourne None si aucun croisement de zéro n'est détecté (flip absent = valide).
    """
    crossings = np.where(np.diff(np.sign(profile)) != 0)[0]
    if len(crossings) == 0:
        return None

    # Trouver le croisement le plus proche du spot
    idx = crossings[int(np.argmin(np.abs(grid[crossings] - spot)))]
    x0, x1 = grid[idx], grid[idx + 1]
    y0, y1 = profile[idx], profile[idx + 1]

    if y1 == y0:
        return float(x0)

    # Interpolation linéaire
    zero_spot = float(x0 - y0 * (x1 - x0) / (y1 - y0))
    return zero_spot


def get_reference_session_date(ref_utc: datetime) -> date:
    """Détermine la session de référence selon le calendrier US actions.

    Session de référence = la séance en cours si la séance US est ouverte,
    sinon la prochaine séance de bourse (pandas_market_calendars).
    """
    if ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    ref_et = ref_utc.astimezone(ET)
    ref_d = ref_et.date()

    if CALENDAR.is_us_equity_regular_hours(ref_utc):
        return ref_d

    # Si jour ouvré avant l'ouverture de 09:30 ET : la séance de référence est aujourd'hui
    if CALENDAR.is_trading_day(ref_d) and ref_et.time() < time(9, 30):
        return ref_d

    # Après la clôture (>= 16:00 ET) ou week-end/férié : prochaine séance de bourse
    start_d = ref_d + timedelta(days=1)
    end_d = ref_d + timedelta(days=12)
    valid = CALENDAR._nasdaq.valid_days(
        start_date=start_d.isoformat(), end_date=end_d.isoformat()
    )
    if len(valid) > 0:
        return valid[0].date()
    return ref_d + timedelta(days=1)


def _parse_quote_datetime_utc(val: Any) -> datetime | None:
    """Parse un horodatage de cotation (texte ou datetime) en datetime UTC."""
    if val is None or not isinstance(val, (str, datetime)):
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s_clean = s[:-1]
            if "T" in s_clean:
                return datetime.fromisoformat(s_clean).replace(tzinfo=timezone.utc)
            return datetime.strptime(s_clean, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        if "T" in s:
            dt_raw = datetime.fromisoformat(s)
            if dt_raw.tzinfo is None:
                return dt_raw.replace(tzinfo=ET).astimezone(timezone.utc)
            return dt_raw.astimezone(timezone.utc)
        dt_raw = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        if dt_raw.tzinfo is None:
            return dt_raw.replace(tzinfo=ET).astimezone(timezone.utc)
        return dt_raw.astimezone(timezone.utc)
    except Exception:
        return None


def calculate_expected_move(
    df: pd.DataFrame,
    spot: float,
    ref_utc: datetime | None = None,
    today_date: date | None = None,
    cboe_quote_time_utc: datetime | None = None,
) -> ExpectedMoveInfo | None:
    """Calcule le move attendu 1 sigma (formule analytique ET straddle ATM du front).

    - T = temps calendaire restant jusqu'à l'expiration calculé depuis l'horodatage
      de la chaîne CBOE (pas d'heure codée en dur).
    - Base ACT/365 pour correspondre à l'annualisation de l'IV CBOE :
      T_years = (exp_utc - cboe_utc) / (365 * 86400).
    - Formule analytique 1σ : S * IV_ATM * sqrt(T_years).
    - Straddle de marché ATM (C_mid + P_mid) ≈ 0,8σ (Brenner-Subrahmanyam).
    - Comparaison à unités égales : straddle_marché vs straddle_théo (0,8 * 1σ).
    """
    if df.empty:
        return None

    nearest_exp = df["expiry"].min()
    sub = df[df["expiry"] == nearest_exp]
    if sub.empty:
        return None

    # Extraction de l'horodatage effectif de cotation CBOE
    cboe_ts: datetime | None = cboe_quote_time_utc
    if cboe_ts is None and "last_trade_time" in sub.columns:
        parsed_dates = []
        for v in sub["last_trade_time"].dropna():
            p_dt = _parse_quote_datetime_utc(v)
            if p_dt is not None:
                parsed_dates.append(p_dt)
        if parsed_dates:
            cboe_ts = max(parsed_dates)

    if cboe_ts is None:
        if ref_utc is not None:
            cboe_ts = (
                ref_utc
                if ref_utc.tzinfo is not None
                else ref_utc.replace(tzinfo=timezone.utc)
            )
        elif today_date is not None:
            cboe_ts = datetime.combine(today_date, time(12, 0), tzinfo=ET).astimezone(
                timezone.utc
            )
        else:
            cboe_ts = datetime.now(timezone.utc)
    elif cboe_ts.tzinfo is None:
        cboe_ts = cboe_ts.replace(tzinfo=timezone.utc)

    # Heure d'échéance : AM (09:30 ET) pour NDX mensuel 3e vendredi, PM (16:00 ET) sinon
    is_third_friday = (
        (nearest_exp.weekday() == 4 and 15 <= nearest_exp.day <= 21)
        if isinstance(nearest_exp, date)
        else False
    )
    is_ndxp = any(str(c).startswith("NDXP") for c in sub.get("contract", []))
    if not is_ndxp and is_third_friday:
        exp_time = time(9, 30)
    else:
        exp_time = time(16, 0)

    if isinstance(nearest_exp, date):
        exp_dt_et = datetime.combine(nearest_exp, exp_time, tzinfo=ET)
        exp_dt_utc = exp_dt_et.astimezone(timezone.utc)
    else:
        exp_dt_utc = cboe_ts + timedelta(days=1)

    # Calcul des jours de bourse (convention trading days)
    eval_dt = ref_utc or cboe_ts
    ref_session = get_reference_session_date(eval_dt)
    in_regular = CALENDAR.is_us_equity_regular_hours(eval_dt)
    if isinstance(nearest_exp, date):
        if nearest_exp == ref_session:
            if in_regular:
                trading_days = CALENDAR.calculate_trading_days_to_expiry(
                    eval_dt, nearest_exp
                )
            else:
                trading_days = 1.0
        else:
            trading_days = CALENDAR.calculate_trading_days_to_expiry(
                eval_dt, nearest_exp
            )
    else:
        trading_days = 1.0

    delta_sec = (exp_dt_utc - cboe_ts).total_seconds()
    if delta_sec < 60.0:
        delta_sec = 60.0  # minimum 1 min pour éviter division par zéro

    t_hours = delta_sec / 3600.0
    t_years = delta_sec / (365.0 * 86400.0)
    days_to_expiry = float(trading_days)

    # IV ATM : strike le plus proche du spot
    sub_valid_iv = sub[sub["iv"] > 1e-4]
    if sub_valid_iv.empty:
        return None

    atm_idx = (sub_valid_iv["strike"] - spot).abs().idxmin()
    iv_atm = float(sub_valid_iv.loc[atm_idx, "iv"])

    # Formule analytique 1 sigma : S * IV * sqrt(T_years)
    formula_move = float(spot * iv_atm * np.sqrt(t_years))

    # Prix du straddle ATM du front (C_atm + P_atm) et Diagnostic Straddle détaillé
    straddle_move = None
    straddle_diag: StraddleDiagnostic | None = None
    atm_strike = float(sub_valid_iv.loc[atm_idx, "strike"])
    call_atm = sub[(sub["strike"] == atm_strike) & (sub["type"] == "C")]
    put_atm = sub[(sub["strike"] == atm_strike) & (sub["type"] == "P")]

    if not call_atm.empty and not put_atm.empty:
        c_row = call_atm.iloc[0]
        p_row = put_atm.iloc[0]

        c_bid = float(c_row["bid"])
        c_ask = float(c_row["ask"])
        p_bid = float(p_row["bid"])
        p_ask = float(p_row["ask"])

        c_last = float(c_row["last_trade_price"])
        p_last = float(p_row["last_trade_price"])
        c_mid = (c_bid + c_ask) / 2.0 if (c_bid + c_ask) > 0 else c_last
        p_mid = (p_bid + p_ask) / 2.0 if (p_bid + p_ask) > 0 else p_last

        if c_mid > 0 and p_mid > 0:
            straddle_move = float(c_mid + p_mid)

        # Extraction des racines OCC
        c_sym = str(c_row.get("contract", ""))
        p_sym = str(p_row.get("contract", ""))
        m_c = OCC_RE.match(c_sym)
        m_p = OCC_RE.match(p_sym)
        c_root = m_c.group("root") if m_c else "NDX"
        p_root = m_p.group("root") if m_p else "NDX"

        c_exp = c_row["expiry"] if isinstance(c_row["expiry"], date) else nearest_exp
        p_exp = p_row["expiry"] if isinstance(p_row["expiry"], date) else nearest_exp

        c_spread_rel = (c_ask - c_bid) / c_mid * 100.0 if c_mid > 0 else 0.0
        p_spread_rel = (p_ask - p_bid) / p_mid * 100.0 if p_mid > 0 else 0.0

        try:
            cfg = load_config()
            max_spread_pct = (
                getattr(cfg.levels, "straddle_max_spread_pct", 0.20) * 100.0
            )
        except Exception:
            max_spread_pct = 20.0

        c_time_et, c_time_alg = _format_quote_time(c_row.get("last_trade_time"))
        p_time_et, p_time_alg = _format_quote_time(p_row.get("last_trade_time"))

        c_leg = StraddleLegInfo(
            option_type="C",
            root=c_root,
            expiry=c_exp,
            strike=atm_strike,
            bid=c_bid,
            ask=c_ask,
            mid=c_mid,
            spread_rel_pct=c_spread_rel,
            iv=float(c_row.get("iv", 0.0)),
            volume=float(c_row.get("volume", 0.0)),
            quote_time_et=c_time_et,
            quote_time_algiers=c_time_alg,
            is_spread_wide=(c_spread_rel > max_spread_pct),
        )

        p_leg = StraddleLegInfo(
            option_type="P",
            root=p_root,
            expiry=p_exp,
            strike=atm_strike,
            bid=p_bid,
            ask=p_ask,
            mid=p_mid,
            spread_rel_pct=p_spread_rel,
            iv=float(p_row.get("iv", 0.0)),
            volume=float(p_row.get("volume", 0.0)),
            quote_time_et=p_time_et,
            quote_time_algiers=p_time_alg,
            is_spread_wide=(p_spread_rel > max_spread_pct),
        )

        roots_match = c_root == p_root
        expiries_match = c_exp == p_exp
        straddle_pts = c_mid + p_mid

        # Unités égales :
        # Le straddle de marché est ≈ 0,8σ (Brenner-Subrahmanyam :
        # straddle ≈ sqrt(2/pi)*sigma*S*sqrt(T) ≈ 0.8 * 1σ)
        # Move théorique straddle dérivé de l'IV : straddle_theo = 0.8 * formula_move
        # Move 1σ équivalent dérivé du straddle : straddle_1s_equiv = straddle_pts / 0.8
        straddle_theo = 0.8 * formula_move
        straddle_1s_equiv = straddle_pts / 0.8 if straddle_pts > 0 else 0.0

        # IV implicite du straddle via approximation Brenner-Subrahmanyam inversée :
        # IV = straddle / (0.8 * spot * sqrt(T_years))
        implied_iv = 0.0
        denom_iv = 0.8 * spot * np.sqrt(t_years)
        if denom_iv > 0:
            implied_iv = straddle_pts / denom_iv

        # Comparaison à unités égales 0,8σ
        spread_pct_vs_iv = 0.0
        denom_comp = max(abs(straddle_pts), abs(straddle_theo))
        if denom_comp > 0:
            spread_pct_vs_iv = abs(straddle_pts - straddle_theo) / denom_comp * 100.0

        # Les 3 strikes voisins ATM (ATM-1, ATM, ATM+1)
        unique_strikes = np.sort(sub["strike"].unique())
        atm_pos = np.where(unique_strikes == atm_strike)[0]
        neighbors: list[StraddleStrikeNeighbor] = []
        if len(atm_pos) > 0:
            idx_k = int(atm_pos[0])
            start_k = max(0, idx_k - 1)
            end_k = min(len(unique_strikes), idx_k + 2)
            for k_val in unique_strikes[start_k:end_k]:
                c_k = sub[(sub["strike"] == k_val) & (sub["type"] == "C")]
                p_k = sub[(sub["strike"] == k_val) & (sub["type"] == "P")]
                c_k_mid = 0.0
                p_k_mid = 0.0
                if not c_k.empty:
                    cb = float(c_k.iloc[0]["bid"])
                    ca = float(c_k.iloc[0]["ask"])
                    cl = float(c_k.iloc[0]["last_trade_price"])
                    c_k_mid = (cb + ca) / 2.0 if (cb + ca) > 0 else cl
                if not p_k.empty:
                    pb = float(p_k.iloc[0]["bid"])
                    pa = float(p_k.iloc[0]["ask"])
                    pl = float(p_k.iloc[0]["last_trade_price"])
                    p_k_mid = (pb + pa) / 2.0 if (pb + pa) > 0 else pl
                neighbors.append(
                    StraddleStrikeNeighbor(
                        strike=float(k_val),
                        call_mid=c_k_mid,
                        put_mid=p_k_mid,
                        straddle_mid=c_k_mid + p_k_mid,
                    )
                )

        # Cause calculée dynamiquement
        c_spr = max(0.0, c_ask - c_bid)
        p_spr = max(0.0, p_ask - p_bid)
        spr_total = c_spr + p_spr
        spr_impact_pct = (
            (spr_total / straddle_pts) * 100.0 if straddle_pts > 0 else 0.0
        )
        iv_diff_pct = (
            ((implied_iv - iv_atm) / iv_atm * 100.0) if iv_atm > 0 else 0.0
        )

        if spread_pct_vs_iv <= 25.0:
            calculated_cause = (
                f"Cohérent à unités égales 0,8σ (écart {spread_pct_vs_iv:.1f}% <= 25%) : "
                f"IV straddle {implied_iv * 100:.2f}% vs IV CBOE {iv_atm * 100:.2f}% "
                f"(delta {iv_diff_pct:+.1f}%) sur T={t_hours:.1f}h"
            )
        else:
            if iv_diff_pct > 25.0:
                vol_expl = (
                    f"prime de volatilité du straddle (IV straddle {implied_iv * 100:.2f}% "
                    f"soit +{iv_diff_pct:.1f}% vs IV CBOE {iv_atm * 100:.2f}%) "
                    "liée à la demande sur les options ATM (skew/prime d'événement)"
                )
            elif iv_diff_pct < -25.0:
                vol_expl = (
                    f"décote de volatilité du straddle (IV straddle {implied_iv * 100:.2f}% "
                    f"soit {iv_diff_pct:.1f}% vs IV CBOE {iv_atm * 100:.2f}%) "
                    "liée à une détente post-événement ou liquidité réduite"
                )
            else:
                vol_expl = (
                    f"écart de pricing de volatilité (IV straddle {implied_iv * 100:.2f}% "
                    f"vs IV CBOE {iv_atm * 100:.2f}%, delta {iv_diff_pct:+.1f}%)"
                )
            spread_expl = (
                f"incertitude bid-ask de {spr_impact_pct:.1f}% sur le straddle "
                f"({c_root} C spread {c_spread_rel:.1f}%, P spread {p_spread_rel:.1f}%)"
            )
            calculated_cause = (
                f"Écart {spread_pct_vs_iv:.1f}% > 25% à 0,8σ [T={t_hours:.1f}h] : "
                f"{vol_expl} ; {spread_expl}"
            )

        is_diag_degraded = False
        reasons: list[str] = []
        if not roots_match:
            is_diag_degraded = True
            reasons.append(f"Racines divergentes ({c_root} vs {p_root})")
        if not expiries_match:
            is_diag_degraded = True
            reasons.append(f"Échéances divergentes ({c_exp} vs {p_exp})")
        if c_leg.is_spread_wide:
            is_diag_degraded = True
            reasons.append(
                f"Spread Call relatif large ({c_spread_rel:.1f}% > {max_spread_pct:.0f}%)"
            )
        if p_leg.is_spread_wide:
            is_diag_degraded = True
            reasons.append(
                f"Spread Put relatif large ({p_spread_rel:.1f}% > {max_spread_pct:.0f}%)"
            )
        if spread_pct_vs_iv > 25.0:
            is_diag_degraded = True
            reasons.append(calculated_cause)

        straddle_diag = StraddleDiagnostic(
            spot_ndx_used=spot,
            atm_strike=atm_strike,
            call_leg=c_leg,
            put_leg=p_leg,
            roots_match=roots_match,
            expiries_match=expiries_match,
            straddle_points=straddle_pts,
            implied_iv_straddle=implied_iv,
            iv_atm_used=iv_atm,
            spread_pct_vs_iv=spread_pct_vs_iv,
            time_to_expiry_hours=t_hours,
            time_to_expiry_years=t_years,
            formula_move_1sigma=formula_move,
            straddle_move_1sigma_equiv=straddle_1s_equiv,
            straddle_theo_from_iv=straddle_theo,
            calculated_cause=calculated_cause,
            neighbors=neighbors,
            is_degraded=is_diag_degraded,
            degraded_reason=" | ".join(reasons) if reasons else calculated_cause,
        )

    return ExpectedMoveInfo(
        formula_move=formula_move,
        straddle_move=straddle_move,
        iv_atm=iv_atm,
        days_to_expiry=float(days_to_expiry),
        lower_bound_ndx=spot - formula_move,
        upper_bound_ndx=spot + formula_move,
        lower_bound_nq=0.0,  # sera rempli avec la base
        upper_bound_nq=0.0,
        expiry=nearest_exp if isinstance(nearest_exp, date) else None,
        straddle_diagnostic=straddle_diag,
        time_to_expiry_hours=t_hours,
        time_to_expiry_years=t_years,
    )


def calculate_max_pain(
    df: pd.DataFrame,
    target_expiry: date | None = None,
) -> float | None:
    """Calcule le strike Max Pain pour UNE échéance spécifique.

    Si target_expiry n'est pas spécifié, prend l'échéance la plus proche.
    Jamais toutes échéances confondues.
    """
    if df.empty:
        return None

    if target_expiry is None:
        target_expiry = df["expiry"].min()

    sub = df[df["expiry"] == target_expiry]
    if sub.empty:
        return None

    valid = sub[sub["open_interest"] > 0]
    if valid.empty:
        return None

    strikes = np.sort(valid["strike"].unique())
    if len(strikes) == 0:
        return None

    total_loss: list[float] = []
    for s_eval in strikes:
        loss = 0.0
        # Calls perdent si s_eval > strike
        calls = valid[valid["type"] == "C"]
        if not calls.empty:
            intrinsic_c = np.maximum(0.0, s_eval - calls["strike"].to_numpy())
            loss += float(np.sum(intrinsic_c * calls["open_interest"].to_numpy()))

        # Puts perdent si s_eval < strike
        puts = valid[valid["type"] == "P"]
        if not puts.empty:
            intrinsic_p = np.maximum(0.0, puts["strike"].to_numpy() - s_eval)
            loss += float(np.sum(intrinsic_p * puts["open_interest"].to_numpy()))

        total_loss.append(loss)

    min_idx = int(np.argmin(total_loss))
    return float(strikes[min_idx])






def build_diagnostic_1c(
    nq_bars: list[Bar] | None = None,
    ndx_bars: list[Bar] | None = None,
    ref_utc: datetime | None = None,
    session_date: date | None = None,
    tolerance_minutes: float = 1.0,
    pair_result: PairResult | None = None,
) -> Diagnostic1cInfo:
    """Construit le Diagnostic 1c prouvé pour la séance de référence précédente.

    Lit obligatoirement le PairResult UNIQUE retourné par find_basis_pair,
    garantissant une stricte cohérence avec compute_previous_session_basis.
    """
    if session_date is None:
        if pair_result is not None:
            session_date = pair_result.target_utc.astimezone(ET).date()
        elif ref_utc is not None:
            session_date = CALENDAR.get_last_equity_session_close(ref_utc).astimezone(ET).date()
        else:
            session_date = datetime.now(ET).date()

    target_et = datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        16,
        0,
        0,
        tzinfo=ET,
    )
    target_utc = target_et.astimezone(timezone.utc)

    if pair_result is None:
        try:
            cfg = load_config()
            target_tol = getattr(cfg.data, "target_tolerance_minutes", 15.0)
        except Exception:
            target_tol = 15.0
        pair_result = find_basis_pair(
            target=target_utc,
            nq_bars=nq_bars,
            ndx_bars=ndx_bars,
            tolerance_minutes=tolerance_minutes,
            target_tolerance_minutes=target_tol,
        )

    target_et_str = target_et.strftime(_ET_FMT)
    target_alg_str = target_et.astimezone(TZ_ALGIERS).strftime(_ALGIERS_FMT)

    # Récapitulatif structuré des étapes de recherche
    search_steps_summary: list[str] = []
    for step in pair_result.search_steps:
        s_name = (
            "Mémoire"
            if step.step_name == "memoire"
            else ("SQLite" if step.step_name == "sqlite" else "Source distante")
        )
        nq_res = "NQ trouvé" if step.nq_found else "NQ non trouvé"
        ndx_res = "NDX trouvé" if step.ndx_found else "NDX non trouvé"
        search_steps_summary.append(
            f"{s_name} : {nq_res} | {ndx_res} ({step.details})"
        )

    nq_bar = pair_result.nq_bar
    ndx_bar = pair_result.ndx_bar

    # Statistiques barres mémoire du jour (informatif)
    nq_count = 0
    nq_first = None
    nq_last = None
    if nq_bars:
        nq_day = [
            b
            for b in nq_bars
            if b.timestamp_utc.astimezone(ET).date() == session_date
        ]
        nq_count = len(nq_day)
        nq_first = _fmt_et(nq_day[0].timestamp_utc) if nq_day else None
        nq_last = _fmt_et(nq_day[-1].timestamp_utc) if nq_day else None

    return Diagnostic1cInfo(
        session_date=session_date,
        target_time_et=target_et_str,
        target_time_algiers=target_alg_str,
        target_time_utc=target_utc,
        nq_candidate_found=nq_bar is not None,
        nq_candidate_time_et=_fmt_et(nq_bar.timestamp_utc) if nq_bar else None,
        nq_candidate_time_algiers=(
            _fmt_algiers(nq_bar.timestamp_utc) if nq_bar else None
        ),
        nq_candidate_close=nq_bar.close if nq_bar else None,
        nq_origin=pair_result.nq_origin,
        nq_bars_count_day=nq_count,
        nq_first_bar_time=nq_first,
        nq_last_bar_time=nq_last,
        ndx_candidate_found=ndx_bar is not None,
        ndx_candidate_time_et=(
            _fmt_et(ndx_bar.timestamp_utc) if ndx_bar else None
        ),
        ndx_candidate_time_algiers=(
            _fmt_algiers(ndx_bar.timestamp_utc) if ndx_bar else None
        ),
        ndx_candidate_spot=ndx_bar.close if ndx_bar else None,
        ndx_origin=pair_result.ndx_origin,
        search_steps_summary=search_steps_summary,
        delta_t_minutes=pair_result.delta_t_minutes,
        tolerance_minutes=pair_result.tolerance_minutes,
        cause_code=pair_result.cause_code,
        cause_detail=pair_result.cause_detail,
        action_taken=pair_result.action_taken,
    )



def enrich_expected_move_nq(
    em: ExpectedMoveInfo,
    basis: float,
    spot_nq: float,
    spot_ndx: float,
    cboe_age_minutes: float | None,
) -> ExpectedMoveInfo:
    """Complète ExpectedMoveInfo avec les champs NQ et le contrôle de cohérence.

    - straddle_move_nq : prix straddle ATM NDX converti en points NQ via base
    - iv_move_nq : formule IV en points NQ
    - discrepancy_pct : |straddle - IV| / max(straddle, IV)
    - is_coherent : discrepancy < 25 %
    """

    # Bornes NQ via formule IV (déjà calculées : formula_move est en points NDX)
    iv_move_nq = em.formula_move  # NDX pts ≈ NQ pts (échelle similaire, base additive)
    iv_lower_nq = spot_nq - iv_move_nq
    iv_upper_nq = spot_nq + iv_move_nq

    # Straddle NDX converti en NQ
    straddle_move_nq: float | None = None
    straddle_lower_nq: float | None = None
    straddle_upper_nq: float | None = None
    if em.straddle_move is not None:
        # Le straddle est en points NDX (bid/ask des options NDX)
        straddle_move_nq = em.straddle_move
        straddle_lower_nq = spot_nq - straddle_move_nq
        straddle_upper_nq = spot_nq + straddle_move_nq

    # Jour de la semaine de l'échéance
    expiry_dow: str | None = None
    if em.expiry is not None:
        expiry_dow = em.expiry.strftime("%A %d/%m/%Y")

    # Contrôle cohérence à unités égales (straddle ≈ 0,8σ)
    discrepancy_pct: float | None = None
    is_coherent = True
    status = DataStatus.OK
    status_explanation: str | None = None

    if em.straddle_diagnostic is not None:
        discrepancy_pct = em.straddle_diagnostic.spread_pct_vs_iv
        is_coherent = not em.straddle_diagnostic.is_degraded
        status = (
            DataStatus.DEGRADED
            if em.straddle_diagnostic.is_degraded
            else DataStatus.OK
        )
        status_explanation = (
            em.straddle_diagnostic.degraded_reason
            if em.straddle_diagnostic.is_degraded
            else f"Cohérence validée à unités égales 0,8σ (écart {discrepancy_pct:.1f}% <= 25%)"
        )
    elif straddle_move_nq is not None and iv_move_nq > 0:
        denom = max(abs(straddle_move_nq), abs(iv_move_nq))
        discrepancy_pct = abs(straddle_move_nq - iv_move_nq) / denom * 100.0
        if discrepancy_pct > 25.0:
            is_coherent = False
            status = DataStatus.DEGRADED
            status_explanation = (
                f"Écart méthodes straddle vs IV = {discrepancy_pct:.1f}% > 25% "
                f"(straddle: {straddle_move_nq:.1f} pts NQ, IV: {iv_move_nq:.1f} pts NQ) "
                "— données à interpréter avec prudence, sans ajustement forcé"
            )

    em.straddle_move_nq = straddle_move_nq
    em.straddle_lower_nq = straddle_lower_nq
    em.straddle_upper_nq = straddle_upper_nq
    em.iv_move_nq = iv_move_nq
    em.iv_lower_nq = iv_lower_nq
    em.iv_upper_nq = iv_upper_nq
    em.expiry_day_of_week = expiry_dow
    em.data_age_minutes = cboe_age_minutes
    em.discrepancy_pct = discrepancy_pct
    em.is_coherent = is_coherent
    em.status = status
    em.status_explanation = status_explanation
    # Mettre à jour les bornes NQ de la formule IV
    em.lower_bound_nq = spot_nq - iv_move_nq
    em.upper_bound_nq = spot_nq + iv_move_nq

    # Tâche 4 : Distinction claire spot NDX formule vs spot NQ centrage
    spot_nq_conv = spot_ndx + basis
    em.spot_ndx_used = spot_ndx
    em.spot_nq_observed = spot_nq
    em.spot_nq_converted = spot_nq_conv
    em.spread_nq_vs_converted = spot_nq - spot_nq_conv
    return em


class LevelsEngine:
    """Moteur de calcul de niveaux gamma, expected move et conversion vers NQ."""

    def __init__(self, output_dir: Path | str = Path("data/levels")) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compute_snapshot(
        self,
        chain: CboeChainSnapshot,
        nq_bars: list[Bar],
        ndx_bars: list[Bar],
        now_utc: datetime | None = None,
    ) -> LevelsSnapshot:
        """Calcule un snapshot complet à partir de la chaîne d'options et des barres."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        anomalies: list[str] = []
        spot_ndx = chain.spot
        ref_session_date = get_reference_session_date(now_utc)

        # 1. Base synthétique par parité Call-Put
        synth_basis = synthetic_futures_basis_from_options(
            chain.options_df,
            spot_ndx,
            today_date=ref_session_date,
        )

        try:
            cfg = load_config()
            tol = getattr(cfg.data, "parity_basis_tolerance_points", 50.0)
            target_tol = getattr(cfg.data, "target_tolerance_minutes", 15.0)
        except Exception:
            tol = 50.0
            target_tol = 15.0

        # 2. Recherche UNIQUE de la paire pour la séance précédente (lue par base et 1c)
        session_close_utc = CALENDAR.get_last_equity_session_close(now_utc)
        pair_result = find_basis_pair(
            target=session_close_utc,
            nq_bars=nq_bars,
            ndx_bars=ndx_bars,
            tolerance_minutes=1.0,
            target_tolerance_minutes=target_tol,
        )

        # 3. Ordre de priorité de la base NQ/NDX :
        #    (i)  Base alignée en séance (barres 1m NQ=F et ^NDX, écart <= 60s, séance en cours)
        #    (ii) Base de la séance précédente (via pair_result unique)
        #    (iii) Base implicite par parité call-put
        #          (fallback si écart > tolérance ou barres manquantes)
        in_regular_session = CALENDAR.is_us_equity_regular_hours(now_utc)
        candidate_basis: BasisSnapshot | None = None

        if in_regular_session and nq_bars and ndx_bars:
            last_nq = nq_bars[-1]
            best_ndx = min(
                ndx_bars,
                key=lambda b: abs((b.timestamp_utc - last_nq.timestamp_utc).total_seconds()),
            )
            live_snap = compute_live_basis(last_nq, best_ndx, now_utc=now_utc)
            if live_snap.status != DataStatus.BLOCKED:
                candidate_basis = live_snap

        if candidate_basis is None:
            prev_snap = compute_previous_session_basis(
                nq_bars, ndx_bars, ref_utc=now_utc, pair_result=pair_result
            )
            if prev_snap.status != DataStatus.BLOCKED:
                candidate_basis = prev_snap

        use_parity_fallback = False
        if candidate_basis is not None:
            if synth_basis is not None:
                parity_diff = abs(candidate_basis.basis - synth_basis)
                if parity_diff > tol:
                    use_parity_fallback = True
                    anomalies.append(
                        f"Écart base empirique ({candidate_basis.basis:+.2f})"
                        f" vs parité ({synth_basis:+.2f})"
                        f" = {parity_diff:.1f} pts > tolérance ({tol:.1f} pts)"
                        " : repli sur parité"
                    )
            if not use_parity_fallback:
                basis_val = candidate_basis.basis
                basis_lbl = candidate_basis.label
                basis_st = candidate_basis.status
            else:
                basis_val = synth_basis if synth_basis is not None else candidate_basis.basis
                basis_lbl = "base implicite (parité)"
                basis_st = DataStatus.DEGRADED
        else:
            if synth_basis is not None:
                basis_val = synth_basis
                basis_lbl = "base implicite (parité)"
                basis_st = DataStatus.DEGRADED
                anomalies.append(
                    "Barres NQ/NDX indisponibles : "
                    "utilisation de la base implicite (parité)"
                )
            else:
                basis_val = 0.0
                basis_lbl = "base indisponible"
                basis_st = DataStatus.BLOCKED
                anomalies.append("Aucune base disponible (ni barres ni parité)")

        # Spot NQ = dernier cours observé de NQ=F avec son horodatage et son âge réel (Tâche 1)
        # Ne présente JAMAIS un NQ dérivé comme un cours.
        # Prix NQ valide : multiple de 0,25.
        spot_nq_age_min: float | None = None
        spot_nq_is_stale = False
        spot_nq_time_utc: datetime | None = None

        try:
            cfg = load_config()
            spot_max_age = getattr(cfg.levels, "spot_max_age_minutes", 20.0)
            wall_win_pct = getattr(cfg.levels, "wall_window_pct", 0.10)
        except Exception:
            spot_max_age = 20.0
            wall_win_pct = 0.10

        from nqcockpit.sources.health import is_cme_futures_market_open

        if nq_bars:
            latest_obs_nq = nq_bars[-1]
            spot_nq = round(latest_obs_nq.close * 4.0) / 4.0
            spot_nq_time_utc = latest_obs_nq.timestamp_utc
            spot_nq_age_min = max(0.0, (now_utc - spot_nq_time_utc).total_seconds() / 60.0)
            nq_ts_ny = spot_nq_time_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S ET")
            nq_ts_alg = spot_nq_time_utc.astimezone(TZ_ALGIERS).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )

            cme_is_open = is_cme_futures_market_open(now_utc)
            if cme_is_open and spot_nq_age_min > spot_max_age:
                spot_nq_is_stale = True
                spot_delay_note = (
                    f"SPOT NQ PÉRIMÉ (âge {spot_nq_age_min:.1f} min > seuil {spot_max_age:.1f} min)"
                )
                anomalies.append(f"DÉGRADÉ : {spot_delay_note}")
            else:
                spot_delay_note = f"âge réel {spot_nq_age_min:.1f} min"

            anomalies.append(
                f"Spot NQ observé : {spot_nq:,.2f} pts"
                f" (cours NQ=F à {nq_ts_ny} | {nq_ts_alg}, {spot_delay_note})"
            )
        else:
            spot_nq = round((spot_ndx + basis_val) * 4.0) / 4.0 if spot_ndx > 0 else 0.0
            spot_delay_note = "cours estimé via NDX + base (barres NQ absentes)"
            spot_nq_is_stale = True
            anomalies.append("Spot NQ : barres NQ=F absentes, repli cours estimé")

        anomalies.append(
            "Niveaux NQ : tous les niveaux NQ (Flip, Walls, Expected Move, Max Pain) "
            "sont des « niveaux NQ (convertis) » via base"
        )

        # Tâche 2 : Base Live et comparatif des 3 bases
        live_basis_val: float | None = None
        live_basis_nq_ts: datetime | None = None
        live_basis_ndx_ts: datetime | None = None
        live_basis_delta_t: float | None = None
        live_basis_avail: bool = False
        live_basis_status: DataStatus = DataStatus.DEGRADED
        live_basis_unavail_reason: str | None = None

        tol_live_min = 1.0

        if nq_bars and ndx_bars:
            last_nq_bar = nq_bars[-1]
            live_basis_nq_ts = last_nq_bar.timestamp_utc
            best_ndx_match = min(
                ndx_bars,
                key=lambda b: abs((b.timestamp_utc - last_nq_bar.timestamp_utc).total_seconds()),
            )
            dt_s = abs((best_ndx_match.timestamp_utc - last_nq_bar.timestamp_utc).total_seconds())
            live_basis_delta_t = dt_s / 60.0
            live_basis_ndx_ts = best_ndx_match.timestamp_utc

            if live_basis_delta_t <= tol_live_min:
                live_basis_val = last_nq_bar.close - best_ndx_match.close
                live_basis_avail = True
                live_basis_status = DataStatus.OK
            else:
                live_basis_unavail_reason = (
                    f"Désalignement temporel ({live_basis_delta_t:.2f} min "
                    f"> tolérance {tol_live_min:.1f} min)"
                )
        elif not nq_bars and not ndx_bars:
            live_basis_unavail_reason = "Barres NQ et cotations NDX absentes"
        elif not nq_bars:
            live_basis_unavail_reason = "Barres NQ absentes"
        else:
            live_basis_unavail_reason = "Cotations NDX absentes"

        # Comparatif des 3 bases
        prev_basis_num = candidate_basis.basis if candidate_basis else None
        spread_live_prev = (
            (live_basis_val - prev_basis_num)
            if (live_basis_val is not None and prev_basis_num is not None)
            else None
        )
        spread_live_parity = (
            (live_basis_val - synth_basis)
            if (live_basis_val is not None and synth_basis is not None)
            else None
        )
        spread_prev_parity = (
            (prev_basis_num - synth_basis)
            if (prev_basis_num is not None and synth_basis is not None)
            else None
        )

        # Tâche 3 : Métriques de fraîcheur CBOE distinctes
        cboe_chain_age_min: float | None = None
        if chain.chain_internal_timestamp_utc:
            cboe_chain_age_min = max(
                0.0, (now_utc - chain.chain_internal_timestamp_utc).total_seconds() / 60.0
            )

        cboe_active_delay_min: float | None = None
        if chain.latest_quote_time_utc:
            cboe_active_delay_min = max(
                0.0, (now_utc - chain.latest_quote_time_utc).total_seconds() / 60.0
            )

        try:
            cboe_delay_max = getattr(cfg.levels, "cboe_delay_max_minutes", 20.0)
        except Exception:
            cboe_delay_max = 20.0

        # 3. Filtrage strict des échéances expirées
        # Session de référence : séance en cours ou prochaine séance de bourse
        df_options = chain.options_df
        if not df_options.empty and "expiry" in df_options.columns:
            expired_mask = df_options["expiry"] < ref_session_date
            n_expired = int(expired_mask.sum())
            if n_expired > 0:
                expired_dates = sorted(df_options.loc[expired_mask, "expiry"].unique())
                exp_str = ", ".join(d.isoformat() for d in expired_dates)
                anomalies.append(
                    f"Échéances expirées exclues (< {ref_session_date.isoformat()}) : "
                    f"{n_expired} options ({exp_str})"
                )
                df_options = df_options[~expired_mask].copy()

        # Gestion chaîne vide
        if df_options.empty:
            anomalies.append("Chaîne d'options CBOE vide (ou toutes échéances expirées)")
            return LevelsSnapshot(
                timestamp_utc=now_utc,
                source_timestamp_utc=chain.latest_quote_time_utc,
                data_age_minutes=chain.age_minutes,
                status=DataStatus.BLOCKED,
                spot_ndx=spot_ndx,
                spot_nq=spot_nq,
                basis=basis_val,
                basis_label=basis_lbl,
                basis_status=basis_st,
                synthetic_basis=synth_basis,
                net_gex=0.0,
                regime="INDISPONIBLE",
                gamma_flip_ndx=None,
                gamma_flip_nq=None,
                call_wall_ndx=None,
                call_wall_nq=None,
                put_wall_ndx=None,
                put_wall_nq=None,
                reference_session_date=ref_session_date,
                spot_nq_delay_note=spot_delay_note,
                spot_nq_time_utc=spot_nq_time_utc,
                spot_nq_age_minutes=spot_nq_age_min,
                spot_nq_is_stale=spot_nq_is_stale,
                cboe_request_time_utc=chain.fetched_at_utc,
                cboe_http_status=chain.http_status,
                cboe_duration_ms=chain.request_duration_ms,
                cboe_internal_timestamp_utc=chain.chain_internal_timestamp_utc,
                cboe_reloaded=chain.chain_reloaded,
                cboe_chain_age_minutes=cboe_chain_age_min,
                cboe_active_quote_delay_minutes=cboe_active_delay_min,
                live_basis_value=live_basis_val,
                live_basis_nq_time_utc=live_basis_nq_ts,
                live_basis_ndx_time_utc=live_basis_ndx_ts,
                live_basis_delta_t_minutes=live_basis_delta_t,
                live_basis_status=live_basis_status,
                live_basis_available=live_basis_avail,
                live_basis_unavailable_reason=live_basis_unavail_reason,
                spread_live_vs_prev_basis=spread_live_prev,
                spread_live_vs_parity_basis=spread_live_parity,
                spread_prev_vs_parity_basis=spread_prev_parity,
                anomalies=anomalies,
            )

        # 4. Calcul GEX sur les options non expirées
        df_gex = compute_gamma_exposure(df_options, spot_ndx)
        net_gex = float(df_gex["gex"].sum())

        if net_gex > 0:
            regime = "AMORTISSEUR (volatilité comprimée)"
        elif net_gex < 0:
            regime = "AMPLIFICATEUR (volatilité accrue)"
        else:
            regime = "NEUTRE"

        # 5. Zéro Gamma (Gamma Flip)
        res_profile = calculate_gamma_profile(df_gex, spot_ndx)
        flip_ndx = None
        flip_nq = None
        if res_profile is not None:
            grid, prof = res_profile
            flip_ndx = calculate_zero_gamma(grid, prof, spot_ndx)
            if flip_ndx is not None:
                flip_nq = round((flip_ndx + basis_val) * 4.0) / 4.0
            else:
                anomalies.append(
                    "Flip absent : aucun passage par zéro dans la plage +/- 8% (régime très stable)"
                )

        # 6. Murs de Gamma (Toutes échéances non expirées) — TÂCHE 3
        by_strike = df_gex.groupby("strike")["gex"].sum()

        # Murs globaux (sur tout le spectre de strikes)
        calls_above_all = by_strike[(by_strike.index >= spot_ndx) & (by_strike > 0)]
        puts_below_all = by_strike[(by_strike.index <= spot_ndx) & (by_strike < 0)]

        call_wall_global_ndx = float(calls_above_all.idxmax()) if len(calls_above_all) else None
        call_wall_global_nq = (
            round((call_wall_global_ndx + basis_val) * 4.0) / 4.0
            if call_wall_global_ndx is not None
            else None
        )
        put_wall_global_ndx = float(puts_below_all.idxmin()) if len(puts_below_all) else None
        put_wall_global_nq = (
            round((put_wall_global_ndx + basis_val) * 4.0) / 4.0
            if put_wall_global_ndx is not None
            else None
        )

        # Murs utiles restreints à la fenêtre configurée (±wall_win_pct, ex. ±10 %)
        k_upper_bound = spot_ndx * (1.0 + wall_win_pct)
        k_lower_bound = spot_ndx * (1.0 - wall_win_pct)

        calls_useful = by_strike[
            (by_strike.index >= spot_ndx) & (by_strike.index <= k_upper_bound) & (by_strike > 0)
        ]
        puts_useful = by_strike[
            (by_strike.index <= spot_ndx) & (by_strike.index >= k_lower_bound) & (by_strike < 0)
        ]

        call_wall_useful_ndx = (
            float(calls_useful.idxmax()) if len(calls_useful) else call_wall_global_ndx
        )
        call_wall_useful_nq = (
            round((call_wall_useful_ndx + basis_val) * 4.0) / 4.0
            if call_wall_useful_ndx is not None
            else None
        )
        put_wall_useful_ndx = (
            float(puts_useful.idxmin()) if len(puts_useful) else put_wall_global_ndx
        )
        put_wall_useful_nq = (
            round((put_wall_useful_ndx + basis_val) * 4.0) / 4.0
            if put_wall_useful_ndx is not None
            else None
        )

        # Distances au spot NQ (en points et en %)
        cw_useful_dist_pts = (
            (call_wall_useful_nq - spot_nq) if (call_wall_useful_nq and spot_nq) else None
        )
        cw_useful_dist_pct = (
            ((call_wall_useful_ndx - spot_ndx) / spot_ndx * 100.0)
            if (call_wall_useful_ndx and spot_ndx > 0)
            else None
        )
        pw_useful_dist_pts = (
            (put_wall_useful_nq - spot_nq) if (put_wall_useful_nq and spot_nq) else None
        )
        pw_useful_dist_pct = (
            ((put_wall_useful_ndx - spot_ndx) / spot_ndx * 100.0)
            if (put_wall_useful_ndx and spot_ndx > 0)
            else None
        )

        cw_global_dist_pts = (
            (call_wall_global_nq - spot_nq) if (call_wall_global_nq and spot_nq) else None
        )
        cw_global_dist_pct = (
            ((call_wall_global_ndx - spot_ndx) / spot_ndx * 100.0)
            if (call_wall_global_ndx and spot_ndx > 0)
            else None
        )
        pw_global_dist_pts = (
            (put_wall_global_nq - spot_nq) if (put_wall_global_nq and spot_nq) else None
        )
        pw_global_dist_pct = (
            ((put_wall_global_ndx - spot_ndx) / spot_ndx * 100.0)
            if (put_wall_global_ndx and spot_ndx > 0)
            else None
        )

        cw_is_outside = (
            call_wall_global_ndx is not None
            and call_wall_useful_ndx is not None
            and call_wall_global_ndx != call_wall_useful_ndx
        )
        pw_is_outside = (
            put_wall_global_ndx is not None
            and put_wall_useful_ndx is not None
            and put_wall_global_ndx != put_wall_useful_ndx
        )

        # Les murs standards exposés sont les murs utiles
        call_wall_ndx = call_wall_useful_ndx
        call_wall_nq = call_wall_useful_nq
        put_wall_ndx = put_wall_useful_ndx
        put_wall_nq = put_wall_useful_nq

        # Top 5 Murs en GEX absolu
        top_abs = by_strike.abs().nlargest(5)
        top_walls: list[GammaWall] = []
        for rank, (k, _) in enumerate(top_abs.items(), start=1):
            val = float(by_strike.loc[k])
            w_type = "CALL" if val > 0 else "PUT"
            top_walls.append(
                GammaWall(
                    strike=float(k),
                    gex=val,
                    type=w_type,
                    rank=rank,
                    nq_strike=round((float(k) + basis_val) * 4.0) / 4.0,
                )
            )

        # 7. Niveaux 0DTE : strictement options où expiry == ref_session_date
        df_0dte = df_gex[df_gex["expiry"] == ref_session_date]
        z_call_ndx, z_call_nq = None, None
        z_put_ndx, z_put_nq = None, None
        z_net_gex = None

        if not df_0dte.empty:
            z_net_gex = float(df_0dte["gex"].sum())
            by_k_0dte = df_0dte.groupby("strike")["gex"].sum()
            z_above = by_k_0dte[(by_k_0dte.index >= spot_ndx) & (by_k_0dte > 0)]
            z_below = by_k_0dte[(by_k_0dte.index <= spot_ndx) & (by_k_0dte < 0)]

            if len(z_above):
                z_call_ndx = float(z_above.idxmax())
                z_call_nq = round((z_call_ndx + basis_val) * 4.0) / 4.0
            if len(z_below):
                z_put_ndx = float(z_below.idxmin())
                z_put_nq = round((z_put_ndx + basis_val) * 4.0) / 4.0

            anomalies.append(
                f"0DTE : échéance {ref_session_date.isoformat()} (session de référence)"
            )
        else:
            anomalies.append(
                f"0DTE : aucune option active"
                f" pour la date de référence {ref_session_date.isoformat()}"
            )

        # 8. Expected Move — enrichir avec les champs NQ côte à côte
        em_info = calculate_expected_move(
            df_gex,
            spot_ndx,
            ref_utc=now_utc,
            cboe_quote_time_utc=chain.latest_quote_time_utc,
        )
        if em_info is not None:
            em_info.lower_bound_nq = em_info.lower_bound_ndx + basis_val
            em_info.upper_bound_nq = em_info.upper_bound_ndx + basis_val
            em_info = enrich_expected_move_nq(
                em_info,
                basis=basis_val,
                spot_nq=spot_nq,
                spot_ndx=spot_ndx,
                cboe_age_minutes=chain.age_minutes,
            )
            exp_str = em_info.expiry.isoformat() if em_info.expiry else "N/A"
            straddle_s = (
                f"{em_info.straddle_move:.1f} pts"
                if em_info.straddle_move
                else "N/A"
            )
            t_h = (
                f"{em_info.time_to_expiry_hours:.1f} h"
                if em_info.time_to_expiry_hours is not None
                else f"{em_info.days_to_expiry:.2f} j"
            )
            anomalies.append(
                f"Expected Move (échéance {exp_str}) : IV ATM {em_info.iv_atm * 100:.2f} %, "
                f"Straddle ATM {straddle_s}, T {t_h}"
            )

        # 9. Max Pain calculé strictement PAR échéance (front / référence)
        target_mp_exp = df_gex["expiry"].min()
        mp_ndx = calculate_max_pain(df_gex, target_expiry=target_mp_exp)
        mp_nq = round((mp_ndx + basis_val) * 4.0) / 4.0 if mp_ndx is not None else None
        if target_mp_exp:
            exp_mp_str = (
                target_mp_exp.isoformat()
                if isinstance(target_mp_exp, date)
                else str(target_mp_exp)
            )
            anomalies.append(
                f"Max Pain calculé pour l'échéance {exp_mp_str} : "
                f"NDX {mp_ndx:,.2f} | niveau NQ (converti) {mp_nq:,.2f}"
            )

        # 10. Statistiques d'âge de la chaîne CBOE
        if chain.age_stats:
            c_cnt = chain.age_stats.get("count", 0)
            c_min = chain.age_stats.get("min_age_minutes", 0.0)
            c_med = chain.age_stats.get("median_age_minutes", 0.0)
            c_max = chain.age_stats.get("max_age_minutes", 0.0)
            anomalies.append(
                f"Chaîne CBOE (options ±3% spot) : N={c_cnt} options | "
                f"âges: min {c_min:.1f} min, "
                f"méd {c_med:.1f} min, max {c_max:.1f} min | "
                f"Statut : {chain.status.value}"
            )

        # 11. Diagnostic 1c : séance de référence précédente (j-1)
        diag_session_date = session_close_utc.astimezone(ET).date()
        diag_1c = build_diagnostic_1c(
            nq_bars=nq_bars,
            ndx_bars=ndx_bars,
            ref_utc=now_utc,
            session_date=diag_session_date,
            tolerance_minutes=1.0,
            pair_result=pair_result,
        )

        # Champs horodatage de la base pour le snapshot
        basis_nq_ts = candidate_basis.nq_timestamp_utc if candidate_basis else None
        basis_ndx_ts = candidate_basis.ndx_timestamp_utc if candidate_basis else None
        basis_delta_t = candidate_basis.delta_t_minutes if candidate_basis else None
        basis_is_aligned = candidate_basis.is_aligned if candidate_basis else False
        basis_method_str = (
            "paire alignée séance courante"
            if (candidate_basis and candidate_basis.is_session_basis)
            else "paire séance précédente"
        )
        basis_delay_note = candidate_basis.delay_compensation_note if candidate_basis else None


        # Statut global du snapshot
        global_status = chain.status
        if basis_st == DataStatus.DEGRADED and global_status == DataStatus.OK:
            global_status = DataStatus.DEGRADED
        if spot_nq_is_stale and global_status == DataStatus.OK:
            global_status = DataStatus.DEGRADED
        if (
            in_regular_session
            and cboe_active_delay_min is not None
            and cboe_active_delay_min > cboe_delay_max
        ):
            anomalies.append(
                f"DÉGRADÉ : Retard cotations CBOE {cboe_active_delay_min:.1f} min "
                f"> seuil {cboe_delay_max:.1f} min"
            )
            global_status = DataStatus.DEGRADED

        snap = LevelsSnapshot(
            timestamp_utc=now_utc,
            source_timestamp_utc=chain.latest_quote_time_utc,
            data_age_minutes=chain.age_minutes,
            status=global_status,
            spot_ndx=spot_ndx,
            spot_nq=spot_nq,
            basis=basis_val,
            basis_label=basis_lbl,
            basis_status=basis_st,
            synthetic_basis=synth_basis,
            net_gex=net_gex,
            regime=regime,
            gamma_flip_ndx=flip_ndx,
            gamma_flip_nq=flip_nq,
            call_wall_ndx=call_wall_ndx,
            call_wall_nq=call_wall_nq,
            put_wall_ndx=put_wall_ndx,
            put_wall_nq=put_wall_nq,
            top_walls_ndx=top_walls,
            zero_dte_call_wall_ndx=z_call_ndx,
            zero_dte_call_wall_nq=z_call_nq,
            zero_dte_put_wall_ndx=z_put_ndx,
            zero_dte_put_wall_nq=z_put_nq,
            zero_dte_net_gex=z_net_gex,
            zero_dte_expiry=ref_session_date if not df_0dte.empty else None,
            expected_move=em_info,
            max_pain_ndx=mp_ndx,
            max_pain_nq=mp_nq,
            max_pain_expiry=target_mp_exp if isinstance(target_mp_exp, date) else None,
            reference_session_date=ref_session_date,
            spot_nq_delay_note=spot_delay_note,
            cboe_age_stats=chain.age_stats,
            oi_flag="OI de la veille",
            anomalies=anomalies,
            diagnostic_1c=diag_1c,
            basis_nq_time_utc=basis_nq_ts,
            basis_nq_close=(
                candidate_basis.nq_price if candidate_basis else None
            ),
            basis_ndx_time_utc=basis_ndx_ts,
            basis_ndx_spot=(
                candidate_basis.ndx_price if candidate_basis else None
            ),
            basis_delta_t_minutes=basis_delta_t,
            basis_tolerance_minutes=1.0,
            basis_is_aligned=basis_is_aligned,
            basis_method=basis_method_str,
            basis_formula="base = NQ_close - NDX_spot",
            basis_delay_compensation_note=basis_delay_note,
            # Murs utiles et globaux (Tâche 3)
            call_wall_useful_ndx=call_wall_useful_ndx,
            call_wall_useful_nq=call_wall_useful_nq,
            call_wall_useful_dist_pts=cw_useful_dist_pts,
            call_wall_useful_dist_pct=cw_useful_dist_pct,
            call_wall_global_ndx=call_wall_global_ndx,
            call_wall_global_nq=call_wall_global_nq,
            call_wall_global_dist_pts=cw_global_dist_pts,
            call_wall_global_dist_pct=cw_global_dist_pct,
            call_wall_is_outside_window=cw_is_outside,
            put_wall_useful_ndx=put_wall_useful_ndx,
            put_wall_useful_nq=put_wall_useful_nq,
            put_wall_useful_dist_pts=pw_useful_dist_pts,
            put_wall_useful_dist_pct=pw_useful_dist_pct,
            put_wall_global_ndx=put_wall_global_ndx,
            put_wall_global_nq=put_wall_global_nq,
            put_wall_global_dist_pts=pw_global_dist_pts,
            put_wall_global_dist_pct=pw_global_dist_pct,
            put_wall_is_outside_window=pw_is_outside,
            wall_window_pct=wall_win_pct,
            # Spot NQ fraîcheur réelle (Tâche 1)
            spot_nq_time_utc=spot_nq_time_utc,
            spot_nq_age_minutes=spot_nq_age_min,
            spot_nq_is_stale=spot_nq_is_stale,
            # CBOE rechargement prouvé & fraîcheur détaillée (Tâche 2 / 3)
            cboe_request_time_utc=chain.fetched_at_utc,
            cboe_http_status=chain.http_status,
            cboe_duration_ms=chain.request_duration_ms,
            cboe_internal_timestamp_utc=chain.chain_internal_timestamp_utc,
            cboe_reloaded=chain.chain_reloaded,
            cboe_chain_age_minutes=cboe_chain_age_min,
            cboe_active_quote_delay_minutes=cboe_active_delay_min,
            # Base live et comparatif (Tâche 2)
            live_basis_value=live_basis_val,
            live_basis_nq_time_utc=live_basis_nq_ts,
            live_basis_ndx_time_utc=live_basis_ndx_ts,
            live_basis_delta_t_minutes=live_basis_delta_t,
            live_basis_status=live_basis_status,
            live_basis_available=live_basis_avail,
            live_basis_unavailable_reason=live_basis_unavail_reason,
            spread_live_vs_prev_basis=spread_live_prev,
            spread_live_vs_parity_basis=spread_live_parity,
            spread_prev_vs_parity_basis=spread_prev_parity,
        )

        # Enregistrement du fichier JSON horodaté
        self._save_json(snap)

        # Enregistrement dans la base SQLite locale
        self._save_sqlite(snap)

        return snap

    def _save_json(self, snap: LevelsSnapshot) -> Path:
        dt_ny = snap.timestamp_utc.astimezone(ET)
        filename = f"levels_{dt_ny.strftime('%Y%m%d_%H%M')}.json"
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap.to_dict(), f, indent=2)
        return path

    def _save_sqlite(self, snap: LevelsSnapshot) -> None:
        try:
            conn = get_db_connection()
            apply_migrations(conn)
            insert_snapshot(
                conn=conn,
                timestamp_utc=snap.timestamp_utc,
                spot=snap.spot_ndx,
                regime=snap.regime,
                gamma_flip=snap.gamma_flip_ndx,
                call_wall=snap.call_wall_ndx,
                put_support=snap.put_wall_ndx,
                expected_move=snap.expected_move.formula_move if snap.expected_move else None,
                basis=snap.basis,
                synthetic_basis=snap.synthetic_basis,
                source="CBOE",
                status=snap.status.value,
                payload=snap.to_dict(),
            )
            conn.close()
        except Exception as e:
            log.warning("Impossible d'enregistrer le snapshot dans SQLite : %s", e)
