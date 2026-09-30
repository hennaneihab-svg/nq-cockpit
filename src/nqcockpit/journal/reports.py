"""Génération de rapports de performance périodiques Markdown (P11 élément 1).

Génère des synthèses hebdomadaires et mensuelles basées sur les trades du journal.
Réutilise exclusivement `compute_performance_stats`, `detect_violations` et l'IC Wilson.
Aucun vocabulaire directionnel implicite.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig, load_config
from nqcockpit.journal.engine import (
    compute_performance_stats,
    detect_period_tilt_alerts,
    detect_violations,
)
from nqcockpit.journal.models import PerformanceStats, TradeEntry
from nqcockpit.journal.store import load_trades

logger = logging.getLogger(__name__)


@dataclass
class PeriodReportResult:
    """Résultat de la génération d'un rapport de performance."""

    period: str  # "week" ou "month"
    period_label: str  # ex. "2026-W40" ou "2026-09"
    start_date: date
    end_date: date
    report_path: Path
    markdown_content: str
    n_trades: int
    r_total: float
    sample_sufficient: bool
    has_prev_data: bool


def get_period_bounds(
    period: str, ref_date: date
) -> tuple[date, date, str, date, date, str]:
    """Calcule les bornes de dates et labels pour la période courante et précédente.

    Returns:
        (curr_start, curr_end, curr_label, prev_start, prev_end, prev_label)
    """
    if period == "week":
        # Semaine ISO : lundi = weekday 0, dimanche = weekday 6
        curr_start = ref_date - timedelta(days=ref_date.weekday())
        curr_end = curr_start + timedelta(days=6)
        iso_year, iso_week, _ = ref_date.isocalendar()
        curr_label = f"{iso_year}-W{iso_week:02d}"

        prev_start = curr_start - timedelta(days=7)
        prev_end = curr_start - timedelta(days=1)
        p_ref = prev_start + timedelta(days=2)
        p_year, p_week, _ = p_ref.isocalendar()
        prev_label = f"{p_year}-W{p_week:02d}"

        return curr_start, curr_end, curr_label, prev_start, prev_end, prev_label

    if period == "month":
        curr_start = date(ref_date.year, ref_date.month, 1)
        if ref_date.month == 12:
            curr_end = date(ref_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            curr_end = date(ref_date.year, ref_date.month + 1, 1) - timedelta(days=1)
        curr_label = f"{ref_date.year}-{ref_date.month:02d}"

        if ref_date.month == 1:
            prev_start = date(ref_date.year - 1, 12, 1)
            prev_end = curr_start - timedelta(days=1)
            prev_label = f"{ref_date.year - 1}-12"
        else:
            prev_start = date(ref_date.year, ref_date.month - 1, 1)
            prev_end = curr_start - timedelta(days=1)
            prev_label = f"{ref_date.year}-{ref_date.month - 1:02d}"

        return curr_start, curr_end, curr_label, prev_start, prev_end, prev_label

    raise ValueError(f"Période non reconnue : {period!r}. Choisir 'week' ou 'month'.")


def filter_trades_by_date_range(
    trades: list[TradeEntry], start_date: date, end_date: date
) -> list[TradeEntry]:
    """Filtre les trades dont la session_date est dans l'intervalle inclusif."""
    filtered: list[TradeEntry] = []
    for t in trades:
        try:
            d = date.fromisoformat(t.session_date)
            if start_date <= d <= end_date:
                filtered.append(t)
        except ValueError:
            continue
    return sorted(filtered, key=lambda x: (x.session_date, x.recorded_at))


def count_violations_by_type(
    trades: list[TradeEntry], config: AppConfig
) -> dict[str, int]:
    """Compte les violations de discipline par type en réutilisant detect_violations."""
    counts: dict[str, int] = {}
    by_session: dict[str, list[TradeEntry]] = {}
    for t in trades:
        by_session.setdefault(t.session_date, []).append(t)

    for session_trades in by_session.values():
        for t in session_trades:
            flags = detect_violations(t, session_trades, config)
            for f in flags:
                key = f.violation.value
                counts[key] = counts.get(key, 0) + 1
    return counts


def generate_period_report(
    trades: list[TradeEntry],
    period: str,
    ref_date: Optional[date] = None,
    output_dir: str | Path = "reports/journal",
    config: Optional[AppConfig] = None,
) -> PeriodReportResult:
    """Génère et sauvegarde un rapport de performance Markdown pour la période spécifiée."""
    if config is None:
        config = load_config()

    if ref_date is None:
        tz = ZoneInfo(config.timezones.display)
        ref_date = datetime.now(tz).date()

    curr_start, curr_end, curr_label, prev_start, prev_end, prev_label = get_period_bounds(
        period, ref_date
    )

    curr_trades = filter_trades_by_date_range(trades, curr_start, curr_end)
    prev_trades = filter_trades_by_date_range(trades, prev_start, prev_end)

    curr_stats: PerformanceStats = compute_performance_stats(
        curr_trades, config=config
    )
    min_required = curr_stats.min_trades_required
    prev_stats: Optional[PerformanceStats] = None
    if prev_trades:
        prev_stats = compute_performance_stats(
            prev_trades, config=config
        )

    curr_r_total = round(sum(t.r_realized for t in curr_trades), 4)
    curr_r_mean = (
        round(curr_r_total / len(curr_trades), 4) if curr_trades else 0.0
    )
    violations_count = count_violations_by_type(curr_trades, config)
    total_violations = sum(violations_count.values())

    # Formatage de l'horodatage de génération
    tz_algiers = ZoneInfo(config.timezones.display)
    now_alg = datetime.now(tz_algiers).strftime("%Y-%m-%d %H:%M")

    period_title = "Hebdomadaire" if period == "week" else "Mensuel"
    prefix = "weekly" if period == "week" else "monthly"
    filename = f"{prefix}_{curr_label}.md"

    # Construction du document Markdown
    md_lines: list[str] = [
        f"# Rapport de Performance {period_title} — {curr_label}",
        "",
        f"- **Période observée :** du {curr_start} au {curr_end}",
        f"- **Généré le :** {now_alg} (fuseau : {config.timezones.display})",
        f"- **Seuil de significativité statistique :** {min_required} trades",
        "",
        "---",
        "",
        "## 1. Statut de Significativité Statistique",
        "",
    ]

    if not curr_trades:
        md_lines.extend([
            "> [!NOTE]",
            f"> Aucun trade enregistré sur la période du {curr_start} au {curr_end}.",
            "",
        ])
    elif not curr_stats.sample_sufficient:
        md_lines.extend([
            "> [!WARNING]",
            f"> **Échantillon statistique insuffisant :** {len(curr_trades)}/{min_required} "
            "trades enregistrés.",
            "> Les statistiques et pourcentages ci-dessous sont descriptifs et ne constituent "
            "pas une espérance statistiquement robuste.",
            "",
        ])
    else:
        md_lines.extend([
            "> [!NOTE]",
            f"> **Échantillon suffisant :** {len(curr_trades)} trades enregistrés "
            f"(>= seuil de validation {min_required}).",
            "",
        ])

    md_lines.extend([
        "## 2. Métriques Clés de Performance",
        "",
        "| Métrique | Valeur Observée | Intervalle de Confiance (95 %) |",
        "| :--- | :---: | :---: |",
    ])

    if curr_trades:
        n_t = curr_stats.n_trades
        n_w = curr_stats.n_wins
        n_l = curr_stats.n_losses
        n_be = curr_stats.n_breakeven

        if curr_stats.win_rate is not None:
            wr_pct = f"{curr_stats.win_rate * 100:.1f} %"
            ci_low = (curr_stats.win_rate_ci_low or 0.0) * 100
            ci_high = (curr_stats.win_rate_ci_high or 0.0) * 100
            wr_ci = f"[{ci_low:.1f} %, {ci_high:.1f} %] (Wilson)"
        else:
            wr_pct, wr_ci = "N/A", "N/A"

        if curr_stats.expectancy_r is not None:
            exp_str = f"{curr_stats.expectancy_r:+.4f}R"
            exp_ci = (
                f"[{curr_stats.expectancy_ci_low:+.4f}R, {curr_stats.expectancy_ci_high:+.4f}R]"
            )
        else:
            exp_str = f"{curr_r_mean:+.4f}R (moyen)"
            exp_ci = "Non calculé (n < seuil)"

        pf_str = (
            f"{curr_stats.profit_factor:.2f}"
            if curr_stats.profit_factor is not None
            else "N/A"
        )
        comp_str = (
            f"{curr_stats.compliance_rate * 100:.1f} %"
            if curr_stats.compliance_rate is not None
            else "N/A"
        )

        md_lines.append(
            f"| **Nombre de trades** | {n_t} (Wins: {n_w}, Losses: {n_l}, BE: {n_be}) | Exact |"
        )
        md_lines.append(f"| **Taux de réussite** | {wr_pct} | {wr_ci} |")
        md_lines.append(f"| **R cumulé** | {curr_r_total:+.4f}R | Somme réalisée |")
        md_lines.append(f"| **R moyen / trade (Espérance)** | {exp_str} | {exp_ci} |")
        md_lines.append(f"| **Facteur de profit** | {pf_str} | Gains bruts / Pertes brutes |")
        md_lines.append(
            f"| **Drawdown maximum en R** | -{curr_stats.max_drawdown_r:.3f}R | Équité cumulée |"
        )
        md_lines.append(
            f"| **Série de pertes max** | {curr_stats.max_loss_streak} trade(s) | Consécutifs |"
        )
        md_lines.append(
            f"| **Taux de conformité aux règles** | {comp_str} | "
            f"{curr_stats.n_compliant}/{n_t} conformes |"
        )
    else:
        md_lines.append("| **Nombre de trades** | 0 | Exact |")
        md_lines.append("| **Taux de réussite** | N/A | N/A |")
        md_lines.append("| **R cumulé** | 0.0000R | Somme réalisée |")
        md_lines.append("| **R moyen / trade** | N/A | N/A |")
        md_lines.append("| **Facteur de profit** | N/A | N/A |")
        md_lines.append("| **Taux de conformité** | N/A | N/A |")

    md_lines.extend([
        "",
        "---",
        "",
        "## 3. Discipline & Violations de Règles",
        "",
    ])

    if total_violations == 0:
        md_lines.append("✅ **Aucune violation de règle détectée** sur la période étudiée.")
    else:
        md_lines.append(
            f"⚠️ **{total_violations} violation(s) détectée(s)** sur les trades de la période :"
        )
        md_lines.append("")
        md_lines.append("| Type de violation | Nombre d'occurrences |")
        md_lines.append("| :--- | :---: |")
        for v_name, count in sorted(violations_count.items(), key=lambda x: -x[1]):
            md_lines.append(f"| `{v_name}` | {count} |")

    md_lines.extend([
        "",
        "---",
        "",
        f"## 4. Comparaison avec la Période Précédente ({prev_label})",
        "",
    ])

    if prev_stats is not None and prev_trades:
        prev_r_total = round(sum(t.r_realized for t in prev_trades), 4)
        prev_r_mean = round(prev_r_total / len(prev_trades), 4)

        md_lines.extend([
            f"| Métrique | Période Précédente ({prev_label}) | "
            f"Période Courante ({curr_label}) | Évolution |",
            "| :--- | :---: | :---: | :---: |",
        ])

        diff_n = len(curr_trades) - len(prev_trades)
        md_lines.append(
            f"| **Trades exécutés** | {len(prev_trades)} | {len(curr_trades)} | {diff_n:+d} |"
        )

        p_wr = (
            f"{prev_stats.win_rate * 100:.1f} %"
            if prev_stats.win_rate is not None
            else "N/A"
        )
        c_wr = (
            f"{curr_stats.win_rate * 100:.1f} %"
            if curr_stats.win_rate is not None
            else "N/A"
        )
        if prev_stats.win_rate is not None and curr_stats.win_rate is not None:
            d_wr = f"{(curr_stats.win_rate - prev_stats.win_rate) * 100:+.1f} pts"
        else:
            d_wr = "N/A"
        md_lines.append(f"| **Taux de réussite** | {p_wr} | {c_wr} | {d_wr} |")

        diff_r = curr_r_total - prev_r_total
        md_lines.append(
            f"| **R cumulé** | {prev_r_total:+.4f}R | {curr_r_total:+.4f}R | {diff_r:+.4f}R |"
        )

        diff_rm = curr_r_mean - prev_r_mean
        md_lines.append(
            f"| **R moyen / trade** | {prev_r_mean:+.4f}R | {curr_r_mean:+.4f}R | {diff_rm:+.4f}R |"
        )

        p_cmp = (
            f"{prev_stats.compliance_rate * 100:.1f} %"
            if prev_stats.compliance_rate is not None
            else "N/A"
        )
        c_cmp = (
            f"{curr_stats.compliance_rate * 100:.1f} %"
            if curr_stats.compliance_rate is not None
            else "N/A"
        )
        if prev_stats.compliance_rate is not None and curr_stats.compliance_rate is not None:
            d_cmp = f"{(curr_stats.compliance_rate - prev_stats.compliance_rate) * 100:+.1f} pts"
        else:
            d_cmp = "N/A"
        md_lines.append(f"| **Conformité aux règles** | {p_cmp} | {c_cmp} | {d_cmp} |")
    else:
        md_lines.append(
            f"ℹ️ **Aucune donnée disponible pour la période précédente ({prev_label})** "
            "— comparaison non applicable."
        )

    # Patterns de tilt détectés sur la période
    tilt_alerts = detect_period_tilt_alerts(curr_trades, config)
    md_lines.extend([
        "",
        "---",
        "",
        "## 5. Patterns de Tilt Détectés",
        "",
    ])
    if not tilt_alerts:
        md_lines.append("✅ **Aucun pattern de tilt détecté** sur la période étudiée.")
    else:
        md_lines.append(
            f"⚠️ **{len(tilt_alerts)} pattern(s) de tilt détecté(s)** sur les trades de la période :"
        )
        md_lines.append("")
        md_lines.append("| Séance | Type de pattern | Constat factuel | Trades impliqués |")
        md_lines.append("| :---: | :--- | :--- | :--- |")
        for alert in tilt_alerts:
            t_str = ", ".join(alert.trades_involved) if alert.trades_involved else "—"
            md_lines.append(
                f"| {alert.session_date} | `{alert.pattern_type}` | {alert.reason} | {t_str} |"
            )

    if curr_trades:
        md_lines.extend([
            "",
            "---",
            "",
            "## 6. Détail des Trades de la Période",
            "",
            "| Date | Instrument | Direction | Entrée | Sortie | Résultat (R) | Issue | Setup |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ])
        for t in curr_trades:
            md_lines.append(
                f"| {t.session_date} | {t.instrument} | {t.direction.value} | "
                f"{t.entry_price:.2f} | {t.exit_price:.2f} | {t.r_realized:+.2f}R | "
                f"{t.outcome.value} | {t.setup_tag or '—'} |"
            )

    md_content = "\n".join(md_lines) + "\n"

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    report_file = (target_dir / filename).resolve()
    report_file.write_text(md_content, encoding="utf-8")
    logger.info("Rapport de journal sauvegardé : %s", report_file)

    return PeriodReportResult(
        period=period,
        period_label=curr_label,
        start_date=curr_start,
        end_date=curr_end,
        report_path=report_file,
        markdown_content=md_content,
        n_trades=len(curr_trades),
        r_total=curr_r_total,
        sample_sufficient=curr_stats.sample_sufficient,
        has_prev_data=prev_stats is not None,
    )


def run_period_report_cli(
    conn: sqlite3.Connection,
    period: str,
    date_str: Optional[str] = None,
    output_dir: str | Path = "reports/journal",
    config: Optional[AppConfig] = None,
) -> PeriodReportResult:
    """Point d'entrée pour la commande CLI nqcockpit journal report."""
    if config is None:
        config = load_config()

    ref_date: Optional[date] = None
    if date_str:
        ref_date = date.fromisoformat(date_str)

    trades = load_trades(conn)
    return generate_period_report(
        trades=trades,
        period=period,
        ref_date=ref_date,
        output_dir=output_dir,
        config=config,
    )
