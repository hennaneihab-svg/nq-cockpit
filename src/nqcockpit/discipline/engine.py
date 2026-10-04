"""Machine à états de la séance et validation pré-trade (P09 réel).

Déterministe, temps réel, interrogable à tout moment.
AUCUN contournement possible du statut STOP.
AUCUNE exécution d'ordre.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig
from nqcockpit.discipline.models import (
    ChecklistResult,
    ChecklistVerdict,
    DisciplineSessionState,
    PreTradeChecklist,
    SessionDisciplineStatus,
)
from nqcockpit.journal.models import TradeEntry, TradeOutcome


def _parse_time(t_str: str) -> time:
    """Convertit un format 'HH:MM' en objet time."""
    parts = t_str.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def evaluate_session_state(
    trades: list[TradeEntry],
    now: datetime,
    config: AppConfig,
) -> DisciplineSessionState:
    """Évalue l'état vivant de la séance de trading à l'instant `now`.

    Vérifie :
    1. Présence dans une fenêtre de trading (heures d'Alger)
    2. Trades déjà pris aujourd'hui
    3. Limite de perte journalière (-2R)
    4. Annulation Trade 2 si Trade 1 en perte
    5. Cooldown en cours après un Stop Loss (compte à rebours)
    """
    tz_algiers = ZoneInfo(config.timezones.display)
    tz_market = ZoneInfo(config.timezones.market)

    # Assurer now avec timezone UTC
    now_utc = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    now_algiers = now_utc.astimezone(tz_algiers)
    now_ny = now_utc.astimezone(tz_market)
    today_ny_str = now_ny.date().isoformat()

    # 1. Fenêtre de trading active (Alger)
    current_time_algiers = now_algiers.time()
    active_window: str | None = None
    for win in config.trading_windows_algiers:
        start_t = _parse_time(win.start)
        end_t = _parse_time(win.end)
        if start_t <= current_time_algiers <= end_t:
            active_window = win.name
            break

    # 2. Trades de la séance courante
    session_trades = [t for t in trades if t.session_date == today_ny_str]
    session_trades.sort(key=lambda x: x.recorded_at)

    trades_taken = len(session_trades)
    max_trades = config.rules.max_trades_per_day

    # Si la règle d'annulation du trade 2 après perte du trade 1 est active
    # et que trade 1 est en perte, le nombre maximal de trades autorisés est ramené à 1.
    trade1_loss = (
        config.rules.cancel_trade2_if_trade1_loss
        and len(session_trades) >= 1
        and (session_trades[0].outcome == TradeOutcome.LOSS or session_trades[0].r_realized < 0)
    )
    effective_max_trades = 1 if trade1_loss else max_trades
    trades_remaining = max(0, effective_max_trades - trades_taken)
    r_today = round(sum(t.r_realized for t in session_trades), 4)

    # 3. Calcul du Cooldown post-SL
    last_sl_time: datetime | None = None
    cooldown_remaining_sec = 0.0
    cooldown_total_sec = config.rules.cooldown_after_sl_minutes * 60.0

    # Dernier trade en perte ou ayant touché son SL
    loss_trades = [
        t for t in session_trades
        if t.outcome == TradeOutcome.LOSS or t.r_realized < 0
    ]
    if loss_trades:
        last_loss = loss_trades[-1]
        last_sl_time = (
            last_loss.recorded_at if last_loss.recorded_at.tzinfo is not None
            else last_loss.recorded_at.replace(tzinfo=timezone.utc)
        )
        elapsed = (now_utc - last_sl_time).total_seconds()
        if elapsed < cooldown_total_sec:
            cooldown_remaining_sec = max(0.0, cooldown_total_sec - elapsed)

    # 4. Évaluation des verrous (par priorité logique)
    reasons: list[str] = []
    status = SessionDisciplineStatus.READY
    can_trade = True

    # Verrou A : Limite de perte journalière (-2R par défaut)
    if r_today <= -config.rules.daily_loss_limit_r:
        status = SessionDisciplineStatus.LOCKED_DAILY_LOSS
        can_trade = False
        reasons.append(
            f"Limite de perte journalière atteinte ({r_today:+.2f}R "
            f"<= -{config.rules.daily_loss_limit_r:.1f}R). Séance verrouillée."
        )

    # Verrou B : Annulation trade 2 si trade 1 en perte (priorité sur max trades)
    elif trade1_loss:
        status = SessionDisciplineStatus.LOCKED_TRADE1_LOSS
        can_trade = False
        reasons.append(
            "Trade 2 annulé : le premier trade de la séance a terminé en perte "
            "(règle stricte anti-revenge trading)."
        )

    # Verrou C : Nombre maximal de trades atteint ou dépassé
    elif trades_taken >= max_trades:
        status = SessionDisciplineStatus.LOCKED_MAX_TRADES
        can_trade = False
        if trades_taken > max_trades:
            reasons.append(
                f"Nombre maximal de trades dépassé ({trades_taken}/{max_trades} trades "
                "enregistrés). Séance terminée."
            )
        else:
            reasons.append(
                f"Nombre maximal de trades atteint ({max_trades}/{max_trades}). "
                "Séance terminée."
            )

    # Verrou D : Cooldown post-SL actif
    elif cooldown_remaining_sec > 0.0:
        status = SessionDisciplineStatus.COOLDOWN_ACTIVE
        can_trade = False
        rem_m = int(cooldown_remaining_sec // 60)
        rem_s = int(cooldown_remaining_sec % 60)
        reasons.append(
            f"Pause obligatoire active après SL : reste {rem_m:02d}:{rem_s:02d} "
            f"avant toute nouvelle entrée (cooldown {config.rules.cooldown_after_sl_minutes} min)."
        )

    # Verrou E : Hors fenêtre horaire
    elif active_window is None:
        status = SessionDisciplineStatus.OUT_OF_WINDOW
        can_trade = False
        win_str = " / ".join(
            f"{w.name} ({w.start}-{w.end})" for w in config.trading_windows_algiers
        )
        reasons.append(
            f"Hors fenêtre horaire autorisée. Fenêtres d'Alger : {win_str}."
        )

    return DisciplineSessionState(
        status=status,
        can_trade=can_trade,
        current_window_name=active_window,
        trades_taken_today=trades_taken,
        max_trades_allowed=effective_max_trades,
        trades_remaining=trades_remaining,
        r_realized_today=r_today,
        daily_loss_limit_r=config.rules.daily_loss_limit_r,
        last_sl_timestamp=last_sl_time,
        cooldown_remaining_seconds=round(cooldown_remaining_sec, 1),
        lock_reasons=reasons,
    )


def evaluate_checklist(
    checklist: PreTradeChecklist,
    session_state: DisciplineSessionState,
    config: AppConfig,
) -> ChecklistResult:
    """Valide la checklist pré-trade de façon stricte.

    GO = Tous les critères sans exception validés.
    STOP = Au moins un critère non rempli, avec cause explicite.
    """
    items_status: dict[str, bool] = {}
    blocking_reasons: list[str] = []

    # 1. État de la machine à états de la journée
    if session_state.can_trade:
        items_status["session_gate"] = True
    else:
        items_status["session_gate"] = False
        blocking_reasons.extend(session_state.lock_reasons)

    # 2. Risque événementiel (pas d'événement Tier 1 RED imminent ou en cours)
    if not checklist.event_risk_tier1_red:
        items_status["event_risk"] = True
    else:
        items_status["event_risk"] = False
        blocking_reasons.append(
            "Événement Tier 1 imminent ou en cours (statut ROUGE). "
            "Trading strictement interdit."
        )

    # 3. Contexte du jour confirmé (profil P08 consulté)
    if checklist.p08_reviewed:
        items_status["p08_context"] = True
    else:
        items_status["p08_context"] = False
        blocking_reasons.append(
            "Profil de séance P08 non consulté (confirmation requise)."
        )

    # 4. Plan écrit explicite (non vide, min 10 caractères)
    plan_clean = checklist.trading_plan.strip()
    if len(plan_clean) >= 10:
        items_status["plan_defined"] = True
    else:
        items_status["plan_defined"] = False
        blocking_reasons.append(
            "Plan de trade manquant ou insuffisant (au moins 10 caractères requis)."
        )

    # 5. Dimensionnement de position calculé et valide
    sizing = checklist.sizing_result
    if sizing is not None and sizing.contracts > 0 and not sizing.warning:
        items_status["sizing_validated"] = True
    else:
        items_status["sizing_validated"] = False
        if sizing is None:
            blocking_reasons.append("Calcul de taille de position non exécuté.")
        elif sizing.contracts == 0:
            blocking_reasons.append(
                f"Taille de position nulle (0 contrat) : {sizing.warning or 'budget insuffisant'}."
            )
        elif sizing.warning:
            blocking_reasons.append(f"Erreur de sizing : {sizing.warning}")

    passed = all(items_status.values())
    verdict = ChecklistVerdict.GO if passed else ChecklistVerdict.STOP

    return ChecklistResult(
        verdict=verdict,
        passed=passed,
        blocking_reasons=blocking_reasons,
        items_status=items_status,
    )
