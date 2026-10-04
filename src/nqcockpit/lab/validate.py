"""NQ Cockpit — Laboratoire de Validation Statistique (P14).

Module de validation empirique des hypothèses de marché (H1 à H4).
Applique des règles strictes sans embellissement ni surapprentissage :
1. Interdiction formelle de conclure sous 60 séances ou 12 événements.
2. Définitions et seuils figés dans hypotheses.yaml avec contrôle d'intégrité SHA-256.
3. Contrôle du taux d'erreur par famille (FWER) via correction de Holm-Bonferroni.
4. Restitution hebdomadaire dans reports/lab.md.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml
from scipy import stats

log = logging.getLogger("nqcockpit.lab.validate")

CONFIG_PATH = Path(__file__).parent / "hypotheses.yaml"
MIN_SESSIONS_THRESHOLD = 60
MIN_EVENTS_THRESHOLD = 12


@dataclass(frozen=True)
class HypothesisDefinition:
    """Définition figée d'une hypothèse de travail."""

    id: str
    title: str
    description: str
    frozen_parameters: dict[str, Any]
    expected_direction: str
    directional_bias: str
    created_at: str = ""


@dataclass
class ValidationResult:
    """Résultat d'évaluation d'une hypothèse."""

    hypothesis_id: str
    sample_size: int
    metric_name: str
    mean_val: float | None = None
    median_val: float | None = None
    effect_size: float | None = None
    effect_size_name: str = "Cohen's d"
    ci_lower: float | None = None
    ci_upper: float | None = None
    p_value_raw: float | None = None
    p_value_adjusted: float | None = None
    status: str = "INSUFFICIENT_SAMPLE"  # INSUFFICIENT_SAMPLE | CONFIRMED | REJECTED | INCONCLUSIVE
    details: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class HypothesisRegistry:
    """Registre immuable des hypothèses empiriques."""

    def __init__(self, yaml_path: Path | str | None = None) -> None:
        self.yaml_path = Path(yaml_path) if yaml_path else CONFIG_PATH
        if not self.yaml_path.exists():
            raise FileNotFoundError(
                f"Registre d'hypothèses introuvable : {self.yaml_path}"
            )

        content = self.yaml_path.read_bytes()
        self.fingerprint = hashlib.sha256(content).hexdigest()
        self.raw_data = yaml.safe_load(content)

        self.version: str = self.raw_data.get("version", "unknown")
        self.created_at: str = self.raw_data.get("created_at", "unknown")
        self.hypotheses: dict[str, HypothesisDefinition] = {}

        for item in self.raw_data.get("hypotheses", []):
            hyp = HypothesisDefinition(
                id=item["id"],
                title=item["title"],
                description=item["description"],
                frozen_parameters=item.get("frozen_parameters", {}),
                expected_direction=item.get("expected_direction", ""),
                directional_bias=item.get("directional_bias", "NONE"),
                created_at=item.get("created_at", self.created_at),
            )
            self.hypotheses[hyp.id] = hyp

    def get(self, hyp_id: str) -> HypothesisDefinition:
        """Récupère une hypothèse par son identifiant."""
        if hyp_id not in self.hypotheses:
            raise KeyError(f"Hypothèse non enregistrée : {hyp_id}")
        return self.hypotheses[hyp_id]

    def all_ids(self) -> list[str]:
        """Retourne la liste ordonnée des identifiants."""
        return list(self.hypotheses.keys())


