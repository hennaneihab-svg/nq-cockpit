"""Orchestrateur du radar d'événements NQ Cockpit.

Appelle toutes les sources (Fed, BLS, BEA, FRED, ForexFactory, Earnings),
fusionne, classifie, calcule le risque, et exporte le rapport JSON.
"""

from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig, load_config
from nqcockpit.events.classifier import merge_and_classify
from nqcockpit.events.earnings import fetch_earnings_events
from nqcockpit.events.models import DataStatus, EventRiskReport, SourceHealth
from nqcockpit.events.risk import compute_event_risk
from nqcockpit.events.sources.bea import fetch_bea_events
from nqcockpit.events.sources.bls import fetch_bls_events
from nqcockpit.events.sources.fed import fetch_fed_events
from nqcockpit.events.sources.forexfactory import fetch_forexfactory_events
from nqcockpit.events.sources.fred import fetch_fred_events

log = logging.getLogger(__name__)

UTC = timezone.utc
TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_ET = ZoneInfo("America/New_York")


def fetch_event_radar(
    config: AppConfig | None = None,
    ref_utc: datetime | None = None,
    horizon_days: int | None = None,
) -> EventRiskReport:
    """Fetch et agrège tous les événements économiques et earnings.

    Paramètres:
        config: Config chargée (load_config() si None).
        ref_utc: Horodatage de référence (now UTC si None).
        horizon_days: Horizon en jours (config.events.horizon_days si None).

    Retourne:
        EventRiskReport complet avec risk_level, raison, calendrier, divergences.
    """
    if config is None:
        config = load_config()
    if ref_utc is None:
        ref_utc = datetime.now(UTC)
    if horizon_days is None:
        horizon_days = config.events.horizon_days

    ev_cfg = config.events
    sources_cfg = ev_cfg.sources or {}

    fed_rss_url = sources_cfg.get(
        "fed_rss",
        "https://www.federalreserve.gov/feeds/press_all.xml",
    )
    bls_base = sources_cfg.get(
        "bls_schedule_base",
        "https://www.bls.gov/schedule/news_release",
    )
    bea_url = sources_cfg.get(
        "bea_schedule",
        "https://www.bea.gov/news/schedule",
    )
    ff_this = sources_cfg.get(
        "forexfactory_thisweek",
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    )
    ff_next = sources_cfg.get(
        "forexfactory_nextweek",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    )
    fred_ids_raw = sources_cfg.get("fred_release_ids", {})
    fred_ids: dict[str, int] | None = (
        {k: int(v) for k, v in fred_ids_raw.items()}
        if isinstance(fred_ids_raw, dict) and fred_ids_raw
        else None
    )

    cache_dir = pathlib.Path(config.data.cache_dir)
    all_raw_events = []
    source_health: list[SourceHealth] = []

    # 1. Fed (RSS + statique)
    try:
        fed_evs, fed_st, fed_err = fetch_fed_events(
            rss_url=fed_rss_url,
            now_utc=ref_utc,
            horizon_days=horizon_days,
        )
        all_raw_events.extend(fed_evs)
        source_health.append(SourceHealth(
            source="fed",
            status=fed_st,
            events_count=len(fed_evs),
            error_msg=fed_err or None,
            fetched_utc=datetime.now(UTC),
        ))
        log.info("Fed: %d événements [%s]", len(fed_evs), fed_st.value)
    except Exception as exc:  # noqa: BLE001
        log.error("Fed fetch exception: %s", exc)
        source_health.append(SourceHealth(
            source="fed", status=DataStatus.BLOCKED, error_msg=str(exc)
        ))

    # 2. BLS
    try:
        bls_evs, bls_st, bls_err = fetch_bls_events(
            base_url=bls_base,
            now_utc=ref_utc,
            horizon_days=horizon_days,
        )
        all_raw_events.extend(bls_evs)
        source_health.append(SourceHealth(
            source="bls",
            status=bls_st,
            events_count=len(bls_evs),
            error_msg=bls_err or None,
            fetched_utc=datetime.now(UTC),
        ))
        log.info("BLS: %d événements [%s]", len(bls_evs), bls_st.value)
    except Exception as exc:  # noqa: BLE001
        log.error("BLS fetch exception: %s", exc)
        source_health.append(SourceHealth(
            source="bls", status=DataStatus.BLOCKED, error_msg=str(exc)
        ))

    # 3. BEA
    try:
        bea_evs, bea_st, bea_err = fetch_bea_events(
            schedule_url=bea_url,
            now_utc=ref_utc,
            horizon_days=horizon_days,
        )
        all_raw_events.extend(bea_evs)
        source_health.append(SourceHealth(
            source="bea",
            status=bea_st,
            events_count=len(bea_evs),
            error_msg=bea_err or None,
            fetched_utc=datetime.now(UTC),
        ))
        log.info("BEA: %d événements [%s]", len(bea_evs), bea_st.value)
    except Exception as exc:  # noqa: BLE001
        log.error("BEA fetch exception: %s", exc)
        source_health.append(SourceHealth(
            source="bea", status=DataStatus.BLOCKED, error_msg=str(exc)
        ))

    # 4. FRED (contrôle croisé)
    try:
        fred_evs, fred_st, fred_err = fetch_fred_events(
            release_ids=fred_ids,
            now_utc=ref_utc,
            horizon_days=horizon_days,
        )
        all_raw_events.extend(fred_evs)
        source_health.append(SourceHealth(
            source="fred",
            status=fred_st,
            events_count=len(fred_evs),
            error_msg=fred_err or None,
            fetched_utc=datetime.now(UTC),
        ))
        log.info("FRED: %d événements [%s]", len(fred_evs), fred_st.value)
    except Exception as exc:  # noqa: BLE001
        log.error("FRED fetch exception: %s", exc)
        source_health.append(SourceHealth(
            source="fred", status=DataStatus.BLOCKED, error_msg=str(exc)
        ))

    # 5. ForexFactory (contrôle croisé + consensus)
    try:
        ff_evs, ff_st, ff_err = fetch_forexfactory_events(
            thisweek_url=ff_this,
            nextweek_url=ff_next,
            now_utc=ref_utc,
            horizon_days=horizon_days,
        )
        all_raw_events.extend(ff_evs)
        source_health.append(SourceHealth(
            source="forexfactory",
            status=ff_st,
            events_count=len(ff_evs),
            error_msg=ff_err or None,
            fetched_utc=datetime.now(UTC),
        ))
        log.info("ForexFactory: %d événements [%s]", len(ff_evs), ff_st.value)
    except Exception as exc:  # noqa: BLE001
        log.error("ForexFactory fetch exception: %s", exc)
        source_health.append(SourceHealth(
            source="forexfactory", status=DataStatus.BLOCKED, error_msg=str(exc)
        ))

    # 6. Fusion + classification + divergences
    merged_events, divergences = merge_and_classify(
        all_raw_events,
        tier1_names=list(ev_cfg.tier1),
        tier2_names=list(ev_cfg.tier2),
    )

    # 7. Earnings mégacaps
    earnings = fetch_earnings_events(
        tickers=list(ev_cfg.megacaps),
        now_utc=ref_utc,
        horizon_days=horizon_days,
        cache_dir=cache_dir,
    )
    ok_count = sum(1 for e in earnings if e.status == DataStatus.OK)
    earnings_st = DataStatus.OK if ok_count == len(earnings) else (
        DataStatus.DEGRADED if ok_count > 0 else DataStatus.BLOCKED
    )
    earnings_err = (
        None if earnings_st == DataStatus.OK
        else f"{len(earnings) - ok_count} tickers sans date"
    )
    source_health.append(SourceHealth(
        source="yfinance_earnings",
        status=earnings_st,
        events_count=len(earnings),
        error_msg=earnings_err,
        fetched_utc=datetime.now(UTC),
    ))

    # 8. Calcul du risque
    windows_dicts = [
        {"name": w.name, "start": w.start, "end": w.end}
        for w in config.trading_windows_algiers
    ]
    report = compute_event_risk(
        events=merged_events,
        earnings=earnings,
        trading_windows=windows_dicts,
        post_buffer_min=ev_cfg.post_event_buffer_minutes,
        stand_aside_before_min=ev_cfg.stand_aside_before_minutes,
        ref_utc=ref_utc,
    )
    report.divergences = divergences
    report.source_health = source_health

    # 9. Export JSON
    _export_json(report, config)

    return report


