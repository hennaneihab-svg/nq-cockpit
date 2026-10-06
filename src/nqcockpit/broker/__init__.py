"""Module d'intégration courtier et plateformes tierces.

Contient les adaptateurs de connexion en lecture seule aux terminaux
de négociation locaux (MetaTrader 5).
"""

from __future__ import annotations

from nqcockpit.broker.mt5_client import (
    MT5AccountInfo,
    MT5Client,
    MT5ImportSummary,
    MT5PositionRecord,
    MT5Status,
    MT5TradeRecord,
)

__all__ = [
    "MT5AccountInfo",
    "MT5Client",
    "MT5ImportSummary",
    "MT5PositionRecord",
    "MT5Status",
    "MT5TradeRecord",
]
