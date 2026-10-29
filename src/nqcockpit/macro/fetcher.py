"""Récupération des données macroéconomiques, cross-asset et CFTC COT.

Sources 100 % gratuites et résilientes :
- FRED : séries publiques DGS10, DGS2 (CSV public, sans clé obligatoire).
- Yahoo Finance / cache : DXY (DX-Y.NYB), VIX (^VIX), VXN (^VXN), NQ (NQ=F).
- CFTC : rapport public Commitments of Traders (COT).
"""

from __future__ import annotations

import logging
import re
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

# Rapport courant officiel CFTC (Traders in Financial Futures, futures only).
# L'ancien endpoint /dea/newcot/FinFutFutures.txt répond désormais HTTP 404.
CFTC_COT_URL = "https://www.cftc.gov/dea/futures/financial_lf.htm"
_CFTC_DATE_RE = re.compile(r"Positions as of\s+([A-Z][a-z]+ \d{1,2}, \d{4})")
_CFTC_NUMBER_RE = re.compile(r"-?\d[\d,]*")


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
        with urllib.request.urlopen(req, timeout=5) as resp:
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


def parse_cftc_report(
    content: str, contract_keyword: str
) -> tuple[str, str, int, int] | None:
    """Parse le rapport HTML CFTC courant (format « Traders in Financial Futures »).

    Returns:
        (report_date, contract_name, nc_long, nc_short) ou None si non parsable.
        Les positions « non-commercial » historiques correspondent à la catégorie
        « Leveraged Funds » du rapport désagrégé.
    """
    lines = content.splitlines()
    keyword = contract_keyword.upper()
    target_idx: int | None = None
    for i, line in enumerate(lines):
        upper = line.upper()
        if keyword in upper and "CONSOLIDATED" in upper:
            target_idx = i
            break
    if target_idx is None:
        for i, line in enumerate(lines):
            if keyword in line.upper():
                target_idx = i
                break
    if target_idx is None:
        return None

    report_date = ""
    for i in range(target_idx, -1, -1):
        match = _CFTC_DATE_RE.search(lines[i])
        if match:
            try:
                report_date = datetime.strptime(
                    match.group(1), "%B %d, %Y"
                ).strftime("%Y-%m-%d")
            except ValueError:
                report_date = ""
            break

    positions_idx: int | None = None
    for i in range(target_idx, min(target_idx + 12, len(lines))):
        if lines[i].strip() == "Positions":
            positions_idx = i
            break
    if positions_idx is None:
        return None

    numbers: list[int] = []
    for line in lines[positions_idx + 1: positions_idx + 4]:
        if line.strip():
            try:
                numbers = [int(t.replace(",", "")) for t in _CFTC_NUMBER_RE.findall(line)]
            except ValueError:
                numbers = []
            break
    if len(numbers) < 8:
        return None

    contract_name = lines[target_idx].split("   (")[0].strip()
    return report_date, contract_name, numbers[6], numbers[7]


def _unavailable_cot(cache_obj: DiskCache, cache_key: str) -> CotPositioning:
    """Retourne un COT DÉGRADÉ explicite : dernier relevé daté en cache, sinon indisponible."""
    stale = cache_obj.get(cache_key)
    if isinstance(stale, dict) and stale.get("report_date"):
        try:
            cot = CotPositioning(**stale)
            cot.status = "DÉGRADÉ: COT indisponible"
            cot.status_detail = (
                f"CFTC inaccessible — dernier relevé connu du {cot.report_date}"
            )
            cot.source = "CFTC (dernier relevé en cache)"
            return cot
        except (TypeError, ValueError):
            pass
    return CotPositioning(
        report_date="",
        status="DÉGRADÉ: COT indisponible",
        status_detail="CFTC inaccessible — aucun relevé disponible",
        source="CFTC (indisponible)",
    )


def fetch_cftc_cot(
    contract_keyword: str = "NASDAQ-100",
    url: str = CFTC_COT_URL,
    cache: DiskCache | None = None,
    max_cache_age_seconds: float = 86400.0,  # 24h (rapport hebdomadaire)
) -> CotPositioning:
    """Récupère le dernier rapport COT CFTC pour le contrat Nasdaq-100.

    Source : rapport public officiel CFTC (HTML, futures only).
    En cas d'inaccessibilité réseau : statut DÉGRADÉ explicite, jamais d'exception.
    """
    cache_obj = cache or DiskCache(DEFAULT_CACHE_DIR)
    cache_key = f"cftc_cot_{contract_keyword}"
    cached = cache_obj.get(cache_key, max_age_seconds=max_cache_age_seconds)
    if cached is not None:
        try:
            return CotPositioning(**cached)
        except (TypeError, ValueError):
            log.warning("Entrée de cache COT invalide, rechargement réseau")

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        parsed = parse_cftc_report(content, contract_keyword)
        if parsed is not None:
            fmt_date, c_name, nc_long, nc_short = parsed
            cot = CotPositioning(
                report_date=fmt_date,
                contract_name=c_name,
                non_commercial_long=nc_long,
                non_commercial_short=nc_short,
                non_commercial_net=nc_long - nc_short,
                change_net_1w=None,
                percentile_1y=None,
                status="OK",
                source="CFTC Traders in Financial Futures (en ligne)",
            )
            cache_obj.set(cache_key, cot.__dict__)
            return cot
        log.warning("Rapport COT CFTC reçu mais contrat %r introuvable", contract_keyword)
    except Exception as exc:
        log.warning("CFTC COT live fetch failed (%s)", exc)

    return _unavailable_cot(cache_obj, cache_key)