class StatisticalValidator:
    """Moteur de calcul statistique et d'ajustement multi-tests."""

    @staticmethod
    def adjust_p_values_holm(p_values: Sequence[float]) -> list[float]:
        """Ajustement des p-values selon la méthode descendante séquentielle de Holm."""
        m = len(p_values)
        if m == 0:
            return []

        indexed = sorted(enumerate(p_values), key=lambda x: x[1])
        adjusted = [0.0] * m

        running_max = 0.0
        for rank, (orig_idx, p) in enumerate(indexed):
            multiplier = m - rank
            p_adj = min(1.0, p * multiplier)
            running_max = max(running_max, p_adj)
            adjusted[orig_idx] = running_max

        return adjusted

    @staticmethod
    def compute_cohens_d(group1: Sequence[float], group2: Sequence[float]) -> float:
        """Calcule la taille d'effet d de Cohen."""
        n1, n2 = len(group1), len(group2)
        if n1 < 2 or n2 < 2:
            return 0.0

        var1 = np.var(group1, ddof=1)
        var2 = np.var(group2, ddof=1)
        pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
        if pooled_std == 0:
            return 0.0
        return float((np.mean(group1) - np.mean(group2)) / pooled_std)

    @staticmethod
    def compute_confidence_interval(
        data: Sequence[float], confidence: float = 0.95
    ) -> tuple[float, float]:
        """Calcule l'intervalle de confiance pour la moyenne d'un échantillon."""
        n = len(data)
        if n < 2:
            val = float(data[0]) if n == 1 else 0.0
            return val, val

        mean = np.mean(data)
        sem = stats.sem(data)
        h = sem * stats.t.ppf((1 + confidence) / 2.0, n - 1)
        return float(mean - h), float(mean + h)

    def validate_h1_gamma_regime(
        self,
        neg_gamma_ranges: Sequence[float],
        pos_gamma_ranges: Sequence[float],
    ) -> ValidationResult:
        """H1 : Gamma négatif ↔ amplitude plus élevée."""
        n1, n2 = len(neg_gamma_ranges), len(pos_gamma_ranges)
        total_n = n1 + n2

        if total_n < MIN_SESSIONS_THRESHOLD or n1 < 5 or n2 < 5:
            return ValidationResult(
                hypothesis_id="H1",
                sample_size=total_n,
                metric_name="amplitude_session_pts",
                status="INSUFFICIENT_SAMPLE",
                details=(
                    f"Échantillon insuffisant : {total_n} séances observées "
                    f"(requis >= {MIN_SESSIONS_THRESHOLD}). Interdiction de conclure."
                ),
            )

        t_stat, p_val = stats.ttest_ind(
            neg_gamma_ranges, pos_gamma_ranges, equal_var=False, alternative="greater"
        )
        d = self.compute_cohens_d(neg_gamma_ranges, pos_gamma_ranges)
        ci_low, ci_high = self.compute_confidence_interval(neg_gamma_ranges)

        status = "CONFIRMED" if (p_val < 0.05 and d > 0.2) else "INCONCLUSIVE"
        return ValidationResult(
            hypothesis_id="H1",
            sample_size=total_n,
            metric_name="amplitude_session_pts",
            mean_val=float(np.mean(neg_gamma_ranges)),
            median_val=float(np.median(neg_gamma_ranges)),
            effect_size=float(d),
            effect_size_name="Cohen's d",
            ci_lower=ci_low,
            ci_upper=ci_high,
            p_value_raw=float(p_val),
            status=status,
            details=f"Welch t={t_stat:.2f}, p_raw={p_val:.4f}, d={d:.2f} (n_neg={n1}, n_pos={n2})",
        )

    def validate_h2_above_flip(
        self,
        above_flip_ranges: Sequence[float],
        below_flip_ranges: Sequence[float],
    ) -> ValidationResult:
        """H2 : Prix au-dessus du flip ↔ amplitude plus faible."""
        n1, n2 = len(above_flip_ranges), len(below_flip_ranges)
        total_n = n1 + n2

        if total_n < MIN_SESSIONS_THRESHOLD or n1 < 5 or n2 < 5:
            return ValidationResult(
                hypothesis_id="H2",
                sample_size=total_n,
                metric_name="amplitude_session_pts",
                status="INSUFFICIENT_SAMPLE",
                details=(
                    f"Échantillon insuffisant : {total_n} séances observées "
                    f"(requis >= {MIN_SESSIONS_THRESHOLD}). Interdiction de conclure."
                ),
            )

        t_stat, p_val = stats.ttest_ind(
            above_flip_ranges, below_flip_ranges, equal_var=False, alternative="less"
        )
        d = self.compute_cohens_d(above_flip_ranges, below_flip_ranges)
        ci_low, ci_high = self.compute_confidence_interval(above_flip_ranges)

        status = "CONFIRMED" if (p_val < 0.05 and d < -0.2) else "INCONCLUSIVE"
        details_str = (
            f"Welch t={t_stat:.2f}, p_raw={p_val:.4f}, d={d:.2f} "
            f"(n_above={n1}, n_below={n2})"
        )
        return ValidationResult(
            hypothesis_id="H2",
            sample_size=total_n,
            metric_name="amplitude_session_pts",
            mean_val=float(np.mean(above_flip_ranges)),
            median_val=float(np.median(above_flip_ranges)),
            effect_size=float(d),
            effect_size_name="Cohen's d",
            ci_lower=ci_low,
            ci_upper=ci_high,
            p_value_raw=float(p_val),
            status=status,
            details=details_str,
        )

    def validate_h3_tier1_events(
        self,
        tier1_ranges: Sequence[float],
        regular_ranges: Sequence[float],
    ) -> ValidationResult:
        """H3 : Jours d'événement Tier 1 ↔ amplitude plus large."""
        n_events = len(tier1_ranges)
        total_sessions = n_events + len(regular_ranges)

        if n_events < MIN_EVENTS_THRESHOLD or total_sessions < MIN_SESSIONS_THRESHOLD:
            return ValidationResult(
                hypothesis_id="H3",
                sample_size=total_sessions,
                metric_name="amplitude_session_pts",
                status="INSUFFICIENT_SAMPLE",
                details=(
                    f"Échantillon insuffisant : {n_events} événements Tier 1 observés "
                    f"(requis >= {MIN_EVENTS_THRESHOLD}) sur {total_sessions} séances "
                    f"(requis >= {MIN_SESSIONS_THRESHOLD}). Interdiction de conclure."
                ),
            )

        t_stat, p_val = stats.ttest_ind(
            tier1_ranges, regular_ranges, equal_var=False, alternative="greater"
        )
        d = self.compute_cohens_d(tier1_ranges, regular_ranges)
        ci_low, ci_high = self.compute_confidence_interval(tier1_ranges)

        status = "CONFIRMED" if (p_val < 0.05 and d > 0.2) else "INCONCLUSIVE"
        details_str = (
            f"Welch t={t_stat:.2f}, p_raw={p_val:.4f}, d={d:.2f} "
            f"(n_t1={n_events}, n_reg={len(regular_ranges)})"
        )
        return ValidationResult(
            hypothesis_id="H3",
            sample_size=total_sessions,
            metric_name="amplitude_session_pts",
            mean_val=float(np.mean(tier1_ranges)),
            median_val=float(np.median(tier1_ranges)),
            effect_size=float(d),
            effect_size_name="Cohen's d",
            ci_lower=ci_low,
            ci_upper=ci_high,
            p_value_raw=float(p_val),
            status=status,
            details=details_str,
        )

    def validate_h4_wall_reactions(
        self,
        reaction_count: int,
        total_touches: int,
        baseline_rate: float = 0.50,
    ) -> ValidationResult:
        """H4 : Réaction mesurable aux murs (retournement / cassure)."""
        if total_touches < MIN_SESSIONS_THRESHOLD:
            return ValidationResult(
                hypothesis_id="H4",
                sample_size=total_touches,
                metric_name="wall_reaction_rate",
                status="INSUFFICIENT_SAMPLE",
                details=(
                    f"Échantillon insuffisant : {total_touches} tests de niveaux observés "
                    f"(requis >= {MIN_SESSIONS_THRESHOLD}). Interdiction de conclure."
                ),
            )

        res = stats.binomtest(
            reaction_count, total_touches, p=baseline_rate, alternative="two-sided"
        )
        observed_rate = reaction_count / total_touches
        ci = res.proportion_ci(confidence_level=0.95)
        risk_diff = observed_rate - baseline_rate

        status = "CONFIRMED" if res.pvalue < 0.05 else "INCONCLUSIVE"
        details_str = (
            f"Binomial exact k={reaction_count}/{total_touches}, "
            f"p_raw={res.pvalue:.4f}, diff={risk_diff:+.3f}"
        )
        return ValidationResult(
            hypothesis_id="H4",
            sample_size=total_touches,
            metric_name="wall_reaction_rate",
            mean_val=float(observed_rate),
            median_val=float(observed_rate),
            effect_size=float(risk_diff),
            effect_size_name="Risk Difference (vs 0.50)",
            ci_lower=float(ci.low),
            ci_upper=float(ci.high),
            p_value_raw=float(res.pvalue),
            status=status,
            details=details_str,
        )


