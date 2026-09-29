"""Health check engine and fallback management for external data sources.

Complies with:
- Zero paid APIs requirement
- Timestamps in America/New_York only (console table and source_check.json)
- Data age tracking in minutes computed in UTC, session-aware in America/New_York
- Strict separation between closed market ("clôture") and stale data ("donnée périmée")
- Rejection of daily midnight (00:00:00) bars to avoid artificial 1200+ min staleness
- Missing timestamp handling ("Âge INCONNU" -> DÉGRADÉ)
- No 2Y yield approximation (DGS2 = INDISPONIBLE without FRED key, DGS10 = ^TNX substitut yfinance)
- User-Agent contact email configured via BLS_CONTACT_EMAIL or sources.bls_contact_email
- No secret logging or display
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import requests

from nqcockpit.config import load_config
from nqcockpit.env import get_key, load_environment
from nqcockpit.time import TZ_NEW_YORK

logger = logging.getLogger("nqcockpit.sources.health")

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
DEFAULT_STALE_THRESHOLD_MINUTES = 60

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 NQCockpit/1.0"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class SourceCheckResult:
    """Individual source health check result."""

    name: str
    category: str
    status: str  # "OK", "DÉGRADÉ", "BLOQUÉ"
    latency_ms: float
    measured_at_ny: str
    data_timestamp: str | None = None
    data_age_minutes: float | None = None
    http_status: int | None = None
    endpoint: str | None = None
    message: str = ""
    fallback_plan: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceHealthReport:
    """Consolidated source health report."""

    generated_at_ny: str
    generated_at_utc: str
    summary: dict[str, int]
    results: list[SourceCheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_ny": self.generated_at_ny,
            "generated_at_utc": self.generated_at_utc,
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
        }

    def save_json(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return p

    def render_console_table(self) -> str:
        """Renders an aligned ASCII table suitable for console output in America/New_York."""
        lines = []
        border = (
            "+--------------------+---------+---------+"
            "-------------------+--------------------+--------------------------------+"
        )
        header = (
            "| Source             | Statut  | Latence |"
            " Mesure (NY)        | Donnée & Âge (min) | Plan B / Message               |"
        )
        lines.append(border)
        lines.append(header)
        lines.append(border)

        for r in self.results:
            name = (r.name[:18] + "..") if len(r.name) > 18 else r.name.ljust(18)
            status = r.status.ljust(7)
            latency = f"{r.latency_ms:.0f} ms".rjust(7)

            # Measurement time concise in NY
            ny_p = r.measured_at_ny.split(" ")
            ny_short = f"{ny_p[1][:5]} {ny_p[2]}" if len(ny_p) > 2 else r.measured_at_ny[:8]
            measure_str = ny_short.center(17)

            # Data timestamp & age
            if r.data_age_minutes is not None:
                ts_part = r.data_timestamp[:10] if r.data_timestamp else ""
                data_col = f"{r.data_age_minutes:.0f}m ({ts_part})"
            elif r.data_timestamp:
                data_col = r.data_timestamp[:17]
            else:
                data_col = "N/A"
            if len(data_col) > 18:
                data_col = data_col[:15] + "..."
            data_col = data_col.ljust(18)

            # Message / Plan B
            info = r.message if r.message else (r.fallback_plan[:28] if r.fallback_plan else "OK")
            if len(info) > 30:
                info = info[:27] + "..."
            info = info.ljust(30)

            lines.append(f"| {name} | {status} | {latency} | {measure_str} | {data_col} | {info} |")

        lines.append(border)
        lines.append(
            f"Résumé : {self.summary.get('OK', 0)} OK, "
            f"{self.summary.get('DÉGRADÉ', 0)} DÉGRADÉ, "
            f"{self.summary.get('BLOQUÉ', 0)} BLOQUÉ"
        )
        return "\n".join(lines)


# --- Market Session Calendar ---


def is_us_equity_market_open(dt_ny: datetime | None = None) -> tuple[bool, str]:
    """Determines if the US regular stock exchange session is currently open."""
    if dt_ny is None:
        dt_ny = datetime.now(TZ_NEW_YORK)
    elif dt_ny.tzinfo is None:
        dt_ny = dt_ny.replace(tzinfo=TZ_NEW_YORK)
    else:
        dt_ny = dt_ny.astimezone(TZ_NEW_YORK)

    weekday = dt_ny.weekday()
    if weekday in (5, 6):
        return False, "Week-end (marché actions fermé)"

    cur_time = dt_ny.time()
    if cur_time < dt_time(9, 30):
        return False, "Pré-marché (avant 09:30 ET)"
    if cur_time >= dt_time(16, 0):
        return False, "Post-marché (après 16:00 ET)"

    return True, "Session régulière ouverte"


def is_cme_futures_market_open(dt_ny: datetime | None = None) -> tuple[bool, str]:
    """Determines if CME futures market (NQ=F) is open."""
    if dt_ny is None:
        dt_ny = datetime.now(TZ_NEW_YORK)
    elif dt_ny.tzinfo is None:
        dt_ny = dt_ny.replace(tzinfo=TZ_NEW_YORK)
    else:
        dt_ny = dt_ny.astimezone(TZ_NEW_YORK)

    weekday = dt_ny.weekday()
    cur_time = dt_ny.time()

    if weekday == 4 and cur_time >= dt_time(17, 0):
        return False, "Week-end (clôture vendredi 17:00 ET)"
    if weekday == 5:
        return False, "Week-end (marché futures fermé)"
    if weekday == 6 and cur_time < dt_time(18, 0):
        return False, "Week-end (réouverture dimanche 18:00 ET)"
    if dt_time(17, 0) <= cur_time < dt_time(18, 0):
        return False, "Pause quotidienne CME (17:00-18:00 ET)"

    return True, "Session futures ouverte"


def get_last_us_equity_close(dt_ny: datetime) -> datetime:
    """Returns expected close (16:00 ET) for the latest US equity trading session."""
    if dt_ny.tzinfo is None:
        dt_ny = dt_ny.replace(tzinfo=TZ_NEW_YORK)
    else:
        dt_ny = dt_ny.astimezone(TZ_NEW_YORK)

    weekday = dt_ny.weekday()
    cur_time = dt_ny.time()

    if weekday in (0, 1, 2, 3, 4) and cur_time >= dt_time(16, 0):
        return datetime(dt_ny.year, dt_ny.month, dt_ny.day, 16, 0, tzinfo=TZ_NEW_YORK)

    if weekday == 0:  # Monday before 16:00 -> Friday close
        target_date = dt_ny.date() - timedelta(days=3)
    elif weekday == 5:  # Saturday -> Friday close
        target_date = dt_ny.date() - timedelta(days=1)
    elif weekday == 6:  # Sunday -> Friday close
        target_date = dt_ny.date() - timedelta(days=2)
    else:  # Tue-Fri before 16:00 -> yesterday close
        target_date = dt_ny.date() - timedelta(days=1)

    return datetime(target_date.year, target_date.month, target_date.day, 16, 0, tzinfo=TZ_NEW_YORK)


def get_last_cme_futures_close(dt_ny: datetime) -> datetime:
    """Returns the expected close datetime (17:00 ET) for CME futures."""
    if dt_ny.tzinfo is None:
        dt_ny = dt_ny.replace(tzinfo=TZ_NEW_YORK)
    else:
        dt_ny = dt_ny.astimezone(TZ_NEW_YORK)

    weekday = dt_ny.weekday()
    cur_time = dt_ny.time()

    if weekday in (0, 1, 2, 3, 4) and cur_time >= dt_time(17, 0):
        return datetime(dt_ny.year, dt_ny.month, dt_ny.day, 17, 0, tzinfo=TZ_NEW_YORK)

    if weekday == 5:  # Saturday -> Friday 17:00
        fri = dt_ny.date() - timedelta(days=1)
        return datetime(fri.year, fri.month, fri.day, 17, 0, tzinfo=TZ_NEW_YORK)
    if weekday == 6:  # Sunday -> Friday 17:00
        fri = dt_ny.date() - timedelta(days=2)
        return datetime(fri.year, fri.month, fri.day, 17, 0, tzinfo=TZ_NEW_YORK)

    if weekday == 0:  # Monday before 17:00 -> Friday 17:00
        fri = dt_ny.date() - timedelta(days=3)
        return datetime(fri.year, fri.month, fri.day, 17, 0, tzinfo=TZ_NEW_YORK)

    prev = dt_ny.date() - timedelta(days=1)
    return datetime(prev.year, prev.month, prev.day, 17, 0, tzinfo=TZ_NEW_YORK)


def evaluate_symbol_session(
    symbol_or_name: str,
    quote_dt: datetime | None,
    now_ny: datetime | None = None,
    session_group: str | None = None,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    is_midnight: bool = False,
) -> tuple[str, str, float | None, str | None]:
    """Evaluates quote freshness according to session rules in America/New_York.

    Returns: (status, message, data_age_minutes, data_timestamp_ny_str)
    """
    if is_midnight:
        return (
            "DÉGRADÉ",
            "Horodatage minuit (00:00:00) rejeté — cotation intraday indisponible",
            None,
            None,
        )

    if quote_dt is None:
        return "DÉGRADÉ", "Âge INCONNU", None, None

    if now_ny is None:
        now_ny = datetime.now(TZ_NEW_YORK)
    elif now_ny.tzinfo is None:
        now_ny = now_ny.replace(tzinfo=TZ_NEW_YORK)
    else:
        now_ny = now_ny.astimezone(TZ_NEW_YORK)

    if quote_dt.tzinfo is None:
        quote_dt = quote_dt.replace(tzinfo=timezone.utc)

    quote_in_ny = quote_dt.astimezone(TZ_NEW_YORK)
    if quote_in_ny.hour == 0 and quote_in_ny.minute == 0 and quote_in_ny.second == 0:
        return (
            "DÉGRADÉ",
            "Horodatage minuit (00:00:00) rejeté — cotation intraday indisponible",
            None,
            None,
        )

    now_utc = now_ny.astimezone(timezone.utc)
    quote_utc = quote_dt.astimezone(timezone.utc)
    age_seconds = max(0.0, (now_utc - quote_utc).total_seconds())
    age_minutes = round(age_seconds / 60.0, 1)

    quote_ny_str = quote_in_ny.strftime("%Y-%m-%d %H:%M:%S %Z")

    if session_group is None:
        clean = symbol_or_name.strip()
        if clean in ("NQ=F", "cme_futures", "CME Futures", "yfinance NQ=F"):
            session_group = "cme_futures"
        elif clean in (
            "^NDX",
            "^VIX",
            "^VXN",
            "CBOE NDX Options",
            "us_equities",
            "US Equities",
            "yfinance ^NDX",
            "yfinance ^VIX",
            "yfinance ^VXN",
        ):
            session_group = "us_equities"

    if session_group is None:
        # Undefined session -> display age without judging
        return "OK", f"âge non jugé ({age_minutes:.0f} min)", age_minutes, quote_ny_str

    if session_group == "us_equities":
        is_open, _ = is_us_equity_market_open(now_ny)
        if is_open:
            if age_minutes <= stale_threshold_minutes:
                return "OK", f"Donnée fraîche ({age_minutes:.0f} min)", age_minutes, quote_ny_str
            return (
                "DÉGRADÉ",
                f"donnée périmée ({age_minutes:.0f} min > seuil {stale_threshold_minutes} min)",
                age_minutes,
                quote_ny_str,
            )
        else:
            expected_close = get_last_us_equity_close(now_ny)
            if quote_in_ny >= expected_close - timedelta(minutes=5):
                return "OK", f"clôture ({age_minutes:.0f} min)", age_minutes, quote_ny_str
            exp_str = expected_close.strftime("%Y-%m-%d 16:00 ET")
            return (
                "DÉGRADÉ",
                f"donnée périmée (antérieure à la dernière clôture du {exp_str})",
                age_minutes,
                quote_ny_str,
            )

    if session_group == "cme_futures":
        is_open, _ = is_cme_futures_market_open(now_ny)
        if is_open:
            if age_minutes <= stale_threshold_minutes:
                return "OK", f"Donnée fraîche ({age_minutes:.0f} min)", age_minutes, quote_ny_str
            return (
                "DÉGRADÉ",
                f"donnée périmée ({age_minutes:.0f} min > seuil {stale_threshold_minutes} min)",
                age_minutes,
                quote_ny_str,
            )
        else:
            expected_close = get_last_cme_futures_close(now_ny)
            if quote_in_ny >= expected_close - timedelta(minutes=5):
                return "OK", f"clôture ({age_minutes:.0f} min)", age_minutes, quote_ny_str
            exp_str = expected_close.strftime("%Y-%m-%d %H:%M ET")
            return (
                "DÉGRADÉ",
                f"donnée périmée (antérieure à la dernière clôture du {exp_str})",
                age_minutes,
                quote_ny_str,
            )


    return "OK", f"âge non jugé ({age_minutes:.0f} min)", age_minutes, quote_ny_str


def evaluate_data_staleness(
    data_age_minutes: float | None,
    market_is_open: bool,
    market_state_desc: str,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> tuple[str, str]:
    """Legacy helper evaluating data freshness."""
    if data_age_minutes is None:
        return "OK", ""
    if data_age_minutes <= stale_threshold_minutes:
        return "OK", f"Donnée fraîche ({data_age_minutes:.0f} min)"
    if not market_is_open:
        return "OK", f"Marché fermé ({market_state_desc}) - dernière cotation conservée"
    return (
        "DÉGRADÉ",
        f"Donnée périmée ({data_age_minutes:.0f} min > seuil {stale_threshold_minutes} min)",
    )


def get_bls_contact_email(config_email: str | None = None) -> str:
    """Resolves contact email from BLS_CONTACT_EMAIL env var or config sources.bls_contact_email."""
    env_val = get_key("BLS_CONTACT_EMAIL")
    if env_val and env_val.strip():
        return env_val.strip()
    if config_email and config_email.strip():
        return config_email.strip()
    try:
        cfg = load_config()
        cfg_email = getattr(cfg.sources, "bls_contact_email", None)
        if cfg_email and cfg_email.strip():
            return cfg_email.strip()
    except Exception:
        pass
    return "contact@nqcockpit.local"


def get_now_ny_timestamp() -> str:
    """Returns formatted current timestamp in America/New_York."""
    return datetime.now(TZ_NEW_YORK).strftime("%Y-%m-%d %H:%M:%S %Z")


def request_with_retry(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> tuple[requests.Response | None, float, Exception | None]:
    """Executes an HTTP request with exponential backoff retry and measures latency."""
    req_headers = dict(DEFAULT_HEADERS)
    if headers:
        req_headers.update(headers)

    requester = session or requests
    last_error: Exception | None = None
    total_start = time.perf_counter()

    for attempt in range(1, max_retries + 1):
        try:
            call_start = time.perf_counter()
            resp = requester.request(
                method=method,
                url=url,
                headers=req_headers,
                timeout=timeout,
                **kwargs,
            )
            call_latency = (time.perf_counter() - call_start) * 1000.0
            if resp.status_code >= 500 and attempt < max_retries:
                time.sleep(backoff_factor * (2 ** (attempt - 1)))
                continue
            return resp, call_latency, None
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(backoff_factor * (2 ** (attempt - 1)))

    total_latency = (time.perf_counter() - total_start) * 1000.0
    return None, total_latency, last_error


# --- Specific Checkers ---


def check_cboe_ndx(
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    ref_time_utc: datetime | None = None,
) -> SourceCheckResult:
    """Checks CBOE delayed quotes options NDX JSON endpoint."""
    try:
        cfg = load_config()
        url = getattr(
            cfg.sources,
            "cboe_ndx_url",
            "https://cdn.cboe.com/api/global/delayed_quotes/options/_NDX.json",
        )
    except Exception:
        url = "https://cdn.cboe.com/api/global/delayed_quotes/options/_NDX.json"

    name = "CBOE NDX Options"
    category = "Options"
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "En cas de blocage ou indisponibilité CBOE : saisie manuelle des niveaux gamma clés "
        "dans l'UI, ou scraping différé alternatif Yahoo Finance options NDX."
    )

    resp, latency, err = request_with_retry(url, timeout=timeout, max_retries=max_retries)
    if err is not None:
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            endpoint=url,
            message=f"Échec réseau: {err}",
            fallback_plan=fallback,
        )

    if resp is None or resp.status_code != 200:
        status_code = resp.status_code if resp is not None else None
        status = "BLOQUÉ" if status_code in (403, 404, 410) else "DÉGRADÉ"
        return SourceCheckResult(
            name=name,
            category=category,
            status=status,
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=status_code,
            endpoint=url,
            message=f"Réponse HTTP inattendue : {status_code}",
            fallback_plan=fallback,
        )

    try:
        from nqcockpit.data.cboe import parse_cboe_payload

        data = resp.json()
        now_utc = ref_time_utc if ref_time_utc is not None else datetime.now(timezone.utc)
        chain_snap = parse_cboe_payload(data, fetched_at_utc=now_utc)
        dt_data = chain_snap.latest_quote_time_utc
        current_price = chain_snap.spot
        options_count = len(chain_snap.options_df)

        if dt_data is None:
            return SourceCheckResult(
                name=name,
                category=category,
                status="DÉGRADÉ",
                latency_ms=latency,
                measured_at_ny=ts_ny,
                http_status=200,
                endpoint=url,
                message="Âge INCONNU (aucun horodatage de cotation dans les options CBOE)",
                fallback_plan=fallback,
            )

        status, session_msg, data_age_min, data_ts_ny = evaluate_symbol_session(
            symbol_or_name=name,
            quote_dt=dt_data,
            session_group="us_equities",
            stale_threshold_minutes=stale_threshold_minutes,
            now_ny=now_utc.astimezone(TZ_NEW_YORK),
        )

        msg = f"Spot NDX={current_price}, {options_count} options | {session_msg}"

        return SourceCheckResult(
            name=name,
            category=category,
            status=status,
            latency_ms=latency,
            measured_at_ny=ts_ny,
            data_timestamp=data_ts_ny,
            data_age_minutes=data_age_min,
            http_status=200,
            endpoint=url,
            message=msg,
            fallback_plan=fallback,
        )
    except Exception as exc:
        return SourceCheckResult(
            name=name,
            category=category,
            status="DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=200,
            endpoint=url,
            message=f"Erreur de décodage JSON CBOE: {exc}",
            fallback_plan=fallback,
        )


def check_yfinance_symbols(
    symbols: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> list[SourceCheckResult]:
    """Checks yfinance for key symbols (NQ=F, ^NDX, ^VIX, ^VXN, ^TNX, DX-Y.NYB)."""
    if symbols is None:
        symbols = ["NQ=F", "^NDX", "^VIX", "^VXN", "^TNX", "DX-Y.NYB"]

    import yfinance as yf

    results = []
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "En cas d'échec yfinance : utilisation des dernières barres archivées en Parquet (data/) "
        "+ affichage du bandeau DÉGRADÉ, ou scraping des cotations MarketWatch / Investing."
    )

    for symbol in symbols:
        name = f"yfinance {symbol}"
        start_time = time.perf_counter()
        success = False
        last_error = None
        last_close: float | None = None
        quote_dt: datetime | None = None
        is_midnight = False

        for attempt in range(1, max_retries + 1):
            try:
                t = yf.Ticker(symbol)
                # First try 1d intraday 1m
                hist = t.history(period="1d", interval="1m", timeout=timeout)
                if hist.empty:
                    # Over weekend or outside sessions, try 5d 5m for recent real bar
                    hist = t.history(period="5d", interval="5m", timeout=timeout)

                if not hist.empty:
                    last_close = float(hist["Close"].iloc[-1])
                    idx_val = hist.index[-1]
                    if hasattr(idx_val, "to_pydatetime"):
                        quote_dt = idx_val.to_pydatetime()
                    elif isinstance(idx_val, datetime):
                        quote_dt = idx_val

                # Check metadata regularMarketTime
                try:
                    meta_rmt = t.history_metadata.get("regularMarketTime")
                    if meta_rmt is not None:
                        if isinstance(meta_rmt, (int, float)):
                            dt_rmt = datetime.fromtimestamp(meta_rmt, tz=timezone.utc)
                        elif isinstance(meta_rmt, datetime):
                            dt_rmt = (
                                meta_rmt
                                if meta_rmt.tzinfo
                                else meta_rmt.replace(tzinfo=TZ_NEW_YORK)
                            )
                        else:
                            dt_rmt = None
                        if dt_rmt is not None and (quote_dt is None or dt_rmt > quote_dt):
                            quote_dt = dt_rmt
                except Exception:
                    pass

                # If still no quote_dt, check daily bar but reject midnight (00:00:00)
                if quote_dt is None:
                    daily_hist = t.history(period="1d", timeout=timeout)
                    if not daily_hist.empty:
                        last_close = float(daily_hist["Close"].iloc[-1])
                        idx_val = daily_hist.index[-1]
                        if hasattr(idx_val, "to_pydatetime"):
                            dt_cand = idx_val.to_pydatetime()
                        elif isinstance(idx_val, datetime):
                            dt_cand = idx_val
                        else:
                            dt_cand = None

                        if dt_cand is not None:
                            ny_cand = (
                                dt_cand.astimezone(TZ_NEW_YORK)
                                if dt_cand.tzinfo
                                else dt_cand.replace(tzinfo=TZ_NEW_YORK)
                            )
                            if (
                                ny_cand.hour == 0
                                and ny_cand.minute == 0
                                and ny_cand.second == 0
                            ):
                                is_midnight = True
                                quote_dt = None
                            else:
                                quote_dt = dt_cand

                if quote_dt is not None or is_midnight or last_close is not None:
                    success = True
                    break
                else:
                    last_error = "Historique vide (marché fermé ou symbole inconnu)"
            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    time.sleep(DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1)))

        latency = (time.perf_counter() - start_time) * 1000.0

        if success:
            group = None
            if symbol == "NQ=F":
                group = "cme_futures"
            elif symbol in ("^NDX", "^VIX", "^VXN"):
                group = "us_equities"

            status, session_msg, data_age_min, data_ts_ny = evaluate_symbol_session(
                symbol_or_name=symbol,
                quote_dt=quote_dt,
                session_group=group,
                stale_threshold_minutes=stale_threshold_minutes,
                is_midnight=is_midnight,
            )

            close_str = f"Dernier cours={last_close:.2f}" if last_close is not None else ""
            msg = f"{close_str} | {session_msg}" if close_str else session_msg

            results.append(
                SourceCheckResult(
                    name=name,
                    category="Prix/Vol",
                    status=status,
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    data_timestamp=data_ts_ny,
                    data_age_minutes=data_age_min,
                    message=msg,
                    fallback_plan=fallback,
                )
            )
        else:
            status = "DÉGRADÉ" if "vide" in str(last_error).lower() else "BLOQUÉ"
            results.append(
                SourceCheckResult(
                    name=name,
                    category="Prix/Vol",
                    status=status,
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    message=f"Erreur yfinance: {last_error}",
                    fallback_plan=fallback,
                )
            )

    return results


def check_fred(
    api_key: str | None = None,
    series: tuple[str, ...] = ("DGS2", "DGS10"),
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    stale_threshold_minutes: int = 1440,
) -> list[SourceCheckResult]:
    """Checks FRED API series (DGS2, DGS10).

    If key is missing:
    - DGS2 = INDISPONIBLE (no approximation, zero invented numbers)
    - DGS10 replaceable by ^TNX marked 'substitut yfinance'
    """
    key = api_key if api_key is not None else get_key("FRED_API_KEY")
    results = []
    ts_ny = get_now_ny_timestamp()

    if not key or not key.strip():
        for s in series:
            name = f"FRED {s}"
            if s == "DGS2":
                msg = "DGS2 = INDISPONIBLE (FRED_API_KEY non configurée dans .env)"
                fallback = (
                    "DGS2 (2 ans US) est INDISPONIBLE sans FRED_API_KEY. "
                    "Obtenir une clé API gratuite sur https://fred.stlouisfed.org. "
                    "Aucune approximation ni chiffre inventé."
                )
            else:
                msg = "DGS10 remplaçable par ^TNX (substitut yfinance)"
                fallback = (
                    "Utiliser le ticker ^TNX via yfinance comme substitut direct du rendement "
                    "10 ans US (marqué substitut yfinance). "
                    "Pour la série officielle FRED DGS10, clé gratuite sur https://fred.stlouisfed.org."
                )

            results.append(
                SourceCheckResult(
                    name=name,
                    category="Macro",
                    status="DÉGRADÉ",
                    latency_ms=0.0,
                    measured_at_ny=ts_ny,
                    endpoint="https://api.stlouisfed.org/fred/series/observations",
                    message=msg,
                    fallback_plan=fallback,
                )
            )
        return results

    base_url = "https://api.stlouisfed.org/fred/series/observations"
    for s in series:
        name = f"FRED {s}"
        url = f"{base_url}?series_id={s}&api_key={key}&file_type=json"
        masked_endpoint = f"{base_url}?series_id={s}&api_key=[REDACTED]&file_type=json"
        fallback = f"En cas d'indisponibilité de la série {s} : " + (
            "utiliser ^TNX comme substitut direct."
            if s == "DGS10"
            else "marquer DGS2 INDISPONIBLE sans approximation."
        )

        resp, latency, err = request_with_retry(url, timeout=timeout, max_retries=max_retries)
        if err is not None:
            results.append(
                SourceCheckResult(
                    name=name,
                    category="Macro",
                    status="BLOQUÉ",
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    endpoint=masked_endpoint,
                    message=f"Échec connexion FRED: {err}",
                    fallback_plan=fallback,
                )
            )
            continue

        if resp is None or resp.status_code != 200:
            status_code = resp.status_code if resp is not None else None
            results.append(
                SourceCheckResult(
                    name=name,
                    category="Macro",
                    status="BLOQUÉ" if status_code == 400 else "DÉGRADÉ",
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    http_status=status_code,
                    endpoint=masked_endpoint,
                    message=f"Erreur HTTP {status_code} (clé FRED invalide ou quota)",
                    fallback_plan=fallback,
                )
            )
            continue

        try:
            data = resp.json()
            obs = data.get("observations", [])
            last_obs = obs[-1] if obs else {}
            obs_date = last_obs.get("date")

            data_age_min = None
            if obs_date:
                try:
                    dt_obs = datetime.fromisoformat(obs_date).replace(tzinfo=timezone.utc)
                    age_s = (datetime.now(timezone.utc) - dt_obs).total_seconds()
                    data_age_min = max(0.0, age_s / 60.0)
                except Exception:
                    pass

            results.append(
                SourceCheckResult(
                    name=name,
                    category="Macro",
                    status="OK",
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    http_status=200,
                    data_timestamp=obs_date,
                    data_age_minutes=round(data_age_min, 1) if data_age_min is not None else None,
                    endpoint=masked_endpoint,
                    message=f"OK (Obs {obs_date} = {last_obs.get('value')}%) | âge non jugé",
                    fallback_plan=fallback,
                )
            )
        except Exception as exc:
            results.append(
                SourceCheckResult(
                    name=name,
                    category="Macro",
                    status="DÉGRADÉ",
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    http_status=200,
                    endpoint=masked_endpoint,
                    message=f"Erreur décodage JSON FRED: {exc}",
                    fallback_plan=fallback,
                )
            )

    return results


def check_cftc_cot(
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> SourceCheckResult:
    """Checks CFTC COT report accessibility via cot_reports."""
    name = "CFTC COT (cot_reports)"
    category = "Macro"
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "Téléchargement direct du zip hebdomadaire CFTC (https://www.cftc.gov/files/dea/history/) "
        "ou maintien des données du dernier rapport hebdomadaire en cache local."
    )

    import cot_reports as cot

    start_time = time.perf_counter()
    current_year = datetime.now().year
    success = False
    error_msg = None
    row_count = 0

    orig_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        for attempt in range(1, max_retries + 1):
            try:
                os.chdir(tmp_dir)
                df = cot.cot_year(year=current_year, cot_report_type="legacy_fut")
                if df is not None and not df.empty:
                    success = True
                    row_count = len(df)
                    break
                else:
                    error_msg = "Rapport COT retourné vide"
            except Exception as exc:
                error_msg = str(exc)
                if attempt < max_retries:
                    time.sleep(DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1)))
            finally:
                os.chdir(orig_cwd)

    annual_path = Path("annual.txt")
    if annual_path.is_file():
        try:
            annual_path.unlink()
        except OSError:
            pass

    latency = (time.perf_counter() - start_time) * 1000.0

    if success:
        return SourceCheckResult(
            name=name,
            category=category,
            status="OK",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            message=f"OK ({row_count} lignes COT {current_year}) | âge non jugé",
            fallback_plan=fallback,
        )
    return SourceCheckResult(
        name=name,
        category=category,
        status="DÉGRADÉ",
        latency_ms=latency,
        measured_at_ny=ts_ny,
        message=f"Échec cot_reports: {error_msg}",
        fallback_plan=fallback,
    )


def check_fed_sources(
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> list[SourceCheckResult]:
    """Checks Federal Reserve official FOMC calendar and RSS feed pages."""
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "En cas d'indisponibilité du site de la Fed : bascule vers le calendrier ForexFactory "
        "hebdomadaire en contrôle croisé, et consultation des comptes-rendus via archives locales."
    )

    targets = [
        (
            "Fed FOMC Calendars",
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "Calendrier officiel des réunions FOMC",
        ),
        (
            "Fed RSS Directory",
            "https://www.federalreserve.gov/feeds/feeds.htm",
            "Page officielle d'annuaire des flux RSS de la Fed",
        ),
        (
            "Fed Press Releases RSS",
            "https://www.federalreserve.gov/feeds/press_all.xml",
            "Flux RSS officiel des communiqués de presse de la Fed",
        ),
    ]

    results = []
    for name, url, desc in targets:
        resp, latency, err = request_with_retry(url, timeout=timeout, max_retries=max_retries)
        if err is not None:
            results.append(
                SourceCheckResult(
                    name=name,
                    category="Events",
                    status="BLOQUÉ",
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    endpoint=url,
                    message=f"Erreur de connexion Fed: {err}",
                    fallback_plan=fallback,
                )
            )
            continue

        if resp is None or resp.status_code != 200:
            status_code = resp.status_code if resp is not None else None
            results.append(
                SourceCheckResult(
                    name=name,
                    category="Events",
                    status="BLOQUÉ" if status_code in (403, 404) else "DÉGRADÉ",
                    latency_ms=latency,
                    measured_at_ny=ts_ny,
                    http_status=status_code,
                    endpoint=url,
                    message=f"Statut HTTP {status_code}",
                    fallback_plan=fallback,
                )
            )
            continue

        results.append(
            SourceCheckResult(
                name=name,
                category="Events",
                status="OK",
                latency_ms=latency,
                measured_at_ny=ts_ny,
                http_status=200,
                endpoint=url,
                message=f"OK ({desc})",
                fallback_plan=fallback,
            )
        )

    return results


def check_bls(
    contact_email: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> SourceCheckResult:
    """Checks BLS news release schedule using configured User-Agent email."""
    name = "BLS Schedule"
    category = "Events"
    url = "https://www.bls.gov/schedule/news_release/"
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "Le BLS exige un email de contact dans l'en-tête User-Agent (configuré via "
        "BLS_CONTACT_EMAIL dans .env ou sources.bls_contact_email dans config.yaml). "
        "En repli : recoupement avec ForexFactory et publications instantanées FRED (CPI, NFP)."
    )

    email = get_bls_contact_email(contact_email)
    headers = {
        "User-Agent": (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 NQCockpit/1.0 ({email})"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    resp, latency, err = request_with_retry(
        url, headers=headers, timeout=timeout, max_retries=max_retries
    )
    if err is not None:
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            endpoint=url,
            message=f"Erreur de connexion BLS: {err}",
            fallback_plan=fallback,
        )

    if resp is None or resp.status_code != 200:
        status_code = resp.status_code if resp is not None else None
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ" if status_code == 403 else "DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=status_code,
            endpoint=url,
            message=f"BLS HTTP {status_code} (vérifier BLS_CONTACT_EMAIL)",
            fallback_plan=fallback,
        )

    return SourceCheckResult(
        name=name,
        category=category,
        status="OK",
        latency_ms=latency,
        measured_at_ny=ts_ny,
        http_status=200,
        endpoint=url,
        message="OK (Calendrier des publications statistiques BLS accessible)",
        fallback_plan=fallback,
    )


def check_forexfactory(
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> SourceCheckResult:
    """Checks ForexFactory weekly calendar JSON (unofficial)."""
    name = "ForexFactory Calendar"
    category = "Events"
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "Le flux JSON ForexFactory est non officiel et peut changer de structure. "
        "En repli : exploitation directe des flux officiels Fed, BLS et BEA."
    )

    resp, latency, err = request_with_retry(url, timeout=timeout, max_retries=max_retries)
    if err is not None:
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            endpoint=url,
            message=f"Erreur connexion ForexFactory: {err}",
            fallback_plan=fallback,
        )

    if resp is None or resp.status_code != 200:
        status_code = resp.status_code if resp is not None else None
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ" if status_code in (403, 404) else "DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=status_code,
            endpoint=url,
            message=f"HTTP {status_code}",
            fallback_plan=fallback,
        )

    try:
        events = resp.json()
        if isinstance(events, list):
            return SourceCheckResult(
                name=name,
                category=category,
                status="OK",
                latency_ms=latency,
                measured_at_ny=ts_ny,
                http_status=200,
                endpoint=url,
                message=f"OK ({len(events)} événements cette semaine) | âge non jugé",
                fallback_plan=fallback,
            )
        return SourceCheckResult(
            name=name,
            category=category,
            status="DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=200,
            endpoint=url,
            message="Format JSON inattendu (pas une liste)",
            fallback_plan=fallback,
        )
    except Exception as exc:
        return SourceCheckResult(
            name=name,
            category=category,
            status="DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=200,
            endpoint=url,
            message=f"Erreur décodage JSON: {exc}",
            fallback_plan=fallback,
        )


def check_gemini(
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> SourceCheckResult:
    """Checks Gemini API connectivity. Zero network call if key is absent."""
    key = api_key if api_key is not None else get_key("GEMINI_API_KEY")
    name = "Gemini API"
    category = "LLM/Brief"
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "Clé gratuite sur https://aistudio.google.com. En cas d'absence de clé ou blocage, "
        "le cockpit utilise la génération déterministe de briefing sans LLM "
        "(docs/PRODUCT_SPEC.md M12) ou un modèle local (Ollama / mistral)."
    )

    if not key or not key.strip():
        return SourceCheckResult(
            name=name,
            category=category,
            status="DÉGRADÉ",
            latency_ms=0.0,
            measured_at_ny=ts_ny,
            endpoint="https://generativelanguage.googleapis.com/v1beta/models",
            message="GEMINI_API_KEY non configurée dans .env (optionnel)",
            fallback_plan=fallback,
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    masked_endpoint = "https://generativelanguage.googleapis.com/v1beta/models?key=[REDACTED]"

    resp, latency, err = request_with_retry(url, timeout=timeout, max_retries=max_retries)
    if err is not None:
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            endpoint=masked_endpoint,
            message=f"Connexion Gemini impossible: {err}",
            fallback_plan=fallback,
        )

    if resp is None or resp.status_code != 200:
        status_code = resp.status_code if resp is not None else None
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ" if status_code in (400, 403) else "DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=status_code,
            endpoint=masked_endpoint,
            message=f"Erreur HTTP {status_code} (clé Gemini invalide ou quota)",
            fallback_plan=fallback,
        )

    return SourceCheckResult(
        name=name,
        category=category,
        status="OK",
        latency_ms=latency,
        measured_at_ny=ts_ny,
        http_status=200,
        endpoint=masked_endpoint,
        message="OK (API Google Gemini accessible)",
        fallback_plan=fallback,
    )


def check_telegram(
    bot_token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> SourceCheckResult:
    """Checks Telegram Bot API via getMe call. Zero network call if token is absent."""
    token = bot_token if bot_token is not None else get_key("TELEGRAM_BOT_TOKEN")
    name = "Telegram Bot API"
    category = "Alerts"
    ts_ny = get_now_ny_timestamp()
    fallback = (
        "Créer un bot gratuit via @BotFather sur Telegram. En repli si Telegram est indisponible : "
        "notifications système de bureau locales (bannières OS) ou e-mail SMTP."
    )

    if not token or not token.strip():
        return SourceCheckResult(
            name=name,
            category=category,
            status="DÉGRADÉ",
            latency_ms=0.0,
            measured_at_ny=ts_ny,
            endpoint="https://api.telegram.org/bot[TOKEN]/getMe",
            message="TELEGRAM_BOT_TOKEN non configuré dans .env (optionnel)",
            fallback_plan=fallback,
        )

    url = f"https://api.telegram.org/bot{token}/getMe"
    masked_endpoint = "https://api.telegram.org/bot[REDACTED]/getMe"

    resp, latency, err = request_with_retry(url, timeout=timeout, max_retries=max_retries)
    if err is not None:
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            endpoint=masked_endpoint,
            message=f"Connexion Telegram impossible: {err}",
            fallback_plan=fallback,
        )

    if resp is None or resp.status_code != 200:
        status_code = resp.status_code if resp is not None else None
        return SourceCheckResult(
            name=name,
            category=category,
            status="BLOQUÉ" if status_code in (401, 404) else "DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=status_code,
            endpoint=masked_endpoint,
            message=f"HTTP {status_code} (token Telegram invalide)",
            fallback_plan=fallback,
        )

    try:
        data = resp.json()
        bot_user = data.get("result", {}).get("username", "Inconnu")
        return SourceCheckResult(
            name=name,
            category=category,
            status="OK",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=200,
            endpoint=masked_endpoint,
            message=f"OK (Bot @{bot_user})",
            fallback_plan=fallback,
        )
    except Exception as exc:
        return SourceCheckResult(
            name=name,
            category=category,
            status="DÉGRADÉ",
            latency_ms=latency,
            measured_at_ny=ts_ny,
            http_status=200,
            endpoint=masked_endpoint,
            message=f"Erreur réponse JSON Telegram: {exc}",
            fallback_plan=fallback,
        )


def run_all_checks(
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    load_env: bool = True,
) -> SourceHealthReport:
    """Runs health checks for all data sources and compiles the report in America/New_York."""
    if load_env:
        load_environment()

    stale_thresh = DEFAULT_STALE_THRESHOLD_MINUTES
    contact_email = None
    try:
        cfg = load_config()
        stale_thresh = getattr(cfg.sources, "stale_data_threshold_minutes", stale_thresh)
        contact_email = getattr(cfg.sources, "bls_contact_email", None)
    except Exception:
        pass

    results: list[SourceCheckResult] = []

    # 1. CBOE NDX Options
    results.append(
        check_cboe_ndx(
            timeout=timeout,
            max_retries=max_retries,
            stale_threshold_minutes=stale_thresh,
        )
    )

    # 2. yfinance (NQ=F, ^NDX, ^VIX, ^VXN, ^TNX, DX-Y.NYB)
    results.extend(
        check_yfinance_symbols(
            timeout=timeout,
            max_retries=max_retries,
            stale_threshold_minutes=stale_thresh,
        )
    )

    # 3. FRED
    results.extend(check_fred(timeout=timeout, max_retries=max_retries))

    # 4. CFTC COT
    results.append(check_cftc_cot(timeout=timeout, max_retries=max_retries))

    # 5. Fed (calendrier + annuaire RSS + flux RSS presse)
    results.extend(check_fed_sources(timeout=timeout, max_retries=max_retries))

    # 6. BLS
    results.append(
        check_bls(
            contact_email=contact_email,
            timeout=timeout,
            max_retries=max_retries,
        )
    )

    # 7. ForexFactory
    results.append(check_forexfactory(timeout=timeout, max_retries=max_retries))

    # 8. Gemini API (zero network call if key is absent)
    results.append(check_gemini(timeout=timeout, max_retries=max_retries))

    # 9. Telegram Bot API (zero network call if token is absent)
    results.append(check_telegram(timeout=timeout, max_retries=max_retries))

    # Summary
    summary = {"OK": 0, "DÉGRADÉ": 0, "BLOQUÉ": 0}
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1

    now_utc = datetime.now(timezone.utc)
    now_ny_dt = now_utc.astimezone(TZ_NEW_YORK)

    return SourceHealthReport(
        generated_at_ny=now_ny_dt.isoformat(),
        generated_at_utc=now_utc.isoformat(),
        summary=summary,
        results=results,
    )
