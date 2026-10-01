"""Modèles de données pour le module Briefing (P12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from nqcockpit.events.models import EventRiskReport
from nqcockpit.forecast.engine import AmplitudeForecast
from nqcockpit.levels.engine import LevelsSnapshot
from nqcockpit.playbook.card import EventPlaybookCard
from nqcockpit.profile.engine import DayProfile


@dataclass(frozen=True)
class GeminiResult:
    """Résultat du traitement par l'agent rédactionnel Gemini."""

    status: str  # "OK", "DISABLED", "REJECTED_HALLUCINATION", "FAILED"
    content: Optional[str] = None
    warning: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status == "OK" and self.content is not None


@dataclass(frozen=True)
class TelegramResult:
    """Résultat de la diffusion Telegram."""

    status: str  # "OK", "DISABLED", "DRY_RUN", "FAILED"
    sent: bool = False
    message: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PreSessionBriefing:
    """Briefing pré-séance agrégé et validé."""

    timestamp_utc: datetime
    session_date_ny: str
    timestamp_algiers_str: str
    status: str  # "OK" ou "DÉGRADÉ"
    status_warnings: list[str] = field(default_factory=list)
    levels_snapshot: Optional[LevelsSnapshot] = None
    risk_assessment: Optional[EventRiskReport] = None
    playbook_card: Optional[EventPlaybookCard] = None
    forecast: Optional[AmplitudeForecast] = None
    profile: Optional[DayProfile] = None
    markdown_briefing: str = ""
    is_gemini_used: bool = False
    gemini_result: Optional[GeminiResult] = None
    telegram_result: Optional[TelegramResult] = None
    output_path: Optional[Path] = None
