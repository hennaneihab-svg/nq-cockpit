"""Module discipline pour NQ Cockpit (P09 réel).

Fournit :
- Machine à états temps réel de la séance (interrogable à tout instant)
- Checklist pré-trade interactive GO / STOP stricte
- Gestionnaire de risque et dimensionnement de position (point_values configurables)
"""

from __future__ import annotations

from nqcockpit.discipline.engine import (
    evaluate_checklist,
    evaluate_session_state,
)
from nqcockpit.discipline.models import (
    ChecklistResult,
    ChecklistVerdict,
    DisciplineSessionState,
    PositionSizingResult,
    PreTradeChecklist,
    SessionDisciplineStatus,
)
from nqcockpit.discipline.risk import compute_position_size

__all__ = [
    "ChecklistResult",
    "ChecklistVerdict",
    "DisciplineSessionState",
    "PositionSizingResult",
    "PreTradeChecklist",
    "SessionDisciplineStatus",
    "compute_position_size",
    "evaluate_checklist",
    "evaluate_session_state",
]
