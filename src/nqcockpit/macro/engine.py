"""Moteur de calcul du contexte macroéconomique et cross-asset (P07).

Calcule :
- Niveaux, percentiles 1 an (252 séances) et variations 5 jours pour US10Y, US2Y, DXY, VIX, VXN.
- Range et gap overnight NQ depuis les barres CME.
- Intégration du rapport COT CFTC.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig
from nqcockpit.data.models import Bar
from nqcockpit.macro.fetcher import (
    fetch_cftc_cot,
    fetch_fred_history,
    fetch_yahoo_history,
)
from nqcockpit.macro.models import (
    MacroMetric,
    MacroSnapshot,
    OvernightStats,
)

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc


def compute_series_stats(
    name: str,
    symbol: str,
    history: list[tuple[str, float]],
    lookback_days: int = 252,
    delta_days: int = 5,
    source_label: str = "",
) -> MacroMetric:
    """Calcule le niveau actuel, le percentile 1 an et la variation 5 jours d'une série.

    Args:
        name: Nom d'affichage ('US 10Y'...)
        symbol: Symbole ('DGS10'...)
        history: Liste de (date_str, valeur) triée par date
        lookback_days: Période pour le percentile (252 séances de bourse)
        delta_days: Période pour la variation (5 séances)
        source_label: Source d'origine

    Returns:
        MacroMetric complète
    """
    if not history:
        return MacroMetric(
            name=name,
            symbol=symbol,
            current_value=None,
            observation_date="",
            percentile_1y=None,
            delta_5d=None,
            delta_5d_pct=None,
            source=source_label,
            status="DÉGRADÉ: historique vide",
            provenance="aucune observation reçue",
        )

    last_date, current_val = history[-1]

    # Fenêtre 252 jours pour le percentile
    window = [v for _, v in history[-lookback_days:]]
    if window:
        count_below = sum(1 for v in window if v <= current_val)
        percentile = round((count_below / len(window)) * 100.0, 1)
    else:
        percentile = None

    # Variation 5 jours
    delta_5d: float | None = None
    delta_5d_pct: float | None = None
    if len(history) > delta_days:
        prior_val = history[-(delta_days + 1)][1]
        delta_5d = round(current_val - prior_val, 4)
        if prior_val != 0:
            delta_5d_pct = round((delta_5d / prior_val) * 100.0, 2)

    return MacroMetric(
        name=name,
        symbol=symbol,
        current_value=round(current_val, 4),
        observation_date=last_date,
        percentile_1y=percentile,
        delta_5d=delta_5d,
        delta_5d_pct=delta_5d_pct,
        source=source_label,
        status="OK",
        provenance=f"lookback {min(len(window), lookback_days)}j, delta {delta_days}j",
    )


def compute_overnight_stats(
    bars_nq: list[Bar],
    now_utc: datetime | None = None,
) -> OvernightStats:
    """Calcule le range et le gap de la nuit du contrat NQ depuis les barres disponibles.

    Session overnight CME : de 18:00 ET (veille) à 09:30 ET (jour J).
    Prior Close : cours de clôture de la séance US précédente (16:00 ET).
    """
    if not bars_nq:
        return OvernightStats(
            status="DÉGRADÉ",
            status_detail="Aucune barre NQ disponible",
        )

    if now_utc is None:
        now_utc = datetime.now(UTC)

    now_et = now_utc.astimezone(ET_TZ)
    target_date_str = now_et.strftime("%Y-%m-%d")

    # Trier les barres par timestamp croissant
    sorted_bars = sorted(bars_nq, key=lambda b: b.timestamp_utc)

    # Identifier la clôture de la veille (dernière barre <= 16:00 ET veille)
    prior_close: float | None = None
    overnight_bars: list[Bar] = []

    for b in sorted_bars:
        b_et = b.timestamp_utc.astimezone(ET_TZ)
        b_date_str = b_et.strftime("%Y-%m-%d")

        # Barres de la veille : capturer la clôture autour de 16:00 ET
        if b_date_str < target_date_str and b_et.hour < 17:
            prior_close = b.close

        # Barres de la session overnight :
        # - soit veille >= 18:00 ET
        # - soit jour J < 09:30 ET
        is_before_open = b_et.hour < 9 or (b_et.hour == 9 and b_et.minute < 30)
        is_overnight = (b_date_str < target_date_str and b_et.hour >= 18) or (
            b_date_str == target_date_str and is_before_open
        )
        if is_overnight:
            overnight_bars.append(b)

    # Si aucune barre spécifiquement identifiée dans la fenêtre exacte,
    # utiliser les barres les plus récentes comme approximation avec statut explicite
    if not overnight_bars:
        recent_bars = sorted_bars[-60:]  # dernières barres
        high = max(b.high for b in recent_bars)
        low = min(b.low for b in recent_bars)
        first = recent_bars[0].open
        last = recent_bars[-1].close
        range_pts = round(high - low, 2)
        gap_pts = round(last - prior_close, 2) if prior_close is not None else None

        return OvernightStats(
            session_date=target_date_str,
            high_price=round(high, 2),
            low_price=round(low, 2),
            open_price=round(first, 2),
            last_price=round(last, 2),
            prior_close_price=round(prior_close, 2) if prior_close is not None else None,
            range_pts=range_pts,
            gap_pts=gap_pts,
            status="DÉGRADÉ: barres récentes partielles",
            status_detail="Fenêtre overnight complète non trouvée, estimation sur dernières barres",
            source="NQ=F (barres partielles)",
        )

    high = max(b.high for b in overnight_bars)
    low = min(b.low for b in overnight_bars)
    first = overnight_bars[0].open
    last = overnight_bars[-1].close
    range_pts = round(high - low, 2)
    gap_pts = round(last - prior_close, 2) if prior_close is not None else None

    return OvernightStats(
        session_date=target_date_str,
        high_price=round(high, 2),
        low_price=round(low, 2),
        open_price=round(first, 2),
        last_price=round(last, 2),
        prior_close_price=round(prior_close, 2) if prior_close is not None else None,
        range_pts=range_pts,
        gap_pts=gap_pts,
        status="OK",
        status_detail="",
        source="NQ=F CME (18:00 - 09:30 ET)",
    )


def compute_macro_snapshot(
    config: AppConfig,
    bars_nq: list[Bar] | None = None,
    now_utc: datetime | None = None,
) -> MacroSnapshot:
    """Calcule le snapshot macro complet (taux, DXY, volatilité, overnight, COT).

    Tous les paramètres proviennent de config.yaml.
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    lookback_days = config.macro.percentile_lookback_days
    delta_days = config.macro.delta_lookback_days
    sources = config.macro.sources

    us10y_id = sources.get("us10y_fred", "DGS10")
    us2y_id = sources.get("us2y_fred", "DGS2")
    dxy_sym = sources.get("dxy_symbol", "DX-Y.NYB")
    vix_sym = sources.get("vix_symbol", "^VIX")
    vxn_sym = sources.get("vxn_symbol", "^VXN")
    cot_contract = sources.get("cot_contract_name", "NASDAQ-100")

    metrics: dict[str, MacroMetric] = {}

    # 1. US 10Y (FRED)
    hist_10y = fetch_fred_history(us10y_id, lookback_days=lookback_days + 150)
    metrics["us10y"] = compute_series_stats(
        name="US 10Y",
        symbol=us10y_id,
        history=hist_10y,
        lookback_days=lookback_days,
        delta_days=delta_days,
        source_label=f"FRED ({us10y_id})",
    )

    # 2. US 2Y (FRED)
    hist_2y = fetch_fred_history(us2y_id, lookback_days=lookback_days + 150)
    metrics["us2y"] = compute_series_stats(
        name="US 2Y",
        symbol=us2y_id,
        history=hist_2y,
        lookback_days=lookback_days,
        delta_days=delta_days,
        source_label=f"FRED ({us2y_id})",
    )

    # 3. DXY (Yahoo ou FRED fallback)
    hist_dxy = fetch_yahoo_history(dxy_sym, period="1y")
    if not hist_dxy:
        fallback_id = sources.get("dxy_fallback_fred", "DTWEXBGS")
        hist_dxy = fetch_fred_history(fallback_id, lookback_days=lookback_days + 150)
        source_dxy = f"FRED fallback ({fallback_id})"
    else:
        source_dxy = f"Yahoo ({dxy_sym})"

    metrics["dxy"] = compute_series_stats(
        name="DXY",
        symbol=dxy_sym,
        history=hist_dxy,
        lookback_days=lookback_days,
        delta_days=delta_days,
        source_label=source_dxy,
    )

    # 4. VIX (Yahoo)
    hist_vix = fetch_yahoo_history(vix_sym, period="1y")
    metrics["vix"] = compute_series_stats(
        name="VIX",
        symbol=vix_sym,
        history=hist_vix,
        lookback_days=lookback_days,
        delta_days=delta_days,
        source_label=f"Yahoo ({vix_sym})",
    )

    # 5. VXN (Yahoo)
    hist_vxn = fetch_yahoo_history(vxn_sym, period="1y")
    metrics["vxn"] = compute_series_stats(
        name="VXN",
        symbol=vxn_sym,
        history=hist_vxn,
        lookback_days=lookback_days,
        delta_days=delta_days,
        source_label=f"Yahoo ({vxn_sym})",
    )

    # 6. Overnight NQ
    effective_bars = bars_nq or []
    if not effective_bars:
        try:
            from nqcockpit.data.fetcher import DataFetcher

            f_live = DataFetcher()
            res_live = f_live.fetch_yahoo_bars("NQ=F", interval="1m", period="1d")
            if res_live.bars:
                effective_bars = res_live.bars
        except Exception as exc:
            log.warning("Échec récupération live NQ pour overnight stats: %s", exc)

    overnight = compute_overnight_stats(effective_bars, now_utc=now_utc)

    # 7. CFTC COT
    cot = fetch_cftc_cot(contract_keyword=cot_contract)

    # Statut global
    degraded = [m.name for m in metrics.values() if "DÉGRADÉ" in m.status]
    if "DÉGRADÉ" in overnight.status:
        degraded.append("Overnight NQ")
    if "DÉGRADÉ" in cot.status:
        degraded.append("COT CFTC")

    overall_status = "OK"
    overall_detail = ""
    if degraded:
        overall_status = "DÉGRADÉ"
        overall_detail = f"Sources dégradées : {', '.join(degraded)}"

    return MacroSnapshot(
        as_of_utc=now_utc,
        metrics=metrics,
        overnight=overnight,
        cot=cot,
        status=overall_status,
        status_detail=overall_detail,
    )
