"""Modèles de données pour le module macro et cross-asset (P07).

Fournit :
- Niveaux, percentiles 1 an et variations 5 jours pour US10Y, US2Y, DXY, VIX, VXN.
- Range et gap overnight du contrat NQ.
- Positionnement CFTC COT (contexte seulement, aucun signal directionnel).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MacroMetric:
    """Métrique macro/cross-asset horodatée avec percentile et variation 5 jours."""

    name: str
    """Nom d'affichage : 'US 10Y', 'US 2Y', 'DXY', 'VIX', 'VXN'."""

    symbol: str
    """Symbole ou identifiant source : 'DGS10', 'DGS2', 'DX-Y.NYB', '^VIX', '^VXN'."""

    current_value: float | None
    """Valeur courante."""

    observation_date: str = ""
    """Date de l'observation (ex: '2026-09-28')."""

    percentile_1y: float | None = None
    """Rang percentile sur les 252 derniers jours de bourse (0.0 à 100.0 %)."""

    delta_5d: float | None = None
    """Variation absolue sur 5 jours ouvrés."""

    delta_5d_pct: float | None = None
    """Variation en pourcentage sur 5 jours ouvrés."""

    source: str = ""
    """Source de la donnée (ex: 'FRED (DGS10)', 'yfinance (^VIX)')."""

    status: str = "OK"
    """'OK' | 'DÉGRADÉ: <raison>'."""

    provenance: str = ""
    """Origine explicite du seuil / de la série."""


@dataclass
class OvernightStats:
    """Statistiques de la session de nuit CME (Overnight) pour le NQ."""

    session_date: str = ""
    """Date de la séance cible (ex: '2026-09-30')."""

    high_price: float | None = None
    """Plus haut de la session overnight."""

    low_price: float | None = None
    """Plus bas de la session overnight."""

    open_price: float | None = None
    """Cours d'ouverture de l'overnight (18:00 ET)."""

    last_price: float | None = None
    """Dernier cours disponible de l'overnight."""

    prior_close_price: float | None = None
    """Clôture de la séance précédente (16:00 ET)."""

    range_pts: float | None = None
    """Amplitude overnight = High - Low."""

    gap_pts: float | None = None
    """Gap overnight = dernier cours (ou open US) - clôture veille 16:00 ET."""

    status: str = "OK"
    """'OK' | 'DÉGRADÉ: <raison>'."""

    status_detail: str = ""
    """Détail du statut DÉGRADÉ."""

    source: str = "barres NQ=F (CME)"
    """Source des barres."""


@dataclass
class CotPositioning:
    """Positionnement CFTC Commitments of Traders (COT).

    Avertissement obligatoire : contexte de positionnement, pas un signal directionnel.
    """

    report_date: str = ""
    """Date du relevé CFTC (mardi précédent)."""

    contract_name: str = ""
    """Nom du contrat (ex: 'NASDAQ-100 CONSOLIDATED - CME')."""

    non_commercial_long: int | None = None
    """Positions longues des spéculateurs (non-commercials)."""

    non_commercial_short: int | None = None
    """Positions courtes des spéculateurs."""

    non_commercial_net: int | None = None
    """Position nette = Long - Short."""

    change_net_1w: int | None = None
    """Variation de la position nette sur une semaine."""

    percentile_1y: float | None = None
    """Percentile historique 1 an de la position nette (0 à 100 %)."""

    status: str = "OK"
    """'OK' | 'DÉGRADÉ: <raison>'."""

    status_detail: str = ""

    source: str = "CFTC Legacy Futures Report"

    note: str = "contexte de positionnement, pas un signal directionnel"
    """Rappel obligatoire : aucun signal de trading n'est déduit du COT."""


@dataclass
class MacroSnapshot:
    """Snapshot global de l'environnement macroéconomique et cross-asset."""

    as_of_utc: datetime
    """Horodatage UTC du calcul."""

    metrics: dict[str, MacroMetric] = field(default_factory=dict)
    """Dictionnaire des métriques : 'us10y', 'us2y', 'dxy', 'vix', 'vxn'."""

    overnight: OvernightStats = field(default_factory=OvernightStats)
    """Données de la nuit NQ."""

    cot: CotPositioning = field(default_factory=CotPositioning)
    """Positionnement COT."""

    status: str = "OK"
    """Statut global."""

    status_detail: str = ""
