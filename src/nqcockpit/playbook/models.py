"""Modèles de données pour le module Event Playbook (P06).

Aucun chiffre inventé : chaque nombre porte sa source et son horodatage.
Aucun biais directionnel : les scénarios décrivent ce qu'on observe, pas ce qu'on prédit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ReactionStats:
    """Distribution des réactions NQ sur un horizon post-événement.

    Calculée depuis les enregistrements historiques en base (event_reactions).
    Si n < min_event_samples (config.validation.min_event_samples), is_sufficient=False.
    """

    horizon_label: str
    """Horizon : '+5m', '+15m', '+60m'."""

    n: int
    """Nombre d'occurrences historiques disponibles."""

    is_sufficient: bool
    """True si n >= min_event_samples (config)."""

    median_pts: float | None = None
    """Médiane des mouvements absolus en points NQ."""

    q25_pts: float | None = None
    """Quantile 25 % des mouvements en points NQ."""

    q75_pts: float | None = None
    """Quantile 75 % des mouvements en points NQ."""

    reversal_pct: float | None = None
    """Part des occurrences ayant subi un retournement.

    Retournement = mouvement contraire > 50 % du move initial.
    """

    note: str = ""
    """Remarque affichée si is_sufficient=False : 'échantillon insuffisant'."""


@dataclass
class ConditionalScenario:
    """Scénario conditionnel (en_ligne / chaud / froid) — ce qu'on observe, pas ce qu'on prédit."""

    label: str
    """'en_ligne' | 'chaud' | 'froid'."""

    surprise_threshold: float | None
    """Seuil de surprise en unité de la release (configurable). None = 'en ligne'."""

    description: str
    """Description de ce qu'on observe dans ce scénario."""

    levels_to_watch: list[str] = field(default_factory=list)
    """Niveaux à surveiller (gamma walls, expected move bornes…)."""

    protocol: str = ""
    """Protocole extrait de la config (stand_aside_before_minutes, wait_after_minutes…)."""


@dataclass
class PositioningSnapshot:
    """Positionnement au moment de la génération de la fiche."""

    expected_move_pts: float | None
    """Expected move du jour en points NQ (ACT/365, T calendaire réel)."""

    regime_gamma: str | None
    """'long_gamma' | 'short_gamma' | 'neutral' | None."""

    dist_call_wall_pts: float | None
    """Distance au call wall en points NQ (positif = call wall au-dessus du spot)."""

    dist_put_wall_pts: float | None
    """Distance au put support en points NQ (positif = put support en dessous du spot)."""

    vxn_spot: float | None
    """VXN spot (volatilité NDX 30j)."""

    vix_spot: float | None
    """VIX spot."""

    basis_pts: float | None
    """Basis NQ/NDX en points."""

    spot_nq: float | None
    """Cours NQ spot utilisé."""

    data_age_minutes: float | None
    """Âge des données de positionnement en minutes."""

    status: str = "OK"
    """'OK' | 'DÉGRADÉ' — DÉGRADÉ si source inaccessible ou données périmées."""

    status_detail: str = ""
    """Explication du statut DÉGRADÉ si applicable."""

    as_of_utc: datetime | None = None
    """Horodatage UTC du snapshot de positionnement."""


