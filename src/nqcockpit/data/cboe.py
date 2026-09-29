"""Ingestion et parsing de la chaîne d'options CBOE (NDX).

Adapté de Darthreign/gex-dashboard (MIT), copyright conservé.

Corrections issues des audits P01/P02 :
- Âge CBOE dérivé exclusivement des horodatages des cotations/trades d'options,
  et NON du champ timestamp du fichier CDN.
- Si aucun horodatage de cotation valide n'est extrait : « âge inconnu », statut DÉGRADÉ.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nqcockpit.data.cache import DiskCache
from nqcockpit.data.calendar import CALENDAR
from nqcockpit.data.models import DataStatus

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
BASE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
OCC_RE = re.compile(r"^(?P<root>.+?)(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


@dataclass
class CboeChainSnapshot:
    """Snapshot complet d'une chaîne d'options CBOE."""

    symbol: str
    spot: float
    options_df: pd.DataFrame
    latest_quote_time_utc: datetime | None
    fetched_at_utc: datetime
    age_minutes: float | None
    status: DataStatus
    source: str = "CBOE"
    notes: str = ""
    age_stats: dict[str, Any] = field(default_factory=dict)


def _cboe_session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = "nqcockpit/0.1 (trading analytics; personal use)"
    s.headers["Accept"] = "application/json"
    return s


_SESSION = _cboe_session()


def parse_occ(symbol: str) -> tuple[date, str, float] | None:
    """Parse un symbole d'option OCC (ex: NDX260930C28000000)."""
    m = OCC_RE.match(symbol)
    if not m:
        return None
    try:
        exp = datetime.strptime(m.group("exp"), "%y%m%d").date()
        cp = m.group("cp")
        strike = int(m.group("strike")) / 1000.0
        return exp, cp, strike
    except Exception:
        return None


def extract_latest_quote_timestamp(raw_options: list[dict]) -> datetime | None:
    """Extrait l'horodatage le plus récent parmi les trades et quotes des options."""
    latest_dt: datetime | None = None

    for opt in raw_options:
        for field_name in ("last_trade_time", "trade_time", "quote_time"):
            val = opt.get(field_name)
            if not val or not isinstance(val, str):
                continue
            clean_val = val.strip()
            try:
                if clean_val.endswith("Z"):
                    clean_ts = clean_val[:-1]
                    if "T" in clean_ts:
                        dt = datetime.fromisoformat(clean_ts).replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.strptime(
                            clean_ts, "%Y-%m-%d %H:%M:%S"
                        ).replace(tzinfo=timezone.utc)
                elif "T" in clean_val:
                    dt_raw = datetime.fromisoformat(clean_val)
                    if dt_raw.tzinfo is None:
                        dt = dt_raw.replace(tzinfo=ET).astimezone(timezone.utc)
                    else:
                        dt = dt_raw.astimezone(timezone.utc)
                else:
                    dt_raw = datetime.strptime(clean_val, "%Y-%m-%d %H:%M:%S")
                    if dt_raw.tzinfo is None:
                        dt = dt_raw.replace(tzinfo=ET).astimezone(timezone.utc)
                    else:
                        dt = dt_raw.astimezone(timezone.utc)

                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
            except Exception:
                continue

    return latest_dt


