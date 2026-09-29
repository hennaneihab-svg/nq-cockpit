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
from datetime import date, datetime, timezone
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
from nqcockpit.data.models import Bar, DataStatus
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


def calculate_expected_move(
    df: pd.DataFrame,
    spot: float,
    ref_utc: datetime | None = None,
    today_date: date | None = None,
) -> ExpectedMoveInfo | None:
    """Calcule le move attendu 1 sigma (formule analytique ET straddle ATM du front).

    Formule analytique : S * IV_ATM * sqrt(jours / 252) où 'jours' représente
    les jours de bourse effectifs restants (CALENDAR), avec fraction pour 0DTE.
    """
    if df.empty:
        return None

    if ref_utc is None:
        ref_utc = datetime.now(timezone.utc)
    elif ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    nearest_exp = df["expiry"].min()
    sub = df[df["expiry"] == nearest_exp]
    if sub.empty:
        return None

    if isinstance(nearest_exp, date):
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
    )


def calculate_max_pain(df: pd.DataFrame) -> float | None:
    """Calcule le strike Max Pain (minimisant la valeur intrinsèque des options à l'expiration)."""
    if df.empty:
        return None

    valid = df[df["open_interest"] > 0]
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

        # 1. Validation de la base NQ/NDX
        if nq_bars and ndx_bars:
            latest_nq = nq_bars[-1]
            latest_ndx = ndx_bars[-1]
            in_regular_session = CALENDAR.is_us_equity_regular_hours(now_utc)
            if in_regular_session:
                basis_snap = compute_live_basis(latest_nq, latest_ndx, now_utc=now_utc)
                if basis_snap.status == DataStatus.BLOCKED:
                    basis_snap = compute_previous_session_basis(nq_bars, ndx_bars, ref_utc=now_utc)
                    anomalies.append(
                        "Barres direct désalignées (> 60s) : repli sur clôture précédente"
                    )
            else:
                basis_snap = compute_previous_session_basis(nq_bars, ndx_bars, ref_utc=now_utc)
                if basis_snap.status == DataStatus.DEGRADED:
                    anomalies.append(
                        "Base de clôture précédente dégradée (> 1 séance de bourse ou désalignée)"
                    )
        else:
            basis_snap = None
            anomalies.append("Aucune barre NQ/NDX disponible pour la base")

        basis_val = basis_snap.basis if basis_snap else 0.0
        basis_lbl = basis_snap.label if basis_snap else "base indisponible"
        basis_st = basis_snap.status if basis_snap else DataStatus.BLOCKED
        spot_nq = spot_ndx + basis_val if spot_ndx > 0 else 0.0

        # Vérification base anormale (> 2% du spot)
        if spot_ndx > 0 and abs(basis_val) > 0.02 * spot_ndx:
            anomalies.append(f"Base NQ/NDX anormale : {basis_val:+.1f} pts (> 2% du spot)")

        # 2. Gestion chaîne vide
        if chain.options_df.empty:
            anomalies.append("Chaîne d'options CBOE vide")
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
                synthetic_basis=None,
                net_gex=0.0,
                regime="INDISPONIBLE",
                gamma_flip_ndx=None,
                gamma_flip_nq=None,
                call_wall_ndx=None,
                call_wall_nq=None,
                put_wall_ndx=None,
                put_wall_nq=None,
                anomalies=anomalies,
            )

        # 3. Calcul GEX
        df_gex = compute_gamma_exposure(chain.options_df, spot_ndx)
        net_gex = float(df_gex["gex"].sum())

        # Régime (volatilité, aucun biais directionnel)
        if net_gex > 0:
            regime = "AMORTISSEUR (volatilité comprimée)"
        elif net_gex < 0:
            regime = "AMPLIFICATEUR (volatilité accrue)"
        else:
            regime = "NEUTRE"

        # 4. Zéro Gamma (Gamma Flip)
        res_profile = calculate_gamma_profile(df_gex, spot_ndx)
        flip_ndx = None
        flip_nq = None
        if res_profile is not None:
            grid, prof = res_profile
            flip_ndx = calculate_zero_gamma(grid, prof, spot_ndx)
            if flip_ndx is not None:
                flip_nq = flip_ndx + basis_val
            else:
                anomalies.append(
                    "Flip absent : aucun passage par zéro dans la plage +/- 8% (régime très stable)"
                )

        # 5. Murs de Gamma (Toutes échéances)
        # Agrégation par strike
        by_strike = df_gex.groupby("strike")["gex"].sum()
        calls_above = by_strike[(by_strike.index >= spot_ndx) & (by_strike > 0)]
        puts_below = by_strike[(by_strike.index <= spot_ndx) & (by_strike < 0)]

        call_wall_ndx = float(calls_above.idxmax()) if len(calls_above) else None
        call_wall_nq = (call_wall_ndx + basis_val) if call_wall_ndx is not None else None

        put_wall_ndx = float(puts_below.idxmin()) if len(puts_below) else None
        put_wall_nq = (put_wall_ndx + basis_val) if put_wall_ndx is not None else None

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
                    nq_strike=float(k) + basis_val,
                )
            )

        # 6. Niveaux 0DTE séparés
        nearest_exp = df_gex["expiry"].min()
        df_0dte = df_gex[df_gex["expiry"] == nearest_exp]
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
                z_call_nq = z_call_ndx + basis_val
            if len(z_below):
                z_put_ndx = float(z_below.idxmin())
                z_put_nq = z_put_ndx + basis_val

        # 7. Expected Move
        em_info = calculate_expected_move(df_gex, spot_ndx, ref_utc=now_utc)
        if em_info is not None:
            em_info.lower_bound_nq = em_info.lower_bound_ndx + basis_val
            em_info.upper_bound_nq = em_info.upper_bound_ndx + basis_val

        # 8. Max Pain
        mp_ndx = calculate_max_pain(df_gex)
        mp_nq = (mp_ndx + basis_val) if mp_ndx is not None else None

        # 9. Base synthétique par parité Call-Put et seuil de tolérance
        synth_basis = synthetic_futures_basis_from_options(
            chain.options_df,
            spot_ndx,
            today_date=now_utc.astimezone(ET).date(),
        )
        if synth_basis is not None:
            try:
                cfg = load_config()
                tol = getattr(cfg.data, "parity_basis_tolerance_points", 50.0)
            except Exception:
                tol = 50.0
            parity_diff = abs(basis_val - synth_basis)
            if parity_diff > tol:
                basis_st = DataStatus.DEGRADED
                anomalies.append(
                    f"Écart base future-spot vs parité Call-Put ({parity_diff:.1f} pts) "
                    f"> tolérance ({tol:.1f} pts)"
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
            expected_move=em_info,
            max_pain_ndx=mp_ndx,
            max_pain_nq=mp_nq,
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
