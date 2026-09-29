"""Earnings megacaps via yfinance.

Récupère les dates de publication des résultats trimestriels pour chaque
ticker de config.events.megacaps. Gestion DÉGRADÉE propre si yfinance
est absent, lève une exception, ou retourne des données vides.
Cache disque 12h pour éviter le flood Yahoo Finance.
"""

from __future__ import annotations

import json
import logging
import pathlib
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from nqcockpit.events.models import DataStatus, EarningsEvent

log = logging.getLogger(__name__)

UTC = timezone.utc
ET_TZ = ZoneInfo("America/New_York")

_CACHE_TTL_SECONDS = 12 * 3600


def _get_cache_path(cache_dir: pathlib.Path, ticker: str) -> pathlib.Path:
    return cache_dir / f"earnings_{ticker.upper()}.json"


def _load_cache(
    cache_path: pathlib.Path,
    now_utc: datetime,
) -> EarningsEvent | None:
    """Charge le cache disque si frais (< TTL)."""
    if not cache_path.is_file():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_ts = raw.get("fetched_utc")
        if fetched_ts is None:
            return None
        fetched_dt = datetime.fromisoformat(fetched_ts)
        if fetched_dt.tzinfo is None:
            fetched_dt = fetched_dt.replace(tzinfo=UTC)
        age_s = (now_utc - fetched_dt).total_seconds()
        if age_s > _CACHE_TTL_SECONDS:
            return None
        scheduled_raw = raw.get("scheduled_utc")
        scheduled_dt = (
            datetime.fromisoformat(scheduled_raw).replace(tzinfo=UTC)
            if scheduled_raw else None
        )
        return EarningsEvent(
            ticker=raw["ticker"],
            scheduled_utc=scheduled_dt,
            confirmed=raw.get("confirmed", False),
            eps_estimate=raw.get("eps_estimate"),
            revenue_estimate=raw.get("revenue_estimate"),
            source_fetched_utc=fetched_dt,
            source_age_seconds=age_s,
            status=DataStatus(raw.get("status", "OK")),
            error_msg=raw.get("error_msg"),
        )
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def _save_cache(cache_path: pathlib.Path, ev: EarningsEvent) -> None:
    """Sauvegarde l'événement en cache JSON."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ticker": ev.ticker,
            "scheduled_utc": (
                ev.scheduled_utc.isoformat() if ev.scheduled_utc else None
            ),
            "confirmed": ev.confirmed,
            "eps_estimate": ev.eps_estimate,
            "revenue_estimate": ev.revenue_estimate,
            "fetched_utc": (
                ev.source_fetched_utc.isoformat()
                if ev.source_fetched_utc else datetime.now(UTC).isoformat()
            ),
            "status": ev.status.value,
            "error_msg": ev.error_msg,
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("Earnings cache write failed for %s: %s", ev.ticker, exc)


def _fetch_yfinance_earnings(ticker: str) -> EarningsEvent:
    """Fetch la date de résultats via yfinance.Ticker.calendar."""
    now_utc = datetime.now(UTC)
    try:
        import yfinance as yf  # type: ignore[import]
    except ImportError:
        return EarningsEvent(
            ticker=ticker,
            scheduled_utc=None,
            status=DataStatus.DEGRADED,
            source_fetched_utc=now_utc,
            source_age_seconds=0.0,
            error_msg="yfinance non installé",
        )

    try:
        tkr = yf.Ticker(ticker)
        cal = tkr.calendar  # dict ou DataFrame
        scheduled_dt: datetime | None = None
        confirmed = False

        if cal is not None and not (hasattr(cal, "empty") and cal.empty):
            # yfinance >= 0.2 : calendar est un dict avec 'Earnings Date'
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed is not None:
                    # Peut être une liste ou une valeur unique
                    if isinstance(ed, list) and ed:
                        ed = ed[0]
                    if hasattr(ed, "to_pydatetime"):
                        scheduled_dt = ed.to_pydatetime()
                    elif isinstance(ed, datetime):
                        scheduled_dt = ed
                    elif isinstance(ed, date):
                        scheduled_dt = datetime.combine(ed, time(16, 30), tzinfo=ET_TZ)
                    if scheduled_dt is not None:
                        if scheduled_dt.tzinfo is None:
                            scheduled_dt = scheduled_dt.replace(tzinfo=ET_TZ)
                        scheduled_dt = scheduled_dt.astimezone(UTC)
                        confirmed = True
            elif hasattr(cal, "loc"):
                # DataFrame legacy
                try:
                    row = cal.loc["Earnings Date"]
                    if hasattr(row, "iloc"):
                        val = row.iloc[0]
                    else:
                        val = row
                    if hasattr(val, "to_pydatetime"):
                        scheduled_dt = val.to_pydatetime()
                    elif isinstance(val, datetime):
                        scheduled_dt = val
                    elif isinstance(val, date):
                        scheduled_dt = datetime.combine(val, time(16, 30), tzinfo=ET_TZ)
                    if scheduled_dt is not None:
                        if scheduled_dt.tzinfo is None:
                            scheduled_dt = scheduled_dt.replace(tzinfo=ET_TZ)
                        scheduled_dt = scheduled_dt.astimezone(UTC)
                        confirmed = True
                except (KeyError, IndexError):
                    pass

        eps_est: float | None = None
        rev_est: float | None = None
        if isinstance(cal, dict):
            eps_est = (
                cal.get("EPS Estimate")
                or cal.get("Earnings Estimate")
                or cal.get("Earnings Average")
            )
            rev_est = (
                cal.get("Revenue Estimate")
                or cal.get("Revenue Average")
            )
            if hasattr(eps_est, "item"):
                eps_est = float(eps_est.item())
            elif eps_est is not None:
                try:
                    eps_est = float(eps_est)
                except (TypeError, ValueError):
                    eps_est = None
            if hasattr(rev_est, "item"):
                rev_est = float(rev_est.item())
            elif rev_est is not None:
                try:
                    rev_est = float(rev_est)
                except (TypeError, ValueError):
                    rev_est = None

        status = DataStatus.OK if scheduled_dt is not None else DataStatus.DEGRADED
        err = None if scheduled_dt is not None else "Date de résultat non disponible"

        return EarningsEvent(
            ticker=ticker,
            scheduled_utc=scheduled_dt,
            confirmed=confirmed,
            eps_estimate=eps_est,
            revenue_estimate=rev_est,
            source_fetched_utc=now_utc,
            source_age_seconds=0.0,
            status=status,
            error_msg=err,
        )

    except Exception as exc:  # noqa: BLE001
        log.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return EarningsEvent(
            ticker=ticker,
            scheduled_utc=None,
            status=DataStatus.DEGRADED,
            source_fetched_utc=now_utc,
            source_age_seconds=0.0,
            error_msg=f"yfinance erreur: {exc}",
        )


def fetch_earnings_events(
    tickers: list[str],
    now_utc: datetime | None = None,
    horizon_days: int = 14,
    cache_dir: str | pathlib.Path = "data/cache",
) -> list[EarningsEvent]:
    """Fetch les dates de résultats pour chaque ticker.

    Utilise le cache disque (TTL 12h) pour éviter le flood Yahoo.
    Retourne toujours une liste, même si DÉGRADÉ.
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    cache_path_obj = pathlib.Path(cache_dir)

    results: list[EarningsEvent] = []
    for ticker in tickers:
        cp = _get_cache_path(cache_path_obj, ticker)
        cached = _load_cache(cp, now_utc)
        if cached is not None:
            ev = cached
            log.debug("Earnings %s: depuis cache (âge %.0fs)", ticker, ev.source_age_seconds)
        else:
            ev = _fetch_yfinance_earnings(ticker)
            _save_cache(cp, ev)

        # Filtrer seulement les dates déjà passées
        if ev.scheduled_utc is not None and ev.scheduled_utc < now_utc:
            continue

        results.append(ev)

    return results
