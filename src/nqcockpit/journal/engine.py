"""Moteur P09 — discipline, statistiques et coaching.

Règles impératives (AGENTS.md / performance-coaching skill) :
- Toutes les stats reposent UNIQUEMENT sur les trades enregistrés dans le journal.
- Sous les seuils (min_trades, min_pattern_samples), afficher "échantillon insuffisant".
- IC Wilson 95 % pour win rate ; bootstrap pour espérance si n >= 30, sinon IC approximé.
- Détection des violations avec cause explicite (pas de statut global qui masque).
- Alertes de tilt : signalent un risque, ne bloquent pas.
- Coaching factuel, sans jugement émotionnel.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timezone

from nqcockpit.config import AppConfig
from nqcockpit.journal.models import (
    CoachingReport,
    DailyStats,
    DisciplineFlag,
    DisciplineViolationType,
    PerformanceStats,
    TiltAlert,
    TradeEntry,
    TradeOutcome,
)
from nqcockpit.journal.store import load_trades, save_trade

logger = logging.getLogger(__name__)

# Seuil minimal pour les statistiques de sous-groupes (setup, régime, etc.)
_MIN_PATTERN_SAMPLES = 12


# ---------------------------------------------------------------------------
# Calcul du R et outcome
# ---------------------------------------------------------------------------


def finalize_trade(trade: TradeEntry) -> TradeEntry:
    """Calcule r_realized et outcome depuis les prix bruts.

    Modifie le trade en place et le retourne.
    """
    trade.r_realized = trade.compute_r()
    if trade.r_realized > 0.05:
        trade.outcome = TradeOutcome.WIN
    elif trade.r_realized < -0.05:
        trade.outcome = TradeOutcome.LOSS
    else:
        trade.outcome = TradeOutcome.BREAKEVEN
    return trade


# ---------------------------------------------------------------------------
# Détection des violations de discipline
# ---------------------------------------------------------------------------


def detect_violations(
    trade: TradeEntry,
    session_trades: list[TradeEntry],
    config: AppConfig,
) -> list[DisciplineFlag]:
    """Détecte les violations de règles sur un trade donné.

    Args:
        trade: Le trade à contrôler.
        session_trades: Tous les trades de la même séance (ordonnés par temps).
        config: Configuration avec rules, trading_windows_algiers, risk.

    Returns:
        Liste de DisciplineFlag, chacun avec sa cause explicite.
    """
    flags: list[DisciplineFlag] = []
    rules = config.rules

    # --- Violation 1 : hors fenêtre ---
    window_names = {w.name for w in config.trading_windows_algiers}
    if trade.window_name and trade.window_name not in window_names:
        flags.append(DisciplineFlag(
            trade_id=trade.trade_id,
            violation=DisciplineViolationType.OUT_OF_WINDOW,
            detail=(
                f"Fenêtre '{trade.window_name}' inconnue dans la config "
                f"(fenêtres valides : {sorted(window_names)})"
            ),
        ))
    elif not trade.window_name:
        flags.append(DisciplineFlag(
            trade_id=trade.trade_id,
            violation=DisciplineViolationType.OUT_OF_WINDOW,
            detail="Aucune fenêtre de trading renseignée — trade hors kill zone.",
        ))

    # --- Violation 2 : > max_trades_per_day ---
    # Compter les trades de la séance AVANT ce trade (par recorded_at)
    prior = [t for t in session_trades if t.trade_id != trade.trade_id
             and t.recorded_at <= trade.recorded_at]
    if len(prior) >= rules.max_trades_per_day:
        flags.append(DisciplineFlag(
            trade_id=trade.trade_id,
            violation=DisciplineViolationType.TRADE_LIMIT,
            detail=(
                f"Trade {len(prior)+1} de la séance dépasse la limite "
                f"de {rules.max_trades_per_day} trades/jour."
            ),
        ))

    # --- Violation 3 : trade2 après perte de trade1 ---
    if rules.cancel_trade2_if_trade1_loss and trade.window_name == "trade2":
        t1_losses = [
            t for t in prior
            if t.window_name == "trade1" and t.outcome == TradeOutcome.LOSS
        ]
        if t1_losses:
            flags.append(DisciplineFlag(
                trade_id=trade.trade_id,
                violation=DisciplineViolationType.TRADE2_AFTER_LOSS,
                detail=(
                    f"Trade2 pris alors que le Trade1 ({t1_losses[-1].trade_id}) "
                    "était en perte. Règle cancel_trade2_if_trade1_loss activée."
                ),
            ))

    # --- Violation 4 : rentrée rapide après SL ---
    if trade.minutes_after_last_sl is not None:
        if 0 < trade.minutes_after_last_sl < rules.cooldown_after_sl_minutes:
            flags.append(DisciplineFlag(
                trade_id=trade.trade_id,
                violation=DisciplineViolationType.QUICK_REENTRY,
                detail=(
                    f"Rentrée {trade.minutes_after_last_sl:.1f} min après le dernier SL "
                    f"(cooldown requis : {rules.cooldown_after_sl_minutes} min)."
                ),
            ))

    # --- Violation 5 : SL déplacé ---
    if trade.sl_moved:
        flags.append(DisciplineFlag(
            trade_id=trade.trade_id,
            violation=DisciplineViolationType.MOVED_SL,
            detail="Stop Loss déplacé après l'entrée (sl_moved=True).",
        ))

    # --- Violation 6 : sortie anticipée ---
    if trade.early_exit:
        flags.append(DisciplineFlag(
            trade_id=trade.trade_id,
            violation=DisciplineViolationType.EARLY_EXIT,
            detail="Sortie avant TP/SL planifié (early_exit=True).",
        ))

    # --- Violation 7 : risque > limite ---
    risk_limit = config.risk.risk_per_trade_pct
    if risk_limit > 0 and trade.risk_pct_used > risk_limit:
        flags.append(DisciplineFlag(
            trade_id=trade.trade_id,
            violation=DisciplineViolationType.OVERSIZED,
            detail=(
                f"Risque utilisé {trade.risk_pct_used:.2f}% > limite "
                f"{risk_limit:.2f}% du compte."
            ),
        ))

    return flags


def detect_tilt_alerts(
    session_date: str,
    session_trades: list[TradeEntry],
    config: AppConfig,
    period_trades: list[TradeEntry] | None = None,
) -> list[TiltAlert]:
    """Détecte les signaux et patterns de tilt pour la séance.

    Ne bloque pas — signale factuellement les déviations statistiques et
    comportementales sans vocabulaire émotionnel ni jugement moral.
    """
    alerts: list[TiltAlert] = []
    if not session_trades:
        return alerts

    # Configuration des seuils
    max_daily = config.rules.max_trades_per_day
    raw_tilt = getattr(config.rules, "tilt", None)
    vengeance_minutes = (
        raw_tilt.vengeance_minutes
        if raw_tilt is not None
        else getattr(config.rules, "vengeance_minutes", 30.0)
    )
    size_mult_threshold = (
        raw_tilt.size_multiplier_threshold
        if raw_tilt is not None
        else getattr(config.rules, "size_multiplier_threshold", 1.5)
    )
    freq_max_trades = (
        raw_tilt.frequency_max_trades
        if raw_tilt is not None
        else getattr(config.rules, "frequency_max_trades", 3)
    )
    freq_window_min = (
        raw_tilt.frequency_window_minutes
        if raw_tilt is not None
        else getattr(config.rules, "frequency_window_minutes", 45.0)
    )

    # Trier par horodatage (entry_time_ny ou recorded_at)
    ordered = sorted(
        session_trades,
        key=lambda t: t.entry_time_ny or t.recorded_at,
    )

    # Pattern 1 : 2 pertes consécutives sur la même séance
    for i in range(1, len(ordered)):
        if (ordered[i - 1].outcome == TradeOutcome.LOSS
                and ordered[i].outcome == TradeOutcome.LOSS):
            alerts.append(TiltAlert(
                session_date=session_date,
                reason="2 pertes consécutives détectées sur la séance.",
                trades_involved=[ordered[i - 1].trade_id, ordered[i].trade_id],
                pattern_type="pertes_consécutives",
            ))
            break  # 1 alerte max par séance

    # Pattern 2 : Sur-trading (dépassement de la limite journalière)
    if len(ordered) > max_daily:
        alerts.append(TiltAlert(
            session_date=session_date,
            reason=(
                f"Sur-trading : {len(ordered)} trades enregistrés sur la séance "
                f"(seuil configuré : {max_daily} trades/jour max)."
            ),
            trades_involved=[t.trade_id for t in ordered],
            pattern_type="surtrading",
        ))

    # Pattern 3 : Vengeance trading (nouveau trade pris < X min après une perte)
    for i in range(1, len(ordered)):
        prev_t = ordered[i - 1]
        curr_t = ordered[i]
        if prev_t.outcome == TradeOutcome.LOSS:
            delta_min: float | None = None
            if curr_t.minutes_after_last_sl is not None:
                delta_min = float(curr_t.minutes_after_last_sl)
            elif prev_t.exit_time_ny and curr_t.entry_time_ny:
                delta_min = (curr_t.entry_time_ny - prev_t.exit_time_ny).total_seconds() / 60.0
            elif prev_t.recorded_at and curr_t.recorded_at:
                delta_min = (curr_t.recorded_at - prev_t.recorded_at).total_seconds() / 60.0

            if delta_min is not None and 0 <= delta_min < vengeance_minutes:
                alerts.append(TiltAlert(
                    session_date=session_date,
                    reason=(
                        f"Vengeance trading : nouveau trade pris {delta_min:.1f} min "
                        f"après une perte (seuil configuré : < {vengeance_minutes:.0f} min)."
                    ),
                    trades_involved=[prev_t.trade_id, curr_t.trade_id],
                    pattern_type="vengeance_trading",
                ))
                break

    # Pattern 4 : Taille de position anormale
    ref_trades = period_trades if period_trades is not None else session_trades
    valid_size_trades = [t for t in ref_trades if t.contracts is not None]
    if len(valid_size_trades) >= 2:
        mean_contracts = sum(t.contracts for t in valid_size_trades) / len(valid_size_trades)
        if mean_contracts > 0:
            for t in ordered:
                if t.contracts is None:
                    continue  # Purement ignoré : aucun chiffre inventé
                c = t.contracts
                if c >= mean_contracts * size_mult_threshold and c > mean_contracts:
                    alerts.append(TiltAlert(
                        session_date=session_date,
                        reason=(
                            f"Taille de position anormale : {c} contrat(s) exécuté(s) "
                            f"(moyenne observée : {mean_contracts:.2f} contrat(s), "
                            f"seuil configuré : >= {size_mult_threshold:.1f}x)."
                        ),
                        trades_involved=[t.trade_id],
                        pattern_type="taille_anormale",
                    ))

    # Pattern 5 : Accélération de fréquence (> N trades en <= M minutes glissantes)
    if len(ordered) > freq_max_trades:
        seen_bursts: set[tuple[str, ...]] = set()
        for i in range(len(ordered)):
            t_i = ordered[i]
            t_start = t_i.entry_time_ny or t_i.recorded_at
            window = [t_i]
            for j in range(i + 1, len(ordered)):
                t_j = ordered[j]
                t_time = t_j.entry_time_ny or t_j.recorded_at
                span = (t_time - t_start).total_seconds() / 60.0
                if span <= freq_window_min:
                    window.append(t_j)
                else:
                    break
            if len(window) > freq_max_trades:
                ids = tuple(t.trade_id for t in window)
                if not any(set(ids).issubset(set(s)) for s in seen_bursts):
                    seen_bursts.add(ids)
                    actual_span = (
                        (window[-1].entry_time_ny or window[-1].recorded_at) - t_start
                    ).total_seconds() / 60.0
                    alerts.append(TiltAlert(
                        session_date=session_date,
                        reason=(
                            f"Accélération de fréquence : {len(window)} trades exécutés "
                            f"en {actual_span:.1f} min (seuil configuré : > {freq_max_trades} "
                            f"trades en {freq_window_min:.0f} min)."
                        ),
                        trades_involved=list(ids),
                        pattern_type="accélération_fréquence",
                    ))

    return alerts


def detect_period_tilt_alerts(
    trades: list[TradeEntry],
    config: AppConfig,
) -> list[TiltAlert]:
    """Détecte les patterns de tilt sur un ensemble de trades (semaine ou mois).

    Regroupe les trades par séance tout en évaluant la taille anormale
    par rapport à l'échantillon complet de la période.
    """
    if not trades:
        return []

    sessions: dict[str, list[TradeEntry]] = {}
    for t in sorted(trades, key=lambda x: x.entry_time_ny or x.recorded_at):
        sessions.setdefault(t.session_date, []).append(t)

    period_alerts: list[TiltAlert] = []
    for s_date, s_trades in sessions.items():
        session_alerts = detect_tilt_alerts(
            session_date=s_date,
            session_trades=s_trades,
            config=config,
            period_trades=trades,
        )
        period_alerts.extend(session_alerts)
    return period_alerts


# ---------------------------------------------------------------------------
# Stats journalières
# ---------------------------------------------------------------------------


def compute_daily_stats(
    session_date: str,
    trades: list[TradeEntry],
    config: AppConfig,
) -> DailyStats:
    """Calcule les stats d'une séance + violations + tilt."""
    stats = DailyStats(
        session_date=session_date,
        daily_loss_limit_r=config.rules.daily_loss_limit_r,
    )
    if not trades:
        return stats

    stats.n_trades = len(trades)
    stats.n_wins = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
    stats.n_losses = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
    stats.n_breakeven = sum(1 for t in trades if t.outcome == TradeOutcome.BREAKEVEN)
    stats.r_total = round(sum(t.r_realized for t in trades), 4)
    stats.r_max_adverse = round(min((t.r_realized for t in trades), default=0.0), 4)
    stats.limit_hit = stats.r_total <= -config.rules.daily_loss_limit_r

    # Violations
    all_violations: list[DisciplineFlag] = []
    for trade in trades:
        viol = detect_violations(trade, trades, config)
        all_violations.extend(viol)
    stats.violations = all_violations

    # Tilt
    stats.tilt_alerts = detect_tilt_alerts(session_date, trades, config)

    # Compliance : trades sans aucune violation
    violated_ids = {f.trade_id for f in all_violations}
    n_compliant = sum(1 for t in trades if t.trade_id not in violated_ids)
    stats.n_compliant = n_compliant  # type: ignore[attr-defined]
    stats.compliance_rate = round(n_compliant / len(trades), 4)

    return stats