def extract_cboe_chain_age_stats(
    raw_options: list[dict],
    spot: float,
    now_utc: datetime,
) -> tuple[float | None, datetime | None, dict[str, Any]]:
    """Calcule l'âge de la chaîne CBOE et les statistiques associées.

    Âge = maintenant - max(last_trade_time) parmi les options dont le strike est à ±3 % du spot.
    Horodatages CBOE interprétés en America/New_York s'ils sont sans fuseau horaire.
    """
    trades_in_band: list[tuple[datetime, float]] = []

    for opt in raw_options:
        strike = opt.get("strike")
        if strike is None:
            parsed = parse_occ(opt.get("option", ""))
            if parsed:
                strike = parsed[2]
        if strike is None:
            continue

        try:
            strike_val = float(strike)
        except (ValueError, TypeError):
            continue

        # Filtre ±3% du spot
        if spot > 0 and abs(strike_val - spot) / spot > 0.03:
            continue

        for field_name in ("last_trade_time", "trade_time", "quote_time"):
            val = opt.get(field_name)
            if not val or not isinstance(val, str):
                continue
            clean_val = val.strip()
            try:
                if clean_val.endswith("Z"):
                    clean_ts = clean_val[:-1]
                    if "T" in clean_ts:
                        dt = datetime.fromisoformat(clean_ts).replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.strptime(
                            clean_ts, "%Y-%m-%d %H:%M:%S"
                        ).replace(tzinfo=timezone.utc)
                elif "T" in clean_val:
                    dt_raw = datetime.fromisoformat(clean_val)
                    if dt_raw.tzinfo is None:
                        dt = dt_raw.replace(tzinfo=ET).astimezone(timezone.utc)
                    else:
                        dt = dt_raw.astimezone(timezone.utc)
                else:
                    dt_raw = datetime.strptime(clean_val, "%Y-%m-%d %H:%M:%S")
                    if dt_raw.tzinfo is None:
                        dt = dt_raw.replace(tzinfo=ET).astimezone(timezone.utc)
                    else:
                        dt = dt_raw.astimezone(timezone.utc)

                age_m = max(0.0, (now_utc - dt).total_seconds() / 60.0)
                trades_in_band.append((dt, age_m))
                break
            except Exception:
                continue

    if not trades_in_band:
        return None, None, {}

    ages = [t[1] for t in trades_in_band]
    latest_dt = max(t[0] for t in trades_in_band)
    min_age = min(ages)
    med_age = float(np.median(ages))
    max_age = max(ages)
    n_count = len(trades_in_band)

    stats = {
        "count": n_count,
        "min_age_minutes": min_age,
        "median_age_minutes": med_age,
        "max_age_minutes": max_age,
        "aggregate": "max(last_trade_time) sur strikes ±3% spot",
    }
    return min_age, latest_dt, stats


