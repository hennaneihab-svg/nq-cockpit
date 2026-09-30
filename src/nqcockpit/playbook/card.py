"""Génération de fiches d'anticipation (EventPlaybookCard) pour les événements Tier 1/2.

Générée à J-2, J-1 ou T-30min.
Aucun chiffre inventé : chaque nombre porte sa source.
Aucun biais directionnel : les scénarios décrivent des niveaux, pas des prévisions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nqcockpit.data.models import Bar
from nqcockpit.events.models import CalendarEvent
from nqcockpit.playbook.models import (
    ConditionalScenario,
    EventPlaybookCard,
    PositioningSnapshot,
    ReactionStats,
)

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")
ALG_TZ = ZoneInfo("Africa/Algiers")
UTC = timezone.utc


def _fmt_et(dt: datetime) -> str:
    return dt.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")


def _fmt_algiers(dt: datetime) -> str:
    return dt.astimezone(ALG_TZ).strftime("%Y-%m-%d %H:%M Alger")


def _countdown(from_utc: datetime, to_utc: datetime) -> str:
    """Compte à rebours depuis from_utc jusqu'à to_utc."""
    delta = to_utc - from_utc
    if delta.total_seconds() <= 0:
        return "déjà passé"
    total_s = int(delta.total_seconds())
    days = total_s // 86400
    hours = (total_s % 86400) // 3600
    minutes = (total_s % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}j")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return "dans " + " ".join(parts)


def _detect_trigger(now_utc: datetime, event_utc: datetime) -> str:
    """Détermine le déclencheur de génération : J-2, J-1, T-30min."""
    delta_h = (event_utc - now_utc).total_seconds() / 3600
    if delta_h <= 0.5:
        return "T-30min"
    if delta_h <= 24:
        return "J-1"
    return "J-2"


def _build_positioning(levels_snapshot: object | None) -> PositioningSnapshot:
    """Extrait le positionnement depuis un LevelsSnapshot ou retourne DÉGRADÉ."""
    if levels_snapshot is None:
        return PositioningSnapshot(
            expected_move_pts=None,
            regime_gamma=None,
            dist_call_wall_pts=None,
            dist_put_wall_pts=None,
            vxn_spot=None,
            vix_spot=None,
            basis_pts=None,
            spot_nq=None,
            data_age_minutes=None,
            status="DÉGRADÉ",
            status_detail="LevelsSnapshot non disponible",
        )

    try:
        spot = getattr(levels_snapshot, "spot", None)
        em = getattr(levels_snapshot, "expected_move_pts", None)
        regime = getattr(levels_snapshot, "regime", None)
        call_wall = getattr(levels_snapshot, "call_wall", None)
        put_support = getattr(levels_snapshot, "put_support", None)
        vxn = getattr(levels_snapshot, "vxn_spot", None)
        vix = getattr(levels_snapshot, "vix_spot", None)
        basis = getattr(levels_snapshot, "basis_pts", None)
        age = getattr(levels_snapshot, "data_age_minutes", None)
        snap_status = getattr(levels_snapshot, "status", None)
        as_of = getattr(levels_snapshot, "timestamp_utc", None)

        dist_call = (call_wall - spot) if (call_wall is not None and spot is not None) else None
        dist_put = (spot - put_support) if (put_support is not None and spot is not None) else None

        ps_status = "OK"
        ps_detail = ""
        if snap_status is not None:
            sv = snap_status.value if hasattr(snap_status, "value") else str(snap_status)
            if "DÉGRADÉ" in sv or "BLOQUÉ" in sv:
                ps_status = "DÉGRADÉ"
                ps_detail = sv

        return PositioningSnapshot(
            expected_move_pts=round(em, 2) if em is not None else None,
            regime_gamma=str(regime) if regime else None,
            dist_call_wall_pts=round(dist_call, 2) if dist_call is not None else None,
            dist_put_wall_pts=round(dist_put, 2) if dist_put is not None else None,
            vxn_spot=round(vxn, 2) if vxn is not None else None,
            vix_spot=round(vix, 2) if vix is not None else None,
            basis_pts=round(basis, 2) if basis is not None else None,
            spot_nq=round(spot, 2) if spot is not None else None,
            data_age_minutes=round(age, 1) if age is not None else None,
            status=ps_status,
            status_detail=ps_detail,
            as_of_utc=as_of,
        )
    except Exception as exc:
        log.warning("Erreur extraction positionnement: %s", exc)
        return PositioningSnapshot(
            expected_move_pts=None,
            regime_gamma=None,
            dist_call_wall_pts=None,
            dist_put_wall_pts=None,
            vxn_spot=None,
            vix_spot=None,
            basis_pts=None,
            spot_nq=None,
            data_age_minutes=None,
            status="DÉGRADÉ",
            status_detail=f"Erreur extraction: {exc}",
        )