@dataclass
class EventPlaybookCard:
    """Fiche complète d'anticipation pour un événement Tier 1/2.

    Générée à J-2, J-1 ou T-30min selon generation_trigger.
    Aucun biais directionnel : les scénarios décrivent des niveaux, pas des prévisions.
    """

    event_name: str
    """Nom de l'événement : 'NFP', 'CPI', 'FOMC Minutes'…"""

    tier: int
    """1 (RED potentiel) ou 2 (AMBER potentiel)."""

    scheduled_utc: datetime
    """Heure programmée de la publication (UTC)."""

    scheduled_et_str: str
    """Heure ET formatée (ex: '2026-10-02 08:30 ET')."""

    scheduled_algiers_str: str
    """Heure Alger formatée (ex: '2026-10-02 13:30 Alger')."""

    countdown_str: str
    """Compte à rebours depuis la génération (ex: 'dans 1j 14h 22m')."""

    generation_trigger: str
    """'J-2' | 'J-1' | 'T-30min'."""

    generated_at_utc: datetime
    """Horodatage UTC de génération de la fiche."""

    consensus: str | None = None
    """Consensus de marché (ForexFactory ou autre source)."""

    consensus_status: str = "OK"
    """Statut du consensus : 'OK' | 'DÉGRADÉ: <raison>'."""

    previous: str | None = None
    """Valeur précédente."""

    previous_status: str = "OK"
    """Statut de la valeur précédente : 'OK' | 'DÉGRADÉ: <raison>'."""

    consensus_source: str = ""
    """Source du consensus (ex: 'ForexFactory')."""

    reaction_stats: dict[str, ReactionStats] = field(default_factory=dict)
    """Distribution des réactions NQ par horizon : {'+5m': ReactionStats, ...}."""

    scenarios: list[ConditionalScenario] = field(default_factory=list)
    """Scénarios conditionnels (en_ligne, chaud, froid)."""

    positioning: PositioningSnapshot | None = None
    """Positionnement au moment de la génération."""

    stand_aside_before_minutes: int = 5
    """Minutes avant l'événement où on ne trade pas (config)."""

    wait_after_minutes: int = 3
    """Minutes après l'événement avant de reprendre (config)."""

    post_event_buffer_minutes: int = 90
    """Buffer total post-événement (config)."""

    date_origin: str = ""
    """Origine de la date retenue : 'officielle' | 'ForexFactory' | 'calendrier statique'…"""

    time_provenance: str = ""
    """Origine de l'heure (ex: 'table versionnée BLS (08:30 ET)')."""

    status: str = "OK"
    """'OK' | 'DÉGRADÉ'."""

    status_detail: str = ""


@dataclass
class FomcDiff:
    """Diff mot à mot entre deux communiqués FOMC successifs.

    Étiquetage : 'aide de lecture, pas un signal'.
    """

    prev_statement_url: str
    """URL du communiqué précédent."""

    curr_statement_url: str
    """URL du communiqué courant."""

    added_sentences: list[str]
    """Phrases ajoutées dans le communiqué courant."""

    removed_sentences: list[str]
    """Phrases retirées par rapport au communiqué précédent."""

    tone_label: str | None
    """'hawkish' | 'neutre' | 'dovish' | None (si gabarit sans LLM)."""

    tone_extracts: list[str] = field(default_factory=list)
    """Extraits courts justifiant la lecture de ton."""

    tone_note: str = "aide de lecture, pas un signal"
    """Avertissement obligatoire."""

    fetched_at_utc: datetime | None = None
    """Horodatage UTC du fetch des deux communiqués."""

    status: str = "OK"
    """'OK' | 'DÉGRADÉ' (si un communiqué est inaccessible)."""

    status_detail: str = ""


@dataclass
class FomcMinutesWatch:
    """Fiche 'à surveiller' avant la publication des minutes FOMC."""

    scheduled_utc: datetime
    """Heure de publication des minutes (UTC)."""

    themes: list[str] = field(default_factory=list)
    """Thèmes clés du dernier communiqué FOMC."""

    speeches_since: list[dict] = field(default_factory=list)
    """Discours Fed depuis la réunion : [{'speaker', 'date', 'title', 'url'}]."""

    dgs2_rate: float | None = None
    """Taux DGS2 (rendement 2 ans US — proxy anticipations) en %."""

    dgs2_date: str | None = None
    """Date d'observation du taux DGS2 (ex: '2026-09-30')."""

    dgs2_status: str = "OK"
    """'OK' | 'DÉGRADÉ'."""

    status: str = "OK"
    """Statut global de la fiche."""

    status_detail: str = ""