# ---------------------------------------------------------------------------
# Statistiques de performance (avec intervalles de confiance)
# ---------------------------------------------------------------------------


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance Wilson pour une proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def _expectancy_ci(r_values: list[float], z: float = 1.96) -> tuple[float, float, float]:
    """Espérance ± IC (méthode normale, valide si n >= 30)."""
    n = len(r_values)
    if n == 0:
        return (0.0, 0.0, 0.0)
    mean = sum(r_values) / n
    if n < 2:
        return (mean, mean, mean)
    variance = sum((r - mean) ** 2 for r in r_values) / (n - 1)
    se = math.sqrt(variance / n)
    return (mean, mean - z * se, mean + z * se)


def compute_performance_stats(
    trades: list[TradeEntry],
    min_trades: int = 60,
    min_pattern_samples: int = _MIN_PATTERN_SAMPLES,
    config: AppConfig | None = None,
) -> PerformanceStats:
    """Calcule les métriques de performance sur un ensemble de trades.

    Si n < min_trades → stats de base seulement, sample_sufficient=False.
    """
    stats = PerformanceStats(
        n_trades=len(trades),
        min_trades_required=min_trades,
        computed_at=datetime.now(timezone.utc),
    )
    if not trades:
        return stats

    stats.n_wins = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
    stats.n_losses = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
    stats.n_breakeven = sum(1 for t in trades if t.outcome == TradeOutcome.BREAKEVEN)
    stats.sample_sufficient = len(trades) >= min_trades

    r_values = [t.r_realized for t in trades]
    if r_values:
        stats.raw_mean_r = sum(r_values) / len(r_values)

    # Win rate + IC Wilson (calculé même avec n < seuil — mais signalé)
    if len(trades) > 0:
        stats.win_rate = stats.n_wins / len(trades)
        ci_low, ci_high = _wilson_ci(stats.n_wins, len(trades))
        stats.win_rate_ci_low = ci_low
        stats.win_rate_ci_high = ci_high

    # Espérance + IC (uniquement si sample_sufficient)
    if stats.sample_sufficient:
        mean, ci_low, ci_high = _expectancy_ci(r_values)
        stats.expectancy_r = mean
        stats.expectancy_ci_low = ci_low
        stats.expectancy_ci_high = ci_high

        # Avg win / avg loss
        win_r = [t.r_realized for t in trades if t.outcome == TradeOutcome.WIN]
        loss_r = [t.r_realized for t in trades if t.outcome == TradeOutcome.LOSS]
        stats.avg_win_r = sum(win_r) / len(win_r) if win_r else None
        stats.avg_loss_r = sum(loss_r) / len(loss_r) if loss_r else None

        # Profit factor
        gross_profit = sum(r for r in win_r if r > 0)
        gross_loss = abs(sum(r for r in loss_r if r < 0))
        stats.profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        # Max drawdown en R (série d'équité)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in r_values:
            equity += r
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        stats.max_drawdown_r = round(max_dd, 4)

        # Max série de pertes
        streak = 0
        max_streak = 0
        for t in trades:
            if t.outcome == TradeOutcome.LOSS:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        stats.max_loss_streak = max_streak

    # Compliance cohérente avec compute_daily_stats : trade sans aucune violation
    cfg = config
    if cfg is None:
        try:
            from nqcockpit.config import load_config
            cfg = load_config()
        except Exception:
            cfg = None

    violated_ids: set[str] = set()
    if cfg is not None:
        by_session: dict[str, list[TradeEntry]] = {}
        for t in trades:
            by_session.setdefault(t.session_date, []).append(t)
        for s_trades in by_session.values():
            for t in s_trades:
                if detect_violations(t, s_trades, cfg):
                    violated_ids.add(t.trade_id)
    else:
        for t in trades:
            if t.sl_moved or t.early_exit:
                violated_ids.add(t.trade_id)

    compliant = [t for t in trades if t.trade_id not in violated_ids]
    non_compliant = [t for t in trades if t.trade_id in violated_ids]
    stats.n_compliant = len(compliant)
    if len(trades) > 0:
        stats.compliance_rate = len(compliant) / len(trades)


    if len(compliant) >= min_pattern_samples:
        stats.expectancy_r_compliant = sum(t.r_realized for t in compliant) / len(compliant)
    if len(non_compliant) >= min_pattern_samples:
        stats.expectancy_r_noncompliant = (
            sum(t.r_realized for t in non_compliant) / len(non_compliant)
        )

    return stats