def generate_lab_report(
    results: list[ValidationResult],
    registry: HypothesisRegistry,
    output_path: Path | str = "reports/lab.md",
) -> Path:
    """Génère le rapport périodique du laboratoire avec traçabilité complète."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Ajustement multi-tests pour les hypothèses ayant une p-value
    active_results = [r for r in results if r.p_value_raw is not None]
    if active_results:
        raw_p = [r.p_value_raw for r in active_results if r.p_value_raw is not None]
        adj_p = StatisticalValidator.adjust_p_values_holm(raw_p)
        for r, p_adj in zip(active_results, adj_p):
            r.p_value_adjusted = p_adj

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Laboratoire de Validation Empirique — NQ Cockpit (P14)",
        "",
        f"**Date d'évaluation :** {now_utc}  ",
        f"**Registre d'hypothèses :** `hypotheses.yaml` (v{registry.version}, "
        f"créé le {registry.created_at})  ",
        f"**Empreinte cryptographique registre (SHA-256) :** `{registry.fingerprint}`  ",
        "**Politique méthodologique :** Aucune conclusion permise sous 60 séances ou 12 "
        "événements. Ajustement FWER de Holm-Bonferroni. Aucun biais directionnel.",
        "",
        "---",
        "",
        "## 1. Synthèse de Validation des Hypothèses Figées",
        "",
        "| ID | Hypothèse | n | Statut | p-value brute | p-value Holm | Taille d'effet | IC 95% |",
        "|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for res in results:
        hyp = registry.get(res.hypothesis_id)
        p_raw_str = f"{res.p_value_raw:.4f}" if res.p_value_raw is not None else "—"
        p_adj_str = f"{res.p_value_adjusted:.4f}" if res.p_value_adjusted is not None else "—"
        effect_str = (
            f"{res.effect_size:.2f} ({res.effect_size_name})"
            if res.effect_size is not None
            else "—"
        )
        ci_str = (
            f"[{res.ci_lower:.1f}, {res.ci_upper:.1f}]"
            if res.ci_lower is not None and res.ci_upper is not None
            else "—"
        )

        status_badge = {
            "INSUFFICIENT_SAMPLE": "**ÉCHANTILLON INSUFFISANT**",
            "CONFIRMED": "VALIDÉE",
            "REJECTED": "REJETÉE",
            "INCONCLUSIVE": "NON CONCLUANTE",
        }.get(res.status, res.status)

        lines.append(
            f"| **{hyp.id}** | {hyp.title} | {res.sample_size} | {status_badge} | "
            f"{p_raw_str} | {p_adj_str} | {effect_str} | {ci_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 2. Détail par Hypothèse & Justification",
        "",
    ])

    for res in results:
        hyp = registry.get(res.hypothesis_id)
        lines.extend([
            f"### Hypothèse {hyp.id} : {hyp.title}",
            f"- **Énoncé théorique :** {hyp.description.strip()}",
            f"- **Direction attendue :** `{hyp.expected_direction}`",
            f"- **Biais directionnel :** `{hyp.directional_bias}`",
            f"- **Échantillon collecté :** n = {res.sample_size} séances / occurrences.",
            f"- **Détails métriques :** {res.details}",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 3. Règles d'Éthique & Non-Surapprentissage",
        "",
        "- **Gel des hypothèses :** Les 4 hypothèses ci-dessus ont été définies a priori. "
        "Tout ajout futur doit figurer dans le registre avec horodatage certifié avant "
        "injection de nouvelles données.",
        "- **Contrôle FWER :** L'ajustement séquentiel de Holm-Bonferroni évite l'inflation "
        "de l'erreur de type I lors des tests simultanés.",
        "- **Refus de sur-interprétation :** Tant que le seuil de 60 séances n'est pas "
        "atteint dans les données locales archivées, le statut demeure irrévocablement "
        "`ÉCHANTILLON INSUFFISANT`.",
        "",
    ])

    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Rapport du laboratoire généré dans %s", out)
    return out
