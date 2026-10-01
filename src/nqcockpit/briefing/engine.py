"""Moteur d'agrégation et de génération du Briefing pré-séance (P12).

Consomme uniquement les objets validés produits par les moteurs existants :
- Levels (P02/P04)
- Event Risk / Radar (P03)
- Playbook (P06)
- Macro / Forecast (P07)
- Profile (P08)

Aucun chiffre n'est inventé ou recalculé.
Les statuts DÉGRADÉ sont propagés de manière explicite.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig, load_config
from nqcockpit.events.models import EventRiskReport
from nqcockpit.events.risk import compute_event_risk
from nqcockpit.forecast.engine import AmplitudeForecast, compute_amplitude_forecast
from nqcockpit.levels.engine import LevelsEngine, LevelsSnapshot
from nqcockpit.playbook.card import EventPlaybookCard, generate_card
from nqcockpit.profile.engine import DayProfile, build_day_profile
from nqcockpit.briefing.gemini_client import generate_gemini_summary
from nqcockpit.briefing.models import (
    GeminiResult,
    PreSessionBriefing,
    TelegramResult,
)
from nqcockpit.briefing.telegram_client import send_telegram_message

logger = logging.getLogger(__name__)


def _extract_numbers_from_obj(obj: Any, num_set: set[float | int | str]) -> None:
    """Parcourt récursivement un objet/dict/dataclass et extrait tous les nombres."""
    if obj is None:
        return
    if isinstance(obj, (int, float)):
        num_set.add(obj)
        num_set.add(str(obj))
        if isinstance(obj, float):
            num_set.add(f"{obj:.1f}")
            num_set.add(f"{obj:.2f}")
            num_set.add(f"{obj:.4f}")
            num_set.add(f"{obj * 100:.1f}")
            num_set.add(f"{obj * 100:.1f}%")
            num_set.add(f"{int(obj)}")
        return
    if isinstance(obj, str):
        # Extrait les sous-chaînes numériques
        matches = re.findall(r"\b\d+(?:\.\d+)?%?\b", obj)
        for m in matches:
            clean = m.rstrip("%")
            num_set.add(m)
            num_set.add(clean)
            try:
                val = float(clean)
                num_set.add(val)
                num_set.add(f"{val:.1f}")
                num_set.add(f"{val:.2f}")
                num_set.add(int(val))
            except ValueError:
                pass
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _extract_numbers_from_obj(v, num_set)
        return
    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            _extract_numbers_from_obj(item, num_set)
        return

    # Si c'est un dataclass ou un objet avec __dict__ ou _asdict
    if hasattr(obj, "__dict__"):
        for k, v in obj.__dict__.items():
            if not k.startswith("_"):
                _extract_numbers_from_obj(v, num_set)
    elif hasattr(obj, "_asdict"):
        for k, v in obj._asdict().items():
            _extract_numbers_from_obj(v, num_set)


def extract_source_numbers(sources: dict[str, Any]) -> set[float | int | str]:
    """Extrait l'ensemble des nombres présents dans l'ensemble des objets sources."""
    num_set: set[float | int | str] = set()

    # Nombres standards autorisés (structure, indices, pourcentages d'en-tête)
    for n in range(0, 101):
        num_set.add(n)
        num_set.add(float(n))
        num_set.add(str(n))
        num_set.add(f"{n}.0")
        num_set.add(f"{n}%")

    _extract_numbers_from_obj(sources, num_set)

    return num_set


def validate_anti_hallucination(
    generated_text: str, source_numbers: set[float | int | str]
) -> tuple[bool, str | None]:
    """Vérifie qu'aucun nombre non présent dans les données sources ne figure dans le texte généré.

    Returns:
        (True, None) si valide, (False, warning_msg) en cas d'hallucination.
    """
    # Regex d'extraction des nombres (ex: 20850.5, 68.3%, 1.5, 100)
    raw_matches = re.findall(r"\b\d+(?:\.\d+)?%?\b", generated_text)

    for match in raw_matches:
        clean_num = match.rstrip("%")
        # Si la chaîne brute ou nettoyée est dans l'ensemble source, c'est valide
        if match in source_numbers or clean_num in source_numbers:
            continue

        try:
            val = float(clean_num)
            # Vérification de tolérance flottante
            matched = False
            for src_val in source_numbers:
                if isinstance(src_val, (int, float)):
                    if abs(src_val - val) < 1e-3:
                        matched = True
                        break
            if matched:
                continue
        except ValueError:
            pass

        # Si le nombre n'a pas été trouvé dans les sources
        return (
            False,
            f"Nombre non reconnu dans les données sources : '{match}'",
        )

    return True, None


def build_fallback_briefing_markdown(
    levels_snap: Optional[LevelsSnapshot],
    risk_assess: Optional[EventRiskReport],
    playbook_card: Optional[EventPlaybookCard],
    forecast: Optional[AmplitudeForecast],
    profile: Optional[DayProfile],
    now_utc: datetime,
    config: AppConfig,
) -> str:
    """Génère le briefing de pré-séance en Markdown déterministe (fallback texte brut sans Gemini)."""
    tz_alg = ZoneInfo(config.timezones.display)
    tz_ny = ZoneInfo(config.timezones.market)

    now_alg_str = now_utc.astimezone(tz_alg).strftime("%Y-%m-%d %H:%M:%S")
    now_ny_str = now_utc.astimezone(tz_ny).strftime("%Y-%m-%d %H:%M:%S")
    session_date = now_utc.astimezone(tz_ny).date().isoformat()

    # Évaluation du statut global
    warnings: list[str] = []
    if levels_snap and levels_snap.status.value != "OK":
        warnings.append(f"Levels : {levels_snap.status.value}")
    if risk_assess and risk_assess.risk_level in ("RED", "ROUGE"):
        warnings.append("Événement Tier 1 imminent ou en cours (Statut ROUGE)")

    global_status_str = "DÉGRADÉ (" + ", ".join(warnings) + ")" if warnings else "OK"

    lines: list[str] = [
        f"# Briefing Pré-Séance NQ — {session_date}",
        "",
        f"- **Horodatage d'émission (Alger) :** {now_alg_str}",
        f"- **Horodatage marché (New York) :** {now_ny_str}",
        f"- **Statut d'intégrité global :** `{global_status_str}`",
        "",
        "---",
        "",
        "## 1. Profil de Séance & Scénarios Conditionnels (P08)",
        "",
    ]

    if profile:
        lines.append(f"- **Type de Profil Identifié :** `{profile.probable_day_type}`")
        lines.append(f"- **Régime Volatilité :** `{profile.volatility_regime}`")
        lines.append(f"- **Régime Gamma :** `{profile.gamma_regime}`")
        lines.append("")
        lines.append("### Scénarios Conditionnels :")
        for sc in profile.scenarios:
            lines.append(
                f"- **[{sc.level_name} @ {sc.level_price:.2f}]** ({sc.level_type}) :"
            )
            if sc.if_condition:
                lines.append(f"  - *Condition :* {sc.if_condition}")
            if sc.then_plan:
                lines.append(f"  - *Plan :* {sc.then_plan}")
    else:
        lines.append("> [!WARNING]")
        lines.append("> Profil de séance non disponible (Statut DÉGRADÉ).")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Niveaux Gamma & Expected Move NQ (P02/P04)",
        "",
    ])

    if levels_snap:
        g_flip = f"{levels_snap.gamma_flip_nq:.2f}" if levels_snap.gamma_flip_nq is not None else "Inconnu"
        c_wall = f"{levels_snap.call_wall_nq:.2f}" if levels_snap.call_wall_nq is not None else "Inconnu"
        p_wall = f"{levels_snap.put_wall_nq:.2f}" if levels_snap.put_wall_nq is not None else "Inconnu"

        em_val = None
        em_lower = None
        em_upper = None
        if levels_snap.expected_move:
            em_val = levels_snap.expected_move.straddle_move_nq or levels_snap.expected_move.formula_move
            em_lower = levels_snap.expected_move.lower_bound_nq
            em_upper = levels_snap.expected_move.upper_bound_nq

        em_pts = f"{em_val:.2f}" if em_val is not None else "N/A"

        lines.append(f"- **Gamma Flip NQ :** `{g_flip}`")
        lines.append(f"- **Call Wall NQ (Résistance Opérative) :** `{c_wall}`")
        lines.append(f"- **Put Wall NQ (Support Opératif) :** `{p_wall}`")
        lines.append(f"- **Expected Move Journalier :** `±{em_pts} points`")
        if em_lower is not None and em_upper is not None:
            lines.append(
                f"- **Bande Expected Move NQ :** `[{em_lower:.2f}, {em_upper:.2f}]`"
            )
    else:
        lines.append("> [!WARNING]")
        lines.append("> Niveaux de positionnement optionnel non disponibles (Statut DÉGRADÉ).")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Radar d'Événements Macro & Risque (P03)",
        "",
    ])

    if risk_assess:
        lines.append(f"- **Niveau de Risque Événementiel :** `{risk_assess.risk_level}`")
        if risk_assess.reason:
            lines.append(f"- **Constat Factuel :** {risk_assess.reason}")
        if risk_assess.next_event_countdown:
            lines.append(f"- **Prochain Événement :** {risk_assess.next_event_countdown}")
    else:
        lines.append("> [!WARNING]")
        lines.append("> Évaluation des risques événementiels non disponible (Statut DÉGRADÉ).")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Playbook Événementiel & Repères (P06)",
        "",
    ])

    if playbook_card and playbook_card.event_name != "Aucun":
        lines.append(f"- **Événement Repère :** `{playbook_card.event_name}`")
        lines.append(f"- **Statut du Champ :** `{playbook_card.field_status}`")
        if playbook_card.scenarios:
            lines.append("- **Scénarios de Réaction Événementielle :**")
            for p_sc in playbook_card.scenarios:
                lines.append(f"  - `{p_sc.name}` : {p_sc.if_condition} -> {p_sc.then_outcome}")
    else:
        lines.append("Aucun événement majeur nécessitant une fiche de playbook spécifique sur la séance.")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Prévisions d'Amplitude & Contexte Macro (P07)",
        "",
    ])

    if forecast:
        lines.append(f"- **État de Calibration :** `{forecast.calibration_status}`")
        if forecast.range_low is not None and forecast.range_high is not None:
            lines.append(
                f"- **Amplitude Prévue (1-Sigma) :** `[{forecast.range_low:.1f}, {forecast.range_high:.1f}] points`"
            )
        if forecast.day_type_probabilities:
            lines.append("- **Probabilités par Type de Journée :**")
            for dtp in forecast.day_type_probabilities:
                lines.append(f"  - `{dtp.day_type}` : `{dtp.probability_pct:.1f} %`")
    else:
        lines.append("> [!WARNING]")
        lines.append("> Prévision d'amplitude non disponible (Statut DÉGRADÉ).")

    lines.extend([
        "",
        "---",
        "",
        "## 6. Drapeaux No-Trade & Alertes (P05/P08)",
        "",
    ])

    if profile and profile.no_trade and profile.no_trade.all_flags:
        active_flags = [f for f in profile.no_trade.all_flags if f.triggered]
        if active_flags:
            lines.append("⚠️ **Drapeaux No-Trade Actifs :**")
            for flag in active_flags:
                code_str = flag.code.value if hasattr(flag.code, "value") else str(flag.code)
                lines.append(f"- `{code_str}` (Sévérité : {flag.severity}) : {flag.reason}")
        else:
            lines.append("✅ **Aucun drapeau No-Trade actif.** Trading autorisé sous réserve de validation de la checklist pré-trade P09.")
    else:
        lines.append("✅ **Aucun drapeau No-Trade actif.** Trading autorisé sous réserve de validation de la checklist pré-trade P09.")

    lines.extend([
        "",
        "---",
        "",
        "## 7. Anti-Biais & Responsabilité",
        "",
        "> [!IMPORTANT]",
        "> Ce briefing est un outil d'aide à la décision factuel, déterministe et non directionnel.",
        "> Il ne constitue en aucun cas un conseil en investissement ou un signal de trading.",
        "> L'exécution des trades reste sous la responsabilité exclusive de l'opérateur et doit respecter la checklist pré-trade P09.",
        "",
    ])

    return "\n".join(lines)


def generate_briefing(
    now_utc: Optional[datetime] = None,
    config: Optional[AppConfig] = None,
    levels_snap: Optional[LevelsSnapshot] = None,
    risk_assess: Optional[EventRiskReport] = None,
    playbook_card: Optional[EventPlaybookCard] = None,
    forecast: Optional[AmplitudeForecast] = None,
    profile: Optional[DayProfile] = None,
    use_gemini: bool = True,
    use_telegram: bool = True,
    dry_run: bool = False,
    output_dir: str | Path = "reports/briefings",
) -> PreSessionBriefing:
    """Consolide et génère le briefing pré-séance avec validation et diffusion optionnelle.

    Args:
        now_utc: Instant de référence (défaut : datetime.now(timezone.utc)).
        config: Configuration globale (défaut : load_config()).
        levels_snap: Snapshot des niveaux gamma (calculé si None).
        risk_assess: Évaluation des risques événementiels (calculée si None).
        playbook_card: Fiche de playbook (calculée si None).
        forecast: Prévisions d'amplitude (calculée si None).
        profile: Profil de séance P08 (calculé si None).
        use_gemini: Si True, tente d'utiliser l'agent rédactionnel Gemini.
        use_telegram: Si True, tente de diffuser le résultat sur Telegram.
        dry_run: Si True, simule les opérations sans envoi réseau.
        output_dir: Dossier de destination pour l'export Markdown.

    Returns:
        PreSessionBriefing contenant l'ensemble des objets et le texte final.
    """
    if config is None:
        config = load_config()

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    tz_alg = ZoneInfo(config.timezones.display)
    tz_ny = ZoneInfo(config.timezones.market)

    session_date_ny = now_utc.astimezone(tz_ny).date().isoformat()
    timestamp_alg_str = now_utc.astimezone(tz_alg).strftime("%Y-%m-%d %H:%M:%S")

    status_warnings: list[str] = []

    # 1. Résolution des moteurs sources (sans duplication)
    if profile is None:
        try:
            profile = build_day_profile(config=config, now_utc=now_utc)
        except Exception as e:
            logger.warning("Échec de construction du profil de séance : %s", e)
            status_warnings.append(f"DayProfile indisponible ({e})")

    if levels_snap is None and profile and hasattr(profile, "levels_snapshot"):
        levels_snap = profile.levels_snapshot

    if risk_assess is None:
        try:
            from nqcockpit.events.radar import fetch_event_radar
            risk_assess = fetch_event_radar(config=config, ref_utc=now_utc)
        except Exception as e:
            logger.warning("Échec du radar d'événements : %s", e)
            status_warnings.append(f"EventRisk indisponible ({e})")

    # Vérification des statuts d'intégrité
    if levels_snap and hasattr(levels_snap, "status") and levels_snap.status.value != "OK":
        status_warnings.append(f"Niveaux gamma en statut {levels_snap.status.value}")

    overall_status = "DÉGRADÉ" if status_warnings else "OK"

    # 2. Construction du fallback Markdown déterministe
    fallback_markdown = build_fallback_briefing_markdown(
        levels_snap=levels_snap,
        risk_assess=risk_assess,
        playbook_card=playbook_card,
        forecast=forecast,
        profile=profile,
        now_utc=now_utc,
        config=config,
    )

    # 3. Extraction des nombres sources pour la validation anti-hallucination
    source_objects = {
        "levels": levels_snap,
        "risk": risk_assess,
        "playbook": playbook_card,
        "forecast": forecast,
        "profile": profile,
        "metadata": {
            "session_date": session_date_ny,
            "timestamp_alg": timestamp_alg_str,
            "min_sessions": config.validation.min_sessions,
            "max_trades": config.rules.max_trades_per_day,
            "daily_loss_limit_r": config.rules.daily_loss_limit_r,
        },
    }
    source_numbers = extract_source_numbers(source_objects)

    # 4. Agent Rédactionnel Gemini (Optionnel)
    gemini_result: Optional[GeminiResult] = None
    final_markdown = fallback_markdown
    is_gemini_used = False

    if use_gemini:
        gemini_result = generate_gemini_summary(
            structured_data=source_objects,
            source_numbers=source_numbers,
            validator_func=validate_anti_hallucination,
            config=config,
        )
        if gemini_result.is_success and gemini_result.content:
            final_markdown = gemini_result.content
            is_gemini_used = True
        elif gemini_result.warning:
            status_warnings.append(gemini_result.warning)

    # 5. Transmission Telegram (Optionnelle)
    telegram_result: Optional[TelegramResult] = None
    if use_telegram:
        telegram_result = send_telegram_message(
            message_text=final_markdown,
            dry_run=dry_run,
        )
        if telegram_result.error:
            status_warnings.append(telegram_result.error)

    # Mettre à jour le statut global final
    if status_warnings and overall_status == "OK":
        overall_status = "DÉGRADÉ"

    # 6. Écriture du fichier Markdown
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = (out_dir / f"briefing_{session_date_ny}.md").resolve()
    out_file.write_text(final_markdown, encoding="utf-8")
    logger.info("Fichier de briefing pré-séance sauvegardé : %s", out_file)

    return PreSessionBriefing(
        timestamp_utc=now_utc,
        session_date_ny=session_date_ny,
        timestamp_algiers_str=timestamp_alg_str,
        status=overall_status,
        status_warnings=status_warnings,
        levels_snapshot=levels_snap,
        risk_assessment=risk_assess,
        playbook_card=playbook_card,
        forecast=forecast,
        profile=profile,
        markdown_briefing=final_markdown,
        is_gemini_used=is_gemini_used,
        gemini_result=gemini_result,
        telegram_result=telegram_result,
        output_path=out_file,
    )