def _build_scenarios(
    event_name: str,
    positioning: PositioningSnapshot,
    stand_aside_before: int,
    wait_after: int,
    post_buffer: int,
    surprise_thresholds: dict | None = None,
) -> list[ConditionalScenario]:
    """Construit les scénarios conditionnels (en_ligne / chaud / froid).

    Les seuils de surprise sont lus depuis la config (passés en paramètre).
    Les niveaux sont extraits du positionnement disponible.
    """
    if surprise_thresholds is None:
        surprise_thresholds = {}

    # Niveaux disponibles pour les scénarios
    levels_str: list[str] = []
    if positioning.expected_move_pts is not None:
        half_em = round(positioning.expected_move_pts / 2, 1)
        levels_str.append(
            f"Expected move ±{positioning.expected_move_pts} pts "
            f"(bornes ±{half_em} pts autour du spot)"
        )
    if positioning.dist_call_wall_pts is not None:
        levels_str.append(f"Call wall à +{positioning.dist_call_wall_pts:.1f} pts du spot")
    if positioning.dist_put_wall_pts is not None:
        levels_str.append(f"Put support à -{positioning.dist_put_wall_pts:.1f} pts du spot")

    protocol_base = (
        f"Stand aside {stand_aside_before} min avant la publication. "
        f"Attendre {wait_after} min après. "
        f"Buffer post-événement : {post_buffer} min. "
        "Attendre la clôture de la première bougie M5 avant toute action."
    )

    # Seuils de surprise (configurables, sinon valeurs génériques)
    seuil_chaud = surprise_thresholds.get(event_name, {}).get("chaud", None)
    seuil_froid = surprise_thresholds.get(event_name, {}).get("froid", None)

    scenarios = [
        ConditionalScenario(
            label="en_ligne",
            surprise_threshold=None,
            description=(
                f"Réalisation proche du consensus. "
                f"Régime gamma : {positioning.regime_gamma or 'inconnu'}. "
                "Surveiller la réaction initiale puis le retour à l'équilibre."
            ),
            levels_to_watch=levels_str,
            protocol=protocol_base,
        ),
        ConditionalScenario(
            label="chaud",
            surprise_threshold=seuil_chaud,
            description=(
                "Réalisation nettement supérieure au consensus"
                + (f" (seuil : +{seuil_chaud})" if seuil_chaud is not None else "")
                + ". Surveiller l'extension vers le call wall "
                "et la résistance de l'expected move."
            ),
            levels_to_watch=levels_str,
            protocol=protocol_base + " Réduire la taille si la volatilité dépasse l'expected move.",
        ),
        ConditionalScenario(
            label="froid",
            surprise_threshold=seuil_froid,
            description=(
                "Réalisation nettement inférieure au consensus"
                + (f" (seuil : {seuil_froid})" if seuil_froid is not None else "")
                + ". Surveiller le put support "
                "et la réaction dans la borne basse de l'expected move."
            ),
            levels_to_watch=levels_str,
            protocol=protocol_base + " Réduire la taille si la volatilité dépasse l'expected move.",
        ),
    ]
    return scenarios


