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
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from nqcockpit.config import load_config
from nqcockpit.data.basis import (
    compute_live_basis,
    compute_previous_session_basis,
    synthetic_futures_basis_from_options,
)
from nqcockpit.data.calendar import CALENDAR
from nqcockpit.data.cboe import CboeChainSnapshot
from nqcockpit.data.db import apply_migrations, get_db_connection, insert_snapshot
from nqcockpit.data.models import Bar, BasisSnapshot, DataStatus
from nqcockpit.levels import greeks
from nqcockpit.levels.models import ExpectedMoveInfo, GammaWall, LevelsSnapshot

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
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


def calculate_expected_move(
    df: pd.DataFrame,
    spot: float,
    ref_utc: datetime | None = None,
    today_date: date | None = None,
) -> ExpectedMoveInfo | None:
    """Calcule le move attendu 1 sigma (formule analytique ET straddle ATM du front).

    Formule analytique : S * IV_ATM * sqrt(jours / 252) avec jours en jours de bourse.
    La fraction de jour du 0DTE ne s'applique que pendant la séance.
    Hors séance, la durée est le temps de bourse entre maintenant et l'échéance (ex: 1.0 j).
    """
    if df.empty:
        return None

    if ref_utc is None:
        if today_date is not None:
            ref_utc = datetime.combine(today_date, time(12, 0), tzinfo=ET).astimezone(timezone.utc)
        else:
            ref_utc = datetime.now(timezone.utc)
    elif ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    ref_session = get_reference_session_date(ref_utc)
    nearest_exp = df["expiry"].min()
    sub = df[df["expiry"] == nearest_exp]
    if sub.empty:
        return None

    in_regular = CALENDAR.is_us_equity_regular_hours(ref_utc)
    if isinstance(nearest_exp, date):
        if nearest_exp == ref_session:
            if in_regular:
                days = CALENDAR.calculate_trading_days_to_expiry(ref_utc, nearest_exp)
            else:
                days = 1.0
        else:
            days = CALENDAR.calculate_trading_days_to_expiry(ref_utc, nearest_exp)
    else:
        days = 1.0

    # IV ATM : strike le plus proche du spot
    sub_valid_iv = sub[sub["iv"] > 1e-4]
    if sub_valid_iv.empty:
        return None

    atm_idx = (sub_valid_iv["strike"] - spot).abs().idxmin()
    iv_atm = float(sub_valid_iv.loc[atm_idx, "iv"])

    # Formule analytique : S * IV * sqrt(jours / 252)
    formula_move = float(spot * iv_atm * np.sqrt(days / 252.0))

    # Prix du straddle ATM du front (C_atm + P_atm)
    straddle_move = None
    atm_strike = sub_valid_iv.loc[atm_idx, "strike"]
    call_atm = sub[(sub["strike"] == atm_strike) & (sub["type"] == "C")]
    put_atm = sub[(sub["strike"] == atm_strike) & (sub["type"] == "P")]

    if not call_atm.empty and not put_atm.empty:
        c_bid = float(call_atm.iloc[0]["bid"])
        c_ask = float(call_atm.iloc[0]["ask"])
        p_bid = float(put_atm.iloc[0]["bid"])
        p_ask = float(put_atm.iloc[0]["ask"])

        c_last = float(call_atm.iloc[0]["last_trade_price"])
        p_last = float(put_atm.iloc[0]["last_trade_price"])
        c_mid = (c_bid + c_ask) / 2.0 if (c_bid + c_ask) > 0 else c_last
        p_mid = (p_bid + p_ask) / 2.0 if (p_bid + p_ask) > 0 else p_last

        if c_mid > 0 and p_mid > 0:
            straddle_move = float(c_mid + p_mid)

    return ExpectedMoveInfo(
        formula_move=formula_move,
        straddle_move=straddle_move,
        iv_atm=iv_atm,
        days_to_expiry=float(days),
        lower_bound_ndx=spot - formula_move,
        upper_bound_ndx=spot + formula_move,
        lower_bound_nq=0.0,  # sera rempli avec la base
        upper_bound_nq=0.0,
        expiry=nearest_exp if isinstance(nearest_exp, date) else None,
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
        except Exception:
            tol = 50.0

        # 2. Ordre de priorité de la base NQ/NDX :
        #    (i)  Base alignée en séance (barres 1m NQ=F et ^NDX, écart <= 60s, séance en cours)
        #    (ii) Base de la séance précédente (dernière séance complète <= 16:00 ET, même minute)
        #    (iii) Base implicite par parité call-put
        #          (fallback si écart > tolérance ou barres manquantes)
        in_regular_session = CALENDAR.is_us_equity_regular_hours(now_utc)
        candidate_basis: BasisSnapshot | None = None

        if in_regular_session and nq_bars and ndx_bars:
            live_snap = compute_live_basis(nq_bars[-1], ndx_bars[-1], now_utc=now_utc)
            if live_snap.status != DataStatus.BLOCKED:
                candidate_basis = live_snap

        if candidate_basis is None:
            prev_snap = compute_previous_session_basis(nq_bars, ndx_bars, ref_utc=now_utc)
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

        # Spot NQ = dernier cours observé de NQ=F avec son horodatage et son retard
        # Ne présente JAMAIS un NQ dérivé comme un cours.
        # Prix NQ valide : multiple de 0,25.
        if nq_bars:
            latest_obs_nq = nq_bars[-1]
            spot_nq = round(latest_obs_nq.close * 4.0) / 4.0
            nq_ts_ny = latest_obs_nq.timestamp_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S EDT")
            nq_ts_utc = latest_obs_nq.timestamp_utc.strftime("%H:%M:%SZ")
            spot_delay_note = "source retardée d'environ 15 min"
            anomalies.append(
                f"Spot NQ observé : {spot_nq:,.2f} pts"
                f" (cours NQ=F à {nq_ts_ny} [{nq_ts_utc}], {spot_delay_note})"
            )
        else:
            spot_nq = round((spot_ndx + basis_val) * 4.0) / 4.0 if spot_ndx > 0 else 0.0
            spot_delay_note = "cours estimé via NDX + base"

        anomalies.append(
            "Niveaux NQ : tous les niveaux NQ (Flip, Walls, Expected Move, Max Pain) "
            "sont des « niveaux NQ (convertis) » via base"
        )

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

        # 6. Murs de Gamma (Toutes échéances non expirées)
        by_strike = df_gex.groupby("strike")["gex"].sum()
        calls_above = by_strike[(by_strike.index >= spot_ndx) & (by_strike > 0)]
        puts_below = by_strike[(by_strike.index <= spot_ndx) & (by_strike < 0)]

        call_wall_ndx = float(calls_above.idxmax()) if len(calls_above) else None
        call_wall_nq = (
            round((call_wall_ndx + basis_val) * 4.0) / 4.0 if call_wall_ndx is not None else None
        )

        put_wall_ndx = float(puts_below.idxmin()) if len(puts_below) else None
        put_wall_nq = (
            round((put_wall_ndx + basis_val) * 4.0) / 4.0 if put_wall_ndx is not None else None
        )

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

        # 8. Expected Move sur l'échéance la plus proche non expirée
        em_info = calculate_expected_move(df_gex, spot_ndx, ref_utc=now_utc)
        if em_info is not None:
            em_info.lower_bound_nq = em_info.lower_bound_ndx + basis_val
            em_info.upper_bound_nq = em_info.upper_bound_ndx + basis_val
            exp_str = em_info.expiry.isoformat() if em_info.expiry else "N/A"
            straddle_s = f"{em_info.straddle_move:.1f} pts" if em_info.straddle_move else "N/A"
            anomalies.append(
                f"Expected Move (échéance {exp_str}) : IV ATM {em_info.iv_atm * 100:.2f} %, "
                f"Straddle ATM {straddle_s}, durée {em_info.days_to_expiry:.2f} j"
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

        # Statut global du snapshot
        global_status = chain.status
        if basis_st == DataStatus.DEGRADED and global_status == DataStatus.OK:
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
