"""Gestionnaire de risque et dimensionnement de position (P09 réel).

Formules rigoureuses :
- Valeur du point extraite de la configuration (NQ: 20$/pt, MNQ: 2$/pt, extensible)
- Arrondi inférieur (math.floor) : ne jamais dépasser le risque autorisé
- Aucune exécution d'ordre
"""

from __future__ import annotations

import math
from typing import Optional

from nqcockpit.config import AppConfig
from nqcockpit.discipline.models import PositionSizingResult


def compute_position_size(
    account_size: float,
    risk_pct: float,
    stop_points: float,
    instrument: str,
    config: AppConfig,
    prop_max_daily_loss: Optional[float] = None,
    prop_trailing_dd: Optional[float] = None,
    current_daily_loss_dollars: float = 0.0,
) -> PositionSizingResult:
    """Calcule le nombre maximal de contrats sans jamais dépasser le risque alloué.

    Args:
        account_size: Capital du compte en dollars ($).
        risk_pct: Pourcentage de risque par trade (ex: 0.5 pour 0.5%).
        stop_points: Distance du stop loss en points NQ/MNQ (> 0).
        instrument: 'NQ' ou 'MNQ'.
        config: Configuration de l'application.
        prop_max_daily_loss: Perte max journalière prop firm ($) optionnelle.
        prop_trailing_dd: Drawdown max glissant prop firm ($) optionnel.
        current_daily_loss_dollars: Pertes déjà enregistrées aujourd'hui ($).

    Returns:
        PositionSizingResult avec nombre de contrats, risque réel et avertissements.
    """
    inst_clean = instrument.strip().upper()
    pt_values = config.risk.point_values
    if inst_clean not in pt_values:
        raise ValueError(
            f"Instrument inconnu {inst_clean!r}. "
            f"Instruments configurés : {list(pt_values.keys())}"
        )

    point_val = pt_values[inst_clean]

    if account_size <= 0:
        return PositionSizingResult(
            instrument=inst_clean,
            account_size=account_size,
            risk_pct=risk_pct,
            stop_points=stop_points,
            point_value=point_val,
            risk_budget_dollars=0.0,
            risk_per_contract_dollars=0.0,
            contracts=0,
            actual_risk_dollars=0.0,
            actual_risk_pct=0.0,
            warning="Capital du compte nul ou négatif.",
        )

    if stop_points <= 0:
        return PositionSizingResult(
            instrument=inst_clean,
            account_size=account_size,
            risk_pct=risk_pct,
            stop_points=stop_points,
            point_value=point_val,
            risk_budget_dollars=round(account_size * (risk_pct / 100.0), 2),
            risk_per_contract_dollars=0.0,
            contracts=0,
            actual_risk_dollars=0.0,
            actual_risk_pct=0.0,
            warning="Distance de Stop Loss invalide (doit être > 0 points).",
        )

    risk_budget = account_size * (risk_pct / 100.0)
    risk_per_contract = stop_points * point_val

    # Arrondi strictement inférieur pour ne jamais dépasser le risque
    contracts_raw = risk_budget / risk_per_contract
    contracts = math.floor(contracts_raw)

    actual_risk_dollars = round(contracts * risk_per_contract, 2)
    actual_risk_pct = round((actual_risk_dollars / account_size) * 100.0, 3)

    warning: str | None = None
    if contracts == 0:
        warning = (
            f"Budget insuffisant ({risk_budget:.2f} $) pour 1 contrat "
            f"(nécessite {risk_per_contract:.2f} $ pour {stop_points:.1f} pts de stop)."
        )

    # Vérifications prop firm si définies (> 0)
    prop_warning: str | None = None
    if prop_max_daily_loss is not None and prop_max_daily_loss > 0:
        potential_daily_loss = current_daily_loss_dollars + actual_risk_dollars
        if potential_daily_loss > prop_max_daily_loss:
            prop_warning = (
                f"Alerte Prop Firm : la perte journalière potentielle "
                f"({potential_daily_loss:.2f} $) dépasserait la limite fixée "
                f"({prop_max_daily_loss:.2f} $)."
            )

    if prop_trailing_dd is not None and prop_trailing_dd > 0:
        if actual_risk_dollars > prop_trailing_dd:
            dd_msg = (
                f"Alerte Prop Firm : le risque de ce trade ({actual_risk_dollars:.2f} $) "
                f"dépasse le drawdown max toléré ({prop_trailing_dd:.2f} $)."
            )
            prop_warning = f"{prop_warning} | {dd_msg}" if prop_warning else dd_msg

    return PositionSizingResult(
        instrument=inst_clean,
        account_size=round(account_size, 2),
        risk_pct=round(risk_pct, 2),
        stop_points=round(stop_points, 2),
        point_value=point_val,
        risk_budget_dollars=round(risk_budget, 2),
        risk_per_contract_dollars=round(risk_per_contract, 2),
        contracts=contracts,
        actual_risk_dollars=actual_risk_dollars,
        actual_risk_pct=actual_risk_pct,
        warning=warning,
        prop_firm_warning=prop_warning,
    )