def _evaluate_field_status(
    event: CalendarEvent,
    value: str | None,
    field_label: str,
    source_health_map: dict[str, str] | None = None,
) -> str:
    """Détermine le statut d'un champ consensus ou previous.

    Si non null -> 'OK'
    Si null -> statut DÉGRADÉ avec raison explicite :
      - Non fourni pour ce type d'événement (ex: FOMC Minutes, discours)
      - Erreur source (ex: ForexFactory HTTP 429, HTTP 404, inaccessible)
      - Non publié par la source
    """
    if value is not None:
        return "OK"

    non_consensus_events = ("fomc minutes", "powell", "fed speech", "fomc", "beige book")
    if any(nce in event.name.lower() for nce in non_consensus_events):
        return "DÉGRADÉ: non fourni pour ce type d'événement"

    if source_health_map and "forexfactory" in source_health_map:
        ff_err = source_health_map["forexfactory"]
        if ff_err:
            return f"DÉGRADÉ: ForexFactory {ff_err}"

    if "forexfactory" not in event.all_sources:
        return "DÉGRADÉ: ForexFactory non disponible"

    return f"DÉGRADÉ: {field_label} non publié par ForexFactory"


def generate_card(
    event: CalendarEvent,
    levels_snapshot: object | None,
    bars_nq_1m: list[Bar],
    db_conn: object | None,
    min_event_samples: int = 12,
    stand_aside_before_minutes: int = 5,
    wait_after_minutes: int = 3,
    post_event_buffer_minutes: int = 90,
    surprise_thresholds: dict | None = None,
    source_health_map: dict[str, str] | None = None,
    now_utc: datetime | None = None,
) -> EventPlaybookCard:
    """Génère une EventPlaybookCard complète pour un événement.

    Args:
        event: CalendarEvent Tier 1 ou 2.
        levels_snapshot: LevelsSnapshot courant (ou None → DÉGRADÉ).
        bars_nq_1m: Barres NQ 1m disponibles (pour historique de réaction).
        db_conn: Connexion SQLite (ou None → stats insuffisantes).
        min_event_samples: Seuil config.validation.min_event_samples.
        stand_aside_before_minutes: Config events.stand_aside_before_minutes.
        wait_after_minutes: Config events.wait_after_minutes.
        post_event_buffer_minutes: Config events.post_event_buffer_minutes.
        surprise_thresholds: Dict de seuils par événement (optionnel).
        source_health_map: Dict source -> message d'erreur/statut.
        now_utc: Heure courante UTC (défaut : now).

    Returns:
        EventPlaybookCard complète.
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    trigger = _detect_trigger(now_utc, event.scheduled_utc)
    positioning = _build_positioning(levels_snapshot)
    scenarios = _build_scenarios(
        event_name=event.name,
        positioning=positioning,
        stand_aside_before=stand_aside_before_minutes,
        wait_after=wait_after_minutes,
        post_buffer=post_event_buffer_minutes,
        surprise_thresholds=surprise_thresholds,
    )

    # Statistiques de réaction
    reaction_stats: dict[str, ReactionStats] = {}
    if db_conn is not None:
        from nqcockpit.playbook.reaction import compute_reaction_stats

        reaction_stats = compute_reaction_stats(
            event_name=event.name,
            bars_1m=bars_nq_1m,
            db_conn=db_conn,
            min_event_samples=min_event_samples,
        )
    else:
        for h in ["+1m", "+5m", "+15m", "+60m"]:
            reaction_stats[h] = ReactionStats(
                horizon_label=h,
                n=0,
                is_sufficient=False,
                note="échantillon insuffisant",
            )

    card_status = "OK"
    card_detail = ""
    if positioning.status == "DÉGRADÉ":
        card_status = "DÉGRADÉ"
        card_detail = f"Positionnement DÉGRADÉ: {positioning.status_detail}"

    # Évaluation du statut des champs consensus et previous
    c_status = _evaluate_field_status(
        event=event,
        value=event.consensus,
        field_label="consensus",
        source_health_map=source_health_map,
    )
    p_status = _evaluate_field_status(
        event=event,
        value=event.previous,
        field_label="précédent",
        source_health_map=source_health_map,
    )

    return EventPlaybookCard(
        event_name=event.name,
        tier=event.tier,
        scheduled_utc=event.scheduled_utc,
        scheduled_et_str=_fmt_et(event.scheduled_utc),
        scheduled_algiers_str=_fmt_algiers(event.scheduled_utc),
        countdown_str=_countdown(now_utc, event.scheduled_utc),
        generation_trigger=trigger,
        generated_at_utc=now_utc,
        consensus=event.consensus,
        consensus_status=c_status,
        previous=event.previous,
        previous_status=p_status,
        consensus_source=event.consensus_source or "",
        reaction_stats=reaction_stats,
        scenarios=scenarios,
        positioning=positioning,
        stand_aside_before_minutes=stand_aside_before_minutes,
        wait_after_minutes=wait_after_minutes,
        post_event_buffer_minutes=post_event_buffer_minutes,
        date_origin=event.date_origin,
        time_provenance=event.time_provenance,
        status=card_status,
        status_detail=card_detail,
    )


def card_to_dict(card: EventPlaybookCard) -> dict:
    """Sérialise une EventPlaybookCard en dict JSON-compatible.

    Aucun chiffre absent des données sources ne peut apparaître ici.
    """

    def _pos_dict(p: PositioningSnapshot | None) -> dict:
        if p is None:
            return {"status": "DÉGRADÉ", "status_detail": "non disponible"}
        return {
            "expected_move_pts": p.expected_move_pts,
            "regime_gamma": p.regime_gamma,
            "dist_call_wall_pts": p.dist_call_wall_pts,
            "dist_put_wall_pts": p.dist_put_wall_pts,
            "vxn_spot": p.vxn_spot,
            "vix_spot": p.vix_spot,
            "basis_pts": p.basis_pts,
            "spot_nq": p.spot_nq,
            "data_age_minutes": p.data_age_minutes,
            "status": p.status,
            "status_detail": p.status_detail,
            "as_of_utc": p.as_of_utc.isoformat() if p.as_of_utc else None,
        }

    def _stats_dict(rs: ReactionStats) -> dict:
        return {
            "n": rs.n,
            "is_sufficient": rs.is_sufficient,
            "median_pts": rs.median_pts,
            "q25_pts": rs.q25_pts,
            "q75_pts": rs.q75_pts,
            "reversal_pct": rs.reversal_pct,
            "note": rs.note,
        }

    def _scenario_dict(sc: ConditionalScenario) -> dict:
        return {
            "label": sc.label,
            "surprise_threshold": sc.surprise_threshold,
            "description": sc.description,
            "levels_to_watch": sc.levels_to_watch,
            "protocol": sc.protocol,
        }

    return {
        "event_name": card.event_name,
        "tier": card.tier,
        "scheduled_utc": card.scheduled_utc.isoformat(),
        "scheduled_et": card.scheduled_et_str,
        "scheduled_algiers": card.scheduled_algiers_str,
        "countdown": card.countdown_str,
        "generation_trigger": card.generation_trigger,
        "generated_at_utc": card.generated_at_utc.isoformat(),
        "consensus": card.consensus,
        "consensus_status": card.consensus_status,
        "previous": card.previous,
        "previous_status": card.previous_status,
        "consensus_source": card.consensus_source,
        "date_origin": card.date_origin,
        "time_provenance": card.time_provenance,
        "stand_aside_before_minutes": card.stand_aside_before_minutes,
        "wait_after_minutes": card.wait_after_minutes,
        "post_event_buffer_minutes": card.post_event_buffer_minutes,
        "positioning": _pos_dict(card.positioning),
        "reaction_stats": {k: _stats_dict(v) for k, v in card.reaction_stats.items()},
        "scenarios": [_scenario_dict(s) for s in card.scenarios],
        "status": card.status,
        "status_detail": card.status_detail,
    }
