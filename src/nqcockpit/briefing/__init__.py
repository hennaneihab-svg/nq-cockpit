"""Package Briefing du Matin & Alertes (P12)."""

from __future__ import annotations

from nqcockpit.briefing.engine import generate_briefing
from nqcockpit.briefing.models import GeminiResult, PreSessionBriefing, TelegramResult

__all__ = [
    "GeminiResult",
    "PreSessionBriefing",
    "TelegramResult",
    "generate_briefing",
]
