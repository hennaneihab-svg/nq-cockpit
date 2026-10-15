"""Module de récupération des données de marché et macro avec cache et retry."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests
import yfinance as yf

from nqcockpit.data.cache import DiskCache
from nqcockpit.data.models import Bar, BarSeries, DataStatus, FredObservation
from nqcockpit.env import get_key, load_environment

log = logging.getLogger(__name__)

# Symboles surveillés par défaut
DEFAULT_BAR_SYMBOLS = ["NQ=F", "^NDX", "^VIX", "^VXN", "^TNX", "DX-Y.NYB"]
DEFAULT_FRED_SERIES = ["DGS2", "DGS10"]


class DataFetcher:
    """Récupérateur unifié avec cache disque, retry/backoff et gestion des statuts."""

    def __init__(self, cache: DiskCache | None = None) -> None:
        self.cache = cache or DiskCache()

    def fetch_yahoo_bars(
        self,
        symbol: str,
        interval: str = "1m",
        period: str = "1d",
        max_cache_age_seconds: float = 60.0,
        max_retries: int = 3,
    ) -> BarSeries:
        """Récupère les barres intraday Yahoo Finance avec cache et retry.

        Convertit tous les timestamps en UTC natifs.
        Mesure la latence par rapport à l'heure actuelle UTC.
        """
        cache_key = f"bars_{symbol}_{interval}_{period}"
        cached = self.cache.get(cache_key, max_age_seconds=max_cache_age_seconds)
        if cached is not None:
            bars = [
                Bar(
                    timestamp_utc=datetime.fromisoformat(b["timestamp_utc"]),
                    open=float(b["open"]),
                    high=float(b["high"]),
                    low=float(b["low"]),
                    close=float(b["close"]),
                    volume=float(b["volume"]),
                )
                for b in cached["bars"]
            ]
            return BarSeries(
                symbol=symbol,
                interval=interval,
                bars=bars,
                source="yfinance (cache)",
                fetched_at_utc=datetime.fromisoformat(cached["fetched_at_utc"]),
                status=DataStatus(cached.get("status", DataStatus.OK)),
                latency_seconds=cached.get("latency_seconds"),
                notes="Données servies depuis le cache disque",
            )

        now_utc = datetime.now(timezone.utc)
        last_error = ""

        for attempt in range(1, max_retries + 1):
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period=period, interval=interval)
                if df is None or df.empty:
                    last_error = "Aucune barre retournée par Yahoo Finance"
                    time.sleep(0.5 * attempt)
                    continue

                bars: list[Bar] = []
                for index, row in df.iterrows():
                    # Conversion de l'index timestamp en datetime UTC
                    if isinstance(index, pd.Timestamp):
                        if index.tzinfo is not None:
                            ts_utc = index.tz_convert("UTC").to_pydatetime()
                        else:
                            ts_utc = index.to_pydatetime().replace(tzinfo=timezone.utc)
                    else:
                        ts_utc = datetime.fromisoformat(str(index)).replace(tzinfo=timezone.utc)

                    bars.append(
                        Bar(
                            timestamp_utc=ts_utc,
                            open=float(row["Open"]),
                            high=float(row["High"]),
                            low=float(row["Low"]),
                            close=float(row["Close"]),
                            volume=float(row.get("Volume", 0.0)),
                        )
                    )

                # Calcul de la latence : écart entre l'heure actuelle UTC et la dernière barre
                latency_sec = None
                status = DataStatus.OK
                notes = ""
                if bars:
                    last_bar_time = bars[-1].timestamp_utc
                    latency_sec = max(0.0, (now_utc - last_bar_time).total_seconds())
                    age_min = latency_sec / 60.0

                    from nqcockpit.config import load_config
                    cfg = load_config()
                    expected_delay = cfg.data.symbols_expected_delay_minutes.get(symbol, 0)
                    margin = cfg.data.delay_margin_minutes
                    max_allowed = expected_delay + margin if expected_delay > 0 else margin

                    if expected_delay > 0 and age_min <= max_allowed:
                        status = DataStatus.OK
                        notes = f"source retardée d'environ {int(round(age_min))} min"
                    elif age_min > max_allowed:
                        status = DataStatus.DEGRADED
                        notes = (
                            f"donnée périmée (âge {int(round(age_min))} min "
                            f"> seuil {max_allowed} min)"
                        )
                    else:
                        status = DataStatus.OK
                        notes = f"donnée à jour (âge {int(round(age_min))} min)"

                series = BarSeries(
                    symbol=symbol,
                    interval=interval,
                    bars=bars,
                    source="yfinance",
                    fetched_at_utc=now_utc,
                    status=status,
                    latency_seconds=latency_sec,
                    notes=notes,
                )

                # Sauvegarder dans le cache
                self.cache.set(
                    cache_key,
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "fetched_at_utc": now_utc.isoformat(),
                        "status": status.value,
                        "latency_seconds": latency_sec,
                        "bars": [b.to_dict() for b in bars],
                    },
                )
                return series

            except Exception as e:
                last_error = str(e)
                log.warning("Tentative %d/%d pour %s a échoué: %s", attempt, max_retries, symbol, e)
                time.sleep(1.0 * attempt)

        # En cas d'échec total des retries
        return BarSeries(
            symbol=symbol,
            interval=interval,
            bars=[],
            source="yfinance",
            fetched_at_utc=now_utc,
            status=DataStatus.BLOCKED,
            notes=f"Échec après {max_retries} tentatives : {last_error}",
        )

    def fetch_fred_series(
        self,
        series_id: str,
        max_cache_age_seconds: float = 3600.0,
    ) -> FredObservation:
        """Récupère une série FRED (DGS2, DGS10).

        Conserve la date d'observation sans calcul d'âge en minutes (audit P01/P02).
        """
        cache_key = f"fred_{series_id}"
        cached = self.cache.get(cache_key, max_age_seconds=max_cache_age_seconds)
        if cached is not None:
            return FredObservation(
                series_id=series_id,
                observation_date=cached["observation_date"],
                value=float(cached["value"]),
                source="FRED (cache)",
                fetched_at_utc=datetime.fromisoformat(cached["fetched_at_utc"]),
                status=DataStatus(cached.get("status", DataStatus.OK)),
                notes="Données servies depuis le cache disque",
            )

        now_utc = datetime.now(timezone.utc)
        load_environment()
        api_key = get_key("FRED_API_KEY")

        if not api_key:
            # Repli transparent sur l'endpoint CSV public gratuit de FRED (sans clé requise)
            try:
                from nqcockpit.macro.fetcher import fetch_fred_history

                hist = fetch_fred_history(
                    series_id, cache=self.cache, max_cache_age_seconds=max_cache_age_seconds
                )
                if hist:
                    last_date, last_val = hist[-1]
                    res = FredObservation(
                        series_id=series_id,
                        observation_date=last_date,
                        value=float(last_val),
                        source="FRED (CSV public)",
                        fetched_at_utc=now_utc,
                        status=DataStatus.OK,
                        notes="Récupéré via endpoint CSV public gratuit sans clé",
                    )
                    self.cache.set(
                        cache_key,
                        {
                            "series_id": series_id,
                            "observation_date": last_date,
                            "value": float(last_val),
                            "fetched_at_utc": now_utc.isoformat(),
                            "status": DataStatus.OK.value,
                        },
                    )
                    return res
            except Exception as exc:
                log.warning("Échec repli FRED CSV public pour %s: %s", series_id, exc)

            return FredObservation(
                series_id=series_id,
                observation_date="",
                value=0.0,
                source="FRED",
                fetched_at_utc=now_utc,
                status=DataStatus.DEGRADED,
                notes="Clé FRED_API_KEY absente et repli CSV indisponible",
            )

        base_url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 5,
        }

        try:
            url = f"{base_url}?{urlencode(params)}"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            obs_list = data.get("observations", [])

            valid_obs: dict[str, Any] | None = None
            for obs in obs_list:
                val_str = obs.get("value", "")
                if val_str not in (".", "", "ND"):
                    valid_obs = obs
                    break

            if not valid_obs:
                return FredObservation(
                    series_id=series_id,
                    observation_date="",
                    value=0.0,
                    source="FRED",
                    fetched_at_utc=now_utc,
                    status=DataStatus.DEGRADED,
                    notes="Aucune valeur numérique valide trouvée dans FRED",
                )

            obs_date = valid_obs["date"]
            obs_val = float(valid_obs["value"])

            res = FredObservation(
                series_id=series_id,
                observation_date=obs_date,
                value=obs_val,
                source="FRED",
                fetched_at_utc=now_utc,
                status=DataStatus.OK,
                notes=f"Observation arrêtée au {obs_date}",
            )

            # Mettre en cache
            self.cache.set(
                cache_key,
                {
                    "series_id": series_id,
                    "observation_date": obs_date,
                    "value": obs_val,
                    "fetched_at_utc": now_utc.isoformat(),
                    "status": DataStatus.OK.value,
                },
            )
            return res

        except Exception as e:
            log.warning(
                "Erreur lors de la récupération FRED API %s: %s — tentative repli CSV public",
                series_id,
                e,
            )
            try:
                from nqcockpit.macro.fetcher import fetch_fred_history

                hist = fetch_fred_history(
                    series_id, cache=self.cache, max_cache_age_seconds=max_cache_age_seconds
                )
                if hist:
                    last_date, last_val = hist[-1]
                    res = FredObservation(
                        series_id=series_id,
                        observation_date=last_date,
                        value=float(last_val),
                        source="FRED (CSV public)",
                        fetched_at_utc=now_utc,
                        status=DataStatus.OK,
                        notes="Récupéré via endpoint CSV public gratuit après échec API",
                    )
                    self.cache.set(
                        cache_key,
                        {
                            "series_id": series_id,
                            "observation_date": last_date,
                            "value": float(last_val),
                            "fetched_at_utc": now_utc.isoformat(),
                            "status": DataStatus.OK.value,
                        },
                    )
                    return res
            except Exception as exc2:
                log.warning("Échec repli FRED CSV public secondaire pour %s: %s", series_id, exc2)

            return FredObservation(
                series_id=series_id,
                observation_date="",
                value=0.0,
                source="FRED",
                fetched_at_utc=now_utc,
                status=DataStatus.BLOCKED,
                notes=f"Erreur réseau/API : {e}",
            )