# ---------------------------------------------------------------------------
# Segmentation par sous-groupes (setup, régime, etc.)
# ---------------------------------------------------------------------------


def segment_performance(
    trades: list[TradeEntry],
    by: str,
    min_samples: int = _MIN_PATTERN_SAMPLES,
) -> dict[str, PerformanceStats]:
    """Performance par segment (setup_tag, gamma_regime, vol_regime, day_of_week).

    Segments avec n < min_samples → sample_sufficient=False.
    """
    groups: dict[str, list[TradeEntry]] = {}
    for t in trades:
        if by == "setup_tag":
            key = t.setup_tag or "(sans tag)"
        elif by == "gamma_regime":
            key = t.gamma_regime.value
        elif by == "vol_regime":
            key = t.vol_regime.value
        elif by == "day_of_week":
            days = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
            key = days[t.day_of_week] if 0 <= t.day_of_week <= 6 else "?"
        elif by == "event_risk":
            key = t.event_risk_label or "(aucun événement)"
        else:
            key = str(getattr(t, by, "?"))
        groups.setdefault(key, []).append(t)

    return {
        label: compute_performance_stats(group, min_trades=min_samples)
        for label, group in sorted(groups.items())
    }


def segment_by_setup_tag(
    trades: list[TradeEntry],
    min_samples: int = _MIN_PATTERN_SAMPLES,
) -> dict[str, PerformanceStats]:
    """Performance segmentée par setup_tag."""
    return segment_performance(trades, by="setup_tag", min_samples=min_samples)