def _export_json(report: EventRiskReport, config: AppConfig) -> None:
    """Exporte le rapport en JSON daté."""
    try:
        out_dir = pathlib.Path("data/events")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = report.as_of_utc.strftime("%Y%m%d_%H%M")
        out_path = out_dir / f"events_{ts}.json"
        payload = {
            "as_of_utc": report.as_of_utc.isoformat(),
            "risk_level": report.risk_level,
            "reason": report.reason,
            "next_event_countdown": report.next_event_countdown,
            "divergences": report.divergences,
            "source_health": [
                {
                    "source": s.source,
                    "status": s.status.value,
                    "events_count": s.events_count,
                    "error_msg": s.error_msg,
                }
                for s in report.source_health
            ],
            "events_14d": [
                {
                    "name": e.name,
                    "tier": e.tier,
                    "scheduled_utc": e.scheduled_utc.isoformat(),
                    "source": e.source,
                    "all_sources": e.all_sources,
                    "status": e.status.value,
                    "consensus": e.consensus,
                    "previous": e.previous,
                    "actual": e.actual,
                    "description": e.description,
                }
                for e in report.events_14d
            ],
            "earnings_14d": [
                {
                    "ticker": e.ticker,
                    "scheduled_utc": (
                        e.scheduled_utc.isoformat() if e.scheduled_utc else None
                    ),
                    "confirmed": e.confirmed,
                    "eps_estimate": e.eps_estimate,
                    "status": e.status.value,
                    "error_msg": e.error_msg,
                }
                for e in report.earnings_14d
            ],
            "calendar_display_algiers": report.calendar_display_algiers,
            "daily_risks": report.daily_risks,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Rapport événements exporté : %s", out_path)
    except OSError as exc:
        log.warning("Export JSON événements échoué : %s", exc)


def render_console(report: EventRiskReport) -> str:
    """Formate le rapport pour affichage console."""
    et_now = report.as_of_utc.astimezone(TZ_ET)
    alg_now = report.as_of_utc.astimezone(TZ_ALGIERS)
    lines = [
        "=" * 70,
        "  NQ COCKPIT · RADAR D'ÉVÉNEMENTS",
        f"  Horodatage : {et_now.strftime('%Y-%m-%d %H:%M')} ET | "
        f"{alg_now.strftime('%Y-%m-%d %H:%M')} Alger | "
        f"Risque : {report.risk_level}",
        "=" * 70,
        f"  Raison : {report.reason}",
    ]
    if report.next_event_countdown:
        lines.append(f"  {report.next_event_countdown}")

    if report.daily_risks:
        lines.append("-" * 70)
        lines.append("  RISQUE PAR JOUR (fenêtres de trading sur l'horizon) :")
        for dr in report.daily_risks:
            today_tag = " (Aujourd'hui)" if dr.get("is_today") else ""
            lbl = f"{dr['day_label']}{today_tag}"
            lines.append(f"    {lbl:<24s} : [{dr['risk_level']}] — {dr['reason']}")

    if report.divergences:
        lines.append("-" * 70)
        lines.append("  DIVERGENCES DÉTECTÉES :")
        for d in report.divergences:
            lines.append(f"    {d}")

    lines.append("-" * 70)
    lines.append("  CALENDRIER (14 prochains jours, heure Alger) :")
    if report.calendar_display_algiers:
        for line in report.calendar_display_algiers:
            lines.append(f"    {line}")
    else:
        lines.append("    Aucun événement dans l'horizon de 14 jours.")

    if report.earnings_14d:
        lines.append("-" * 70)
        lines.append("  RÉSULTATS MÉGACAPS :")
        for e in report.earnings_14d:
            if e.scheduled_utc:
                alg_e = e.scheduled_utc.astimezone(TZ_ALGIERS)
                et_e = e.scheduled_utc.astimezone(TZ_ET)
                dt_str = f"{alg_e.strftime('%d %b %H:%M')} Alger ({et_e.strftime('%H:%M')} ET)"
            else:
                dt_str = "date inconnue"
            st = e.status.value
            eps_str = f" | EPS fcst={e.eps_estimate:.2f}" if e.eps_estimate is not None else ""
            conf_str = "confirmée" if e.confirmed else "estimée"
            raw_date = e.scheduled_utc.strftime("%Y-%m-%d") if e.scheduled_utc else "N/A"
            lines.append(
                f"    {e.ticker}: {dt_str}{eps_str} [{conf_str}, brut: {raw_date}] [{st}]"
            )

    lines.append("-" * 70)
    lines.append("  STATUT DES SOURCES :")
    for s in report.source_health:
        err = f" — {s.error_msg}" if s.error_msg else ""
        lines.append(
            f"    [{s.status.value}] {s.source}: {s.events_count} événements{err}"
        )

    lines.append("=" * 70)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    report = fetch_event_radar()
    print(render_console(report))
