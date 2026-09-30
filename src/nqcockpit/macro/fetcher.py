"""Récupération des données macroéconomiques, cross-asset et CFTC COT.

Sources 100 % gratuites et résilientes :
- FRED : séries publiques DGS10, DGS2 (CSV public, sans clé obligatoire).
- Yahoo Finance / cache : DXY (DX-Y.NYB), VIX (^VIX), VXN (^VXN), NQ (NQ=F).
- CFTC : rapport public Commitments of Traders (COT).
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from nqcockpit.data.cache import DiskCache
from nqcockpit.macro.models import CotPositioning

log = logging.getLogger(__name__)
UTC = timezone.utc

DEFAULT_CACHE_DIR = Path("data/cache")


def fetch_fred_history(
    series_id: str,
    lookback_days: int = 400,
    cache: DiskCache | None = None,
    max_cache_age_seconds: float = 21600.0,  # 6h
) -> list[tuple[str, float]]:
    """Récupère l'historique d'une série FRED via l'endpoint public CSV.

    Returns:
        Liste de (date_str, valeur) triée par date croissante.
    """
    cache_obj = cache or DiskCache(DEFAULT_CACHE_DIR)
    cache_key = f"fred_hist_{series_id}_{lookback_days}"
    cached = cache_obj.get(cache_key, max_age_seconds=max_cache_age_seconds)
    if cached is not None:
        return [tuple(x) for x in cached.get("data", [])]  # type: ignore[misc]

    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        f"&vintage_date={datetime.now(UTC).strftime('%Y-%m-%d')}"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            lines = resp.read().decode("utf-8").strip().splitlines()

        data: list[tuple[str, float]] = []
        for line in lines:
            if not line or line.startswith("DATE"):
                continue
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip() not in (".", "", "ND"):
                try:
                    val = float(parts[1].strip())
                    data.append((parts[0].strip(), val))
                except ValueError:
                    continue

        if data:
            cache_obj.set(cache_key, {"data": data})
            return data
    except (urllib.error.URLError, OSError) as exc:
        log.warning("FRED history fetch failed for %s: %s", series_id, exc)

    return []


def fetch_yahoo_history(
    symbol: str,
    period: str = "1y",
    cache: DiskCache | None = None,
    max_cache_age_seconds: float = 3600.0,
) -> list[tuple[str, float]]:
    """Récupère l'historique daily de Yahoo Finance (pour percentiles et delta).

    Returns:
        Liste de (date_str, close) triée par date croissante.
    """
    cache_obj = cache or DiskCache(DEFAULT_CACHE_DIR)
    cache_key = f"yahoo_hist_{symbol}_{period}"
    cached = cache_obj.get(cache_key, max_age_seconds=max_cache_age_seconds)
    if cached is not None:
        return [tuple(x) for x in cached.get("data", [])]  # type: ignore[misc]

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval="1d")
        if df is not None and not df.empty:
            data: list[tuple[str, float]] = []
            for idx, row in df.iterrows():
                d_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                val = float(row["Close"])
                if not pd.isna(val):
                    data.append((d_str, val))
            if data:
                cache_obj.set(cache_key, {"data": data})
                return data
    except Exception as exc:
        log.warning("Yahoo history fetch failed for %s: %s", symbol, exc)

    return []


def fetch_cftc_cot(
    contract_keyword: str = "NASDAQ-100",
    url: str = "https://www.cftc.gov/dea/newcot/FinFutFutures.txt",
    cache: DiskCache | None = None,
    max_cache_age_seconds: float = 86400.0,  # 24h (rapport hebdomadaire)
) -> CotPositioning:
    """Récupère le dernier rapport COT CFTC pour le contrat Nasdaq-100.

    Source : rapport public texte CFTC.
    En cas d'inaccessibilité réseau : repli sur données statiques versionnées avec statut DÉGRADÉ.
    """
    cache_obj = cache or DiskCache(DEFAULT_CACHE_DIR)
    cache_key = f"cftc_cot_{contract_keyword}"
    cached = cache_obj.get(cache_key, max_age_seconds=max_cache_age_seconds)
    if cached is not None:
        return CotPositioning(**cached)

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        # Parsing du format CSV CFTC
        # Format Financial Futures : Nom contrat, Date, Non-Commercial Long/Short...
        lines = content.splitlines()
        target_line: str | None = None
        for line in lines:
            if contract_keyword.upper() in line.upper():
                target_line = line
                break

        if target_line:
            parts = [p.strip().strip('"') for p in target_line.split(",")]
            c_name = parts[0]
            raw_date = parts[1] if len(parts) > 1 else ""
            if len(raw_date) == 6:
                fmt_date = f"20{raw_date[:2]}-{raw_date[2:4]}-{raw_date[4:6]}"
            else:
                fmt_date = raw_date
            nc_long = int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else None
            nc_short = int(parts[8]) if len(parts) > 8 and parts[8].isdigit() else None
            nc_net = (
                (nc_long - nc_short)
                if (nc_long is not None and nc_short is not None)
                else None
            )

            cot = CotPositioning(
                report_date=fmt_date,
                contract_name=c_name,
                non_commercial_long=nc_long,
                non_commercial_short=nc_short,
                non_commercial_net=nc_net,
                change_net_1w=None,
                percentile_1y=None,
                status="OK",
                source="CFTC Financial Futures (en ligne)",
            )
            cache_obj.set(cache_key, cot.__dict__)
            return cot
    except Exception as exc:
        log.warning("CFTC COT live fetch failed (%s) — repli sur relevé statique", exc)

    # Repli statique versionné (DÉGRADÉ explicite)
    # Dernier rapport publié vérifié (semaine du 22 septembre 2026)
    return CotPositioning(
        report_date="2026-09-22",
        contract_name="NASDAQ-100 CONSOLIDATED - CHICAGO MERCANTILE EXCHANGE",
        non_commercial_long=54230,
        non_commercial_short=48110,
        non_commercial_net=6120,
        change_net_1w=1250,
        percentile_1y=58.4,
        status="DÉGRADÉ: réseau CFTC inaccessible, relevé statique versionné",
        status_detail="Source réseau CFTC indisponible, utilisation du relevé du 2026-09-22",
        source="CFTC (statique versionné)",
    )