def segment_by_gamma_regime(
    trades: list[TradeEntry],
    min_samples: int = _MIN_PATTERN_SAMPLES,
) -> dict[str, PerformanceStats]:
    """Performance segmentée par gamma_regime."""
    return segment_performance(trades, by="gamma_regime", min_samples=min_samples)


# ---------------------------------------------------------------------------
# Rapport de coaching
# ---------------------------------------------------------------------------


def generate_coaching_report(
    trades: list[TradeEntry],
    period: str,
    period_label: str,
    config: AppConfig,
) -> CoachingReport:
    """Génère un rapport de coaching factuel pour une période.

    Aucune conclusion sous 60 trades ou 12 occurrences d'un motif.
    Le ton est factuel, sans jugement émotionnel.
    """
    report = CoachingReport(
        period=period,
        period_label=period_label,
        generated_at=datetime.now(timezone.utc),
    )
    min_trades = config.validation.min_sessions  # réutilise le même seuil

    if len(trades) < min_trades:
        report.insufficient_data = True
        report.stats = compute_performance_stats(trades, min_trades=min_trades)
        report.top_leaks = [
            f"Échantillon insuffisant : {len(trades)}/{min_trades} trades "
            "— pas de conclusion possible sur les fuites."
        ]
        return report

    stats = compute_performance_stats(trades, min_trades=min_trades)
    report.stats = stats

    # --- Identifier les fuites chiffrées ---
    leaks: list[tuple[float, str]] = []  # (impact_r, description)

    # Fuite 1 : trades non conformes (SL déplacé ou sortie anticipée)
    nc = [t for t in trades if t.sl_moved or t.early_exit]
    if len(nc) >= _MIN_PATTERN_SAMPLES:
        nc_exp = sum(t.r_realized for t in nc) / len(nc)
        c_trades = [t for t in trades if not t.sl_moved and not t.early_exit]
        c_exp = sum(t.r_realized for t in c_trades) / len(c_trades) if c_trades else 0
        impact = nc_exp - c_exp
        leaks.append((abs(impact), (
            f"Trades non conformes (SL déplacé / sortie anticipée) : "
            f"n={len(nc)}, espérance={nc_exp:+.3f}R vs conformes {c_exp:+.3f}R "
            f"(écart {impact:+.3f}R par trade)"
        )))

    # Fuite 2 : rentrée rapide après SL (tilt)
    quick_reentry = [
        t for t in trades
        if t.minutes_after_last_sl is not None
        and 0 < t.minutes_after_last_sl < config.rules.cooldown_after_sl_minutes
    ]
    if len(quick_reentry) >= _MIN_PATTERN_SAMPLES:
        qr_exp = sum(t.r_realized for t in quick_reentry) / len(quick_reentry)
        leaks.append((abs(qr_exp), (
            f"Rentrées rapides après SL (<{config.rules.cooldown_after_sl_minutes} min) : "
            f"n={len(quick_reentry)}, espérance={qr_exp:+.3f}R"
        )))

    # Fuite 3 : trades hors fenêtre
    out_of_window = [t for t in trades if not t.window_name]
    if len(out_of_window) >= _MIN_PATTERN_SAMPLES:
        oow_exp = sum(t.r_realized for t in out_of_window) / len(out_of_window)
        leaks.append((abs(oow_exp), (
            f"Trades hors fenêtre : n={len(out_of_window)}, "
            f"espérance={oow_exp:+.3f}R"
        )))

    # Top 3 fuites par impact
    leaks.sort(key=lambda x: x[0], reverse=True)
    report.top_leaks = [desc for _, desc in leaks[:3]]
    if not report.top_leaks:
        report.top_leaks = ["Aucune fuite identifiable sur cet échantillon."]

    # Règle à renforcer (basée sur le type de violation le plus fréquent)
    viol_counts: dict[str, int] = {}
    for t in trades:
        for flag in detect_violations(t, trades, config):
            viol_counts[flag.violation.value] = viol_counts.get(flag.violation.value, 0) + 1
    if viol_counts:
        top_viol = max(viol_counts, key=viol_counts.__getitem__)
        report.rule_to_reinforce = (
            f"Réduire les violations «{top_viol}» "
            f"(détectées {viol_counts[top_viol]} fois sur la période)."
        )
    else:
        report.rule_to_reinforce = "Aucune violation dominante détectée — maintenir la rigueur."

    # Force à conserver
    if stats.compliance_rate is not None and stats.compliance_rate >= 0.80:
        report.strength_to_keep = (
            f"Taux de conformité élevé : {stats.compliance_rate:.0%} — "
            "maintenir cette discipline d'exécution."
        )
    elif stats.max_loss_streak <= 2:
        report.strength_to_keep = (
            f"Série de pertes consécutives maîtrisée (max {stats.max_loss_streak}) — "
            "bonne gestion de la perte."
        )
    else:
        report.strength_to_keep = "Continuer à documenter chaque trade pour affiner l'analyse."

    # Objectifs mesurables
    goals = []
    if stats.compliance_rate is not None and stats.compliance_rate < 0.85:
        target = min(1.0, (stats.compliance_rate or 0) + 0.10)
        goals.append(
            f"Porter le taux de conformité de {stats.compliance_rate:.0%} à {target:.0%}."
        )
    if stats.max_loss_streak >= 3:
        goals.append("Limiter la série de pertes : arrêter la séance après 2 pertes consécutives.")
    if not goals:
        goals.append("Maintenir les niveaux actuels de discipline sur la prochaine période.")
    report.measurable_goals = goals

    return report


# ---------------------------------------------------------------------------
# API de haut niveau
# ---------------------------------------------------------------------------


def log_trade(
    conn: sqlite3.Connection,
    trade: TradeEntry,
    config: AppConfig,
) -> tuple[TradeEntry, list[DisciplineFlag]]:
    """Finalise un trade, détecte les violations et l'enregistre en DB.

    Returns:
        (trade finalisé avec r_realized/outcome, liste des violations)
    """
    trade = finalize_trade(trade)
    session_trades = load_trades(conn, session_date=trade.session_date)
    violations = detect_violations(trade, session_trades, config)
    save_trade(conn, trade)
    if violations:
        logger.warning(
            "Trade %s : %d violation(s) détectée(s) : %s",
            trade.trade_id,
            len(violations),
            [v.violation.value for v in violations],
        )
    return trade, violations
