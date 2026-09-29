"""Moteur de risque événementiel : GREEN / AMBER / RED.

Règles (logique marché en ET, affichage en Alger) :

RED  — Tier 1 dans [window_start - stand_aside_before, window_end + post_buffer]
     — OU Tier 1 déjà publié et toujours dans le tampon post-événement

AMBER — Tier 2 ou mégacap earnings dans [window_start - 2h, window_end + post_buffer]
      — OU Tier 1 dans les 2h avant/après les fenêtres (mais pas dans le buffer)

GREEN — Aucun des cas ci-dessus

La raison est TOUJOURS fournie explicitement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nqcockpit.events.models import CalendarEvent, EarningsEvent, EventRiskReport

UTC = timezone.utc
TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_ET = ZoneInfo("America/New_York")

_AMBER_PROXIMITY_MINUTES = 120  # 2h d'extension pour AMBER autour des fenêtres


def _fmt_algiers(dt: datetime) -> str:
    """Formate un datetime en heure Alger lisible."""
    alg = dt.astimezone(TZ_ALGIERS)
    return alg.strftime("%d %b %Y %H:%M (Alger)")


def _fmt_countdown(delta: timedelta) -> str:
    """Formate un timedelta en 'Xj Yh Zm'."""
    total_s = int(delta.total_seconds())
    if total_s < 0:
        return "passé"
    d = total_s // 86400
    h = (total_s % 86400) // 3600
    m = (total_s % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d}j")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def _window_utc_bounds(
    window_start_algiers: str,
    window_end_algiers: str,
    ref_utc: datetime,
) -> tuple[datetime, datetime]:
    """Calcule les bornes UTC d'une fenêtre Alger pour le jour de ref_utc."""
    alg_ref = ref_utc.astimezone(TZ_ALGIERS)
    sh, sm = (int(x) for x in window_start_algiers.split(":"))
    eh, em = (int(x) for x in window_end_algiers.split(":"))
    start_alg = alg_ref.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end_alg = alg_ref.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start_alg.astimezone(UTC), end_alg.astimezone(UTC)


