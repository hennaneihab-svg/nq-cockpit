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
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nqcockpit.data.cache import DiskCache
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
    """Extrait l'horodatage le plus récent parmi les trades et quotes des options.

    Recherche les champs 'last_trade_time', 'trade_time', ou 'quote_time'.
    """
    latest_dt: datetime | None = None

    for opt in raw_options:
        for field_name in ("last_trade_time", "trade_time", "quote_time"):
            val = opt.get(field_name)
            if not val or not isinstance(val, str):
                continue
            try:
                # Format CBOE fréquent : '2026-09-28T19:59:45' ou '2026-09-28 19:59:45'
                clean_val = val.replace("Z", "").strip()
                if "T" in clean_val:
                    dt = datetime.fromisoformat(clean_val)
                else:
                    dt = datetime.strptime(clean_val, "%Y-%m-%d %H:%M:%S")

                if dt.tzinfo is None:
                    # Les cotations CBOE sont généralement en heure locale ET ou UTC
                    # On les interprète en UTC
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)

                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
            except Exception:
                continue

    return latest_dt


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

    # Dérivation de l'âge à partir des horodatages de cotations d'options
    latest_quote_dt = extract_latest_quote_timestamp(raw_options)

    if latest_quote_dt is not None:
        age_min = max(0.0, (fetched_at_utc - latest_quote_dt).total_seconds() / 60.0)
        status = DataStatus.OK if age_min <= 60.0 else DataStatus.DEGRADED
        notes = f"Âge dérivé des cotations d'options : {age_min:.1f} min"
    else:
        # Horodatage introuvable dans les cotations -> âge inconnu = DÉGRADÉ
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