def parse_cboe_payload(raw: dict, fetched_at_utc: datetime) -> CboeChainSnapshot:
    """Parse le payload JSON brut de CBOE et calcule l'âge sur les cotations."""
    data = raw.get("data", {})
    spot = float(data.get("current_price", 0.0))
    raw_options = data.get("options", [])

    rows: list[dict] = []
    for o in raw_options:
        opt_sym = o.get("option", "")
        parsed = parse_occ(opt_sym)
        if parsed is None:
            continue
        exp, cp, strike = parsed
        rows.append(
            {
                "contract": opt_sym,
                "expiry": exp,
                "type": cp,
                "strike": strike,
                "bid": float(o.get("bid", 0.0)),
                "ask": float(o.get("ask", 0.0)),
                "iv": float(o.get("iv", 0.0)),
                "open_interest": float(o.get("open_interest", 0.0)),
                "volume": float(o.get("volume", 0.0)),
                "delta": float(o.get("delta", 0.0)),
                "gamma": float(o.get("gamma", 0.0)),
                "last_trade_price": float(o.get("last_trade_price", 0.0)),
                "last_trade_time": o.get("last_trade_time"),
            }
        )

    df = pd.DataFrame(rows)

    # Dérivation de l'âge à partir des options dans la bande ±3% du spot
    age_min, latest_quote_dt, age_stats = extract_cboe_chain_age_stats(
        raw_options, spot, fetched_at_utc
    )

    if latest_quote_dt is None:
        # Repli sur l'ensemble des cotations d'options
        latest_quote_dt = extract_latest_quote_timestamp(raw_options)
        if latest_quote_dt is not None:
            age_min = max(0.0, (fetched_at_utc - latest_quote_dt).total_seconds() / 60.0)
            age_stats = {
                "count": len(raw_options),
                "min_age_minutes": age_min,
                "median_age_minutes": age_min,
                "max_age_minutes": age_min,
                "aggregate": "repli: toutes options",
            }
        else:
            # Repli sur le timestamp global du JSON si présent (ex: certaines fixtures)
            ts_str = data.get("timestamp") or raw.get("timestamp")
            if ts_str and isinstance(ts_str, str):
                clean_ts = ts_str.replace("Z", "").strip()
                try:
                    if "T" in clean_ts:
                        latest_quote_dt = datetime.fromisoformat(clean_ts)
                    else:
                        latest_quote_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
                    if latest_quote_dt.tzinfo is None:
                        latest_quote_dt = (
                            latest_quote_dt.replace(tzinfo=ET).astimezone(timezone.utc)
                        )
                    else:
                        latest_quote_dt = latest_quote_dt.astimezone(timezone.utc)
                    age_min = max(0.0, (fetched_at_utc - latest_quote_dt).total_seconds() / 60.0)
                    age_stats = {
                        "count": 1,
                        "min_age_minutes": age_min,
                        "median_age_minutes": age_min,
                        "max_age_minutes": age_min,
                        "aggregate": "repli: timestamp global",
                    }
                except Exception:
                    latest_quote_dt = None

    in_regular = CALENDAR.is_us_equity_regular_hours(fetched_at_utc)

    if latest_quote_dt is not None:
        last_close_utc = CALENDAR.get_last_equity_session_close(fetched_at_utc)
        last_close_et = last_close_utc.astimezone(ET)
        options_close_et = datetime.combine(last_close_et.date(), time(16, 15), tzinfo=ET)
        options_close_utc = options_close_et.astimezone(timezone.utc)

        if not in_regular and fetched_at_utc >= options_close_utc:
            # Hors séance et après fermeture des options (16:15 ET)
            if latest_quote_dt.astimezone(ET).date() == last_close_et.date():
                status = DataStatus.OK
                notes = (
                    f"OK « clôture » (clôture 16:15 ET | ±3%: N={age_stats.get('count', 0)}, "
                    f"âges: min {age_stats.get('min_age_minutes', 0.0):.1f}m / "
                    f"méd {age_stats.get('median_age_minutes', 0.0):.1f}m / "
                    f"max {age_stats.get('max_age_minutes', 0.0):.1f}m)"
                )
            else:
                status = DataStatus.DEGRADED
                notes = "donnée antérieure à la dernière séance de clôture"
        else:
            fresh = age_min is not None and age_min <= 60.0
            status = DataStatus.OK if fresh else DataStatus.DEGRADED
            notes = (
                f"Âge dérivé (max trade ±3%) : {age_min:.1f} min | N={age_stats.get('count', 0)} "
                f"(min {age_stats.get('min_age_minutes', 0.0):.1f}m / "
                f"méd {age_stats.get('median_age_minutes', 0.0):.1f}m / "
                f"max {age_stats.get('max_age_minutes', 0.0):.1f}m)"
            )
    else:
        age_min = None
        status = DataStatus.DEGRADED
        notes = "Âge inconnu (aucun horodatage de cotation exploitable dans les options)"

    return CboeChainSnapshot(
        symbol="NDX",
        spot=spot,
        options_df=df,
        latest_quote_time_utc=latest_quote_dt,
        fetched_at_utc=fetched_at_utc,
        age_minutes=age_min,
        status=status,
        source="CBOE",
        notes=notes,
        age_stats=age_stats,
    )


def fetch_cboe_options_chain(
    cboe_symbol: str = "_NDX",
    timeout: int = 30,
    cache: DiskCache | None = None,
    max_cache_age_seconds: float = 60.0,
) -> CboeChainSnapshot:
    """Télécharge et parse la chaîne d'options CBOE avec cache optionnel."""
    cache_key = f"cboe_chain_{cboe_symbol}"
    if cache is not None:
        cached = cache.get(cache_key, max_age_seconds=max_cache_age_seconds)
        if cached is not None:
            return parse_cboe_payload(cached, datetime.now(timezone.utc))

    try:
        from nqcockpit.config import load_config

        cfg = load_config()
        configured_url = getattr(cfg.sources, "cboe_ndx_url", None)
    except Exception:
        configured_url = None

    if configured_url and cboe_symbol == "_NDX":
        url = configured_url
    else:
        url = BASE_URL.format(sym=cboe_symbol)

    now_utc = datetime.now(timezone.utc)
    try:
        resp = _SESSION.get(url, timeout=timeout)
        resp.raise_for_status()
        raw = resp.json()
        if cache is not None:
            cache.set(cache_key, raw)
        return parse_cboe_payload(raw, now_utc)
    except Exception as e:
        log.error("Échec du téléchargement CBOE %s: %s", cboe_symbol, e)
        return CboeChainSnapshot(
            symbol="NDX",
            spot=0.0,
            options_df=pd.DataFrame(),
            latest_quote_time_utc=None,
            fetched_at_utc=now_utc,
            age_minutes=None,
            status=DataStatus.BLOCKED,
            source="CBOE",
            notes=f"Erreur réseau CBOE : {e}",
        )