def compute_event_risk(
    events: list[CalendarEvent],
    earnings: list[EarningsEvent],
    trading_windows: list[dict],
    post_buffer_min: int,
    stand_aside_before_min: int,
    ref_utc: datetime | None = None,
) -> EventRiskReport:
    """Calcule le niveau de risque événementiel pour la journée de trading.

    Args:
        events: Événements économiques classifiés.
        earnings: Résultats mégacaps.
        trading_windows: Liste de dicts {name, start, end} en heure Alger.
        post_buffer_min: Tampon post-événement Tier 1 (minutes).
        stand_aside_before_min: Minutes d'évitement avant un Tier 1.
        ref_utc: Horodatage de référence (now si None).

    Returns:
        EventRiskReport avec risk_level, reason, countdown, calendrier Alger.
    """
    if ref_utc is None:
        ref_utc = datetime.now(UTC)

    horizon_end = ref_utc + timedelta(days=1)  # Risque pour la journée en cours

    # Calculer les bornes UTC de chaque fenêtre de trading
    window_bounds: list[tuple[str, datetime, datetime]] = []
    for w in trading_windows:
        name = w.get("name", "trade")
        start_s = w.get("start", "15:30")
        end_s = w.get("end", "18:30")
        w_start, w_end = _window_utc_bounds(start_s, end_s, ref_utc)
        window_bounds.append((name, w_start, w_end))

    post_delta = timedelta(minutes=post_buffer_min)
    stand_delta = timedelta(minutes=stand_aside_before_min)
    amber_delta = timedelta(minutes=_AMBER_PROXIMITY_MINUTES)

    risk_level = "GREEN"
    reason = "Aucun événement significatif détecté dans les fenêtres de trading."
    red_reasons: list[str] = []
    amber_reasons: list[str] = []

    all_events_today = [e for e in events if e.scheduled_utc <= horizon_end]

    for ev in all_events_today:
        ev_utc = ev.scheduled_utc
        alg_str = _fmt_algiers(ev_utc)
        countdown = _fmt_countdown(ev_utc - ref_utc)

        for w_name, w_start, w_end in window_bounds:
            # Impact Tier 1 : [ev_utc - stand_delta, ev_utc + post_delta] chevauche [w_start, w_end]
            tier1_disrupts_window = (
                (w_start - post_delta) <= ev_utc <= (w_end + stand_delta)
            )
            # Zone périphérique AMBER : ±2h autour de la fenêtre
            near_window = (
                (w_start - amber_delta) <= ev_utc <= (w_end + amber_delta)
            )

            if ev.tier == 1:
                if tier1_disrupts_window:
                    red_reasons.append(
                        f"Tier 1 [{ev.name}] à {alg_str} dans {countdown} "
                        f"— couvre la fenêtre {w_name} "
                        f"(±tampon {stand_aside_before_min}m/{post_buffer_min}m)"
                    )
                elif near_window:
                    amber_reasons.append(
                        f"Tier 1 [{ev.name}] à {alg_str} dans {countdown} "
                        f"— dans la zone AMBER de {w_name} (±2h)"
                    )
            elif ev.tier == 2:
                if near_window:
                    amber_reasons.append(
                        f"Tier 2 [{ev.name}] à {alg_str} dans {countdown} "
                        f"— proche de la fenêtre {w_name}"
                    )

    # Earnings mégacaps
    for earn in earnings:
        if earn.scheduled_utc is None or earn.scheduled_utc > horizon_end:
            continue
        ev_utc = earn.scheduled_utc
        alg_str = _fmt_algiers(ev_utc)
        countdown = _fmt_countdown(ev_utc - ref_utc)
        for w_name, w_start, w_end in window_bounds:
            if (w_start - amber_delta) <= ev_utc <= (w_end + amber_delta):
                amber_reasons.append(
                    f"Résultats {earn.ticker} à {alg_str} dans {countdown} "
                    f"— proche de la fenêtre {w_name}"
                )

    if red_reasons:
        risk_level = "RED"
        reason = " | ".join(red_reasons)
    elif amber_reasons:
        risk_level = "AMBER"
        reason = " | ".join(amber_reasons)

    # Countdown vers le prochain événement
    future_events = sorted(
        [e for e in events if e.scheduled_utc > ref_utc],
        key=lambda e: e.scheduled_utc,
    )
    next_countdown = ""
    if future_events:
        nxt = future_events[0]
        cd = _fmt_countdown(nxt.scheduled_utc - ref_utc)
        next_countdown = (
            f"Prochain : {nxt.name} dans {cd} "
            f"({_fmt_algiers(nxt.scheduled_utc)})"
        )

    # Calendrier Alger des 14 prochains jours
    horizon_14d = ref_utc + timedelta(days=14)
    cal_display: list[str] = []
    tier_sym = {1: "[T1]", 2: "[T2]"}
    for ev in sorted(events, key=lambda e: e.scheduled_utc):
        if ev.scheduled_utc < ref_utc or ev.scheduled_utc > horizon_14d:
            continue
        alg = ev.scheduled_utc.astimezone(TZ_ALGIERS)
        et = ev.scheduled_utc.astimezone(TZ_ET)
        sym = tier_sym.get(ev.tier, "[--]")
        consensus_str = f" | fcst={ev.consensus}" if ev.consensus else ""
        previous_str = f" | prec={ev.previous}" if ev.previous else ""
        src_str = ",".join(ev.all_sources) if ev.all_sources else ev.source
        line = (
            f"{sym} {alg.strftime('%a %d %b %H:%M')} Alger ({et.strftime('%H:%M')} ET) | "
            f"Tier {ev.tier} | {ev.name}"
            f"{consensus_str}{previous_str} | [{src_str}]"
        )
        cal_display.append(line)

    return EventRiskReport(
        as_of_utc=ref_utc,
        risk_level=risk_level,
        reason=reason,
        events_14d=events,
        earnings_14d=earnings,
        next_event_countdown=next_countdown,
        calendar_display_algiers=cal_display,
    )
