"""Moteur de génération du profil de séance, carte de scénarios et drapeaux NO-TRADE (P08).

Règles impératives :
- .agents/skills/nq-principles/SKILL.md : aucun biais directionnel.
- Formulations de scénarios strictement conditionnelles ("Si... alors...").
- Statut de santé par composant explicite (jamais masqué).
- Export CSV compatible TradingView / ATAS.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig, load_config
from nqcockpit.profile.models import (
    ComponentHealth,
    DayProfile,
    KeyLevel,
    NoTradeAssessment,
    NoTradeFlag,
    NoTradeFlagCode,
    ScenarioCard,
)

log = logging.getLogger(__name__)

UTC = timezone.utc
TZ_ET = ZoneInfo("America/New_York")
TZ_ALGIERS = ZoneInfo("Africa/Algiers")
_ALGIERS_FMT = "%Y-%m-%d %H:%M:%S (Alger)"
_ET_FMT = "%Y-%m-%d %H:%M:%S ET"


def evaluate_no_trade_flags(  # noqa: C901
    *,
    event_risk_level: str = "GREEN",
    is_red_window_active: bool = False,
    event_risk_reason: str = "",
    spot_nq: float = 20000.0,
    call_wall: float | None = None,
    put_support: float | None = None,
    wall_proximity_points: float = 40.0,
    component_statuses: dict[str, ComponentHealth] | None = None,
    stale_data_minutes: float = 30.0,
    basis_anomaly: bool = False,
    basis_anomaly_detail: str = "",
    daily_loss_r: float | None = None,
    daily_loss_limit_r: float = 2.0,
) -> NoTradeAssessment:
    """Évalue exhaustivement les 5 drapeaux NO-TRADE avec justification explicite."""
    flags: list[NoTradeFlag] = []
    blocking_flags: list[NoTradeFlag] = []

    # 1. Drapeau Événement RED (P05/P06)
    is_event_red = is_red_window_active or (event_risk_level.upper() == "RED")
    if is_event_red:
        event_reason = (
            f"Événement économique Tier 1 actif ou dans le tampon post-événement : "
            f"{event_risk_reason}"
        )
    else:
        event_reason = (
            "Aucun événement économique Tier 1 en cours ni dans le tampon post-événement"
        )
    flag_event = NoTradeFlag(
        code=NoTradeFlagCode.EVENT_RED,
        title="Événement RED / Tampon post-événement",
        triggered=is_event_red,
        status="ACTIF" if is_event_red else "INACTIF",
        reason=event_reason,
        severity="BLOCKING",
        source_module="P05-P06 Events/Playbook",
    )
    flags.append(flag_event)
    if is_event_red:
        blocking_flags.append(flag_event)

    # 2. Drapeau Compression entre deux murs gamma (P04)
    is_wall_compressed = False
    wall_reason = "Distance entre murs gamma suffisante pour opérer"
    if call_wall is not None and put_support is not None:
        wall_span = abs(call_wall - put_support)
        dist_to_call = abs(call_wall - spot_nq)
        dist_to_put = abs(spot_nq - put_support)
        if wall_span <= wall_proximity_points or (
            dist_to_call <= wall_proximity_points
            and dist_to_put <= wall_proximity_points
        ):
            is_wall_compressed = True
            wall_reason = (
                f"Prix coincé entre deux murs gamma à moins de "
                f"{wall_proximity_points:.0f} pts (Call Wall {call_wall:.1f} vs "
                f"Put Support {put_support:.1f}, écart={wall_span:.1f} pts)"
            )
    flag_wall = NoTradeFlag(
        code=NoTradeFlagCode.WALL_COMPRESSION,
        title="Compression entre murs gamma",
        triggered=is_wall_compressed,
        status="ACTIF" if is_wall_compressed else "INACTIF",
        reason=wall_reason,
        severity="BLOCKING",
        source_module="P04 Levels",
    )
    flags.append(flag_wall)
    if is_wall_compressed:
        blocking_flags.append(flag_wall)

    # 3. Drapeau Donnée périmée (toutes sources)
    is_stale = False
    stale_reasons: list[str] = []
    comp_map = component_statuses or {}
    for c_name, c_health in comp_map.items():
        if (
            c_health.age_minutes is not None
            and c_health.age_minutes > stale_data_minutes
        ):
            is_stale = True
            stale_reasons.append(
                f"{c_name} périmé ({c_health.age_minutes:.1f}m > "
                f"{stale_data_minutes:.0f}m)"
            )
        elif "périmé" in c_health.status.lower() or "stale" in c_health.status.lower():
            is_stale = True
            stale_reasons.append(f"{c_name}: {c_health.status}")

    if is_stale:
        stale_reason_str = " ; ".join(stale_reasons)
    else:
        stale_reason_str = "Toutes les sources sont fraîches et dans les seuils"

    flag_stale = NoTradeFlag(
        code=NoTradeFlagCode.STALE_DATA,
        title="Donnée de marché périmée",
        triggered=is_stale,
        status="ACTIF" if is_stale else "INACTIF",
        reason=stale_reason_str,
        severity="BLOCKING",
        source_module="Toutes sources (P04-P07)",
    )
    flags.append(flag_stale)
    if is_stale:
        blocking_flags.append(flag_stale)

    # 4. Drapeau Base NDX/NQ anormale (P04)
    if basis_anomaly:
        basis_reason_str = basis_anomaly_detail
    else:
        basis_reason_str = "Écart de base NDX/NQ et parité synthétique normaux"

    flag_basis = NoTradeFlag(
        code=NoTradeFlagCode.ABNORMAL_BASIS,
        title="Base NDX/NQ anormale",
        triggered=basis_anomaly,
        status="ACTIF" if basis_anomaly else "INACTIF",
        reason=basis_reason_str,
        severity="BLOCKING",
        source_module="P04 Basis",
    )
    flags.append(flag_basis)
    if basis_anomaly:
        blocking_flags.append(flag_basis)

    # 5. Drapeau Limite de perte journalière (P09)
    is_loss_limit_hit = False
    if daily_loss_r is not None:
        if daily_loss_r <= -daily_loss_limit_r:
            is_loss_limit_hit = True
            loss_status = "ACTIF"
            loss_reason = (
                f"Limite de perte journalière atteinte "
                f"({daily_loss_r:.1f}R <= -{daily_loss_limit_r:.1f}R)"
            )
        else:
            loss_status = "INACTIF"
            loss_reason = (
                f"Pertes du jour sous contrôle "
                f"({daily_loss_r:.1f}R > -{daily_loss_limit_r:.1f}R)"
            )
    else:
        loss_status = "DÉGRADÉ: module P09 (journal) non encore livré — non bloquant"
        loss_reason = (
            "Suivi des pertes P09 non disponible (statut dégradé sans blocage du trading)"
        )

    flag_loss = NoTradeFlag(
        code=NoTradeFlagCode.DAILY_LOSS_LIMIT,
        title="Limite de perte journalière (-2R)",
        triggered=is_loss_limit_hit,
        status=loss_status,
        reason=loss_reason,
        severity="BLOCKING" if is_loss_limit_hit else "INFORMATIVE",
        source_module="P09 Journal (en attente)",
    )
    flags.append(flag_loss)
    if is_loss_limit_hit:
        blocking_flags.append(flag_loss)

    is_allowed = len(blocking_flags) == 0
    if is_allowed:
        overall_status = "AUTORISÉ (sous conditions de setup)"
        summary_text = (
            "Aucun drapeau bloquant actif. Respecter impérativement les règles "
            "de Kill Zone et la limite de 2 trades/jour."
        )
    else:
        overall_status = "NO-TRADE ACTIF"
        flag_details = " | ".join(
            f"{f.code.value} ({f.reason})" for f in blocking_flags
        )
        summary_text = (
            f"{len(blocking_flags)} drapeau(x) bloquant(s) actif(s) : {flag_details}"
        )

    return NoTradeAssessment(
        is_trading_allowed=is_allowed,
        overall_status=overall_status,
        active_flags_count=len(blocking_flags),
        blocking_flags=blocking_flags,
        all_flags=flags,
        summary=summary_text,
    )


def build_scenario_map(
    key_levels: list[KeyLevel],
    gamma_regime: str = "POSITIVE_GAMMA",
    base_em_pts: float = 150.0,
) -> list[ScenarioCard]:
    """Génère la carte de scénarios "si... alors..." strictement non-directionnelle."""
    scenarios: list[ScenarioCard] = []

    for lvl in key_levels:
        name = lvl.name.upper()
        p = lvl.price

        if "GAMMA FLIP" in name:
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si le prix s'établit au-dessus du Gamma Flip ({p:.1f}) "
                        f"et s'y maintient"
                    ),
                    then_plan=(
                        "alors régime d'amortissement dealer (Mean Reversion) : "
                        "observer les replis vers la VWAP et éviter les "
                        "poursuites impulsives tardives."
                    ),
                    context_notes=(
                        "Régime gamma positif : les market makers vendent la force "
                        "et achètent les faiblesses."
                    ),
                )
            )
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si le prix casse franchement et clôture sous le Gamma Flip "
                        f"({p:.1f}) avec accélération"
                    ),
                    then_plan=(
                        "alors passage en régime de volatilité expansive : le hedging "
                        "dealer devient pro-cyclique (chasse à la liquidité, "
                        "amplitude accrue, réduire les tailles)."
                    ),
                    context_notes=(
                        "Régime gamma négatif : risque de cascade d'ordres stop et "
                        "d'amplification des amplitudes."
                    ),
                )
            )

        elif "CALL WALL" in name:
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si le prix teste le Call Wall ({p:.1f}) avec essoufflement "
                        f"du flux et absorption visible au carnet"
                    ),
                    then_plan=(
                        "alors résistance majeure attendue par couverture vendeuse "
                        "dealer : observer un setup de rejet ou d'absorption."
                    ),
                    context_notes=(
                        "Plus gros strike d'Open Interest Call : zone naturelle de "
                        "friction institutionnelle."
                    ),
                )
            )
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si le prix traverse le Call Wall ({p:.1f}) avec fort "
                        f"volume institutionnel et acceptation"
                    ),
                    then_plan=(
                        "alors risque de squeeze de delta dealer : ne pas anticiper "
                        "de retournement contre-tendance tant qu'aucune structure de "
                        "rejet M5/M15 n'est validée."
                    ),
                    context_notes=(
                        "Débouclage forcé possible des vendeurs d'options si le mur cède."
                    ),
                )
            )

        elif "PUT SUPPORT" in name:
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si le prix teste le Put Support ({p:.1f}) avec épuisement "
                        f"vendeur et absorption des stops"
                    ),
                    then_plan=(
                        "alors zone de soutien dealer majeure : observer la formation "
                        "d'un setup de retournement (CHoCH/BOS) pour un retour "
                        "statistique vers la zone médiane."
                    ),
                    context_notes=(
                        "Plus grand strike d'Open Interest Put : zone de rebond "
                        "technique statistiquement défendue."
                    ),
                )
            )
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si enfoncement soutenu sous le Put Support ({p:.1f}) sans "
                        f"réintégration immédiate"
                    ),
                    then_plan=(
                        "alors rupture de support institutionnel : risque d'accélération "
                        "par hedging vendeur des dealers, suspendre les achats aveugles."
                    ),
                    context_notes=(
                        "En cas de cassure de mur bas, l'expected move journalier "
                        "devient le prochain repère."
                    ),
                )
            )

        elif "OVERNIGHT HIGH" in name:
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si test de l'Overnight High ({p:.1f}) avec rejet immédiat "
                        f"(balayage de liquidité sans acceptation)"
                    ),
                    then_plan=(
                        "alors scénario de liquidity sweep : observer une réintégration "
                        "du range de nuit en direction de la VWAP de session."
                    ),
                    context_notes=(
                        "Les extrêmes de nuit concentrent les ordres stop des "
                        "participants asiatiques et européens."
                    ),
                )
            )
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si franchissement de l'Overnight High ({p:.1f}) avec "
                        f"ré-accumulation au-dessus du niveau"
                    ),
                    then_plan=(
                        "alors décalage structurel d'extension : surveiller le "
                        "Call Wall et la borne haute de l'Expected Move comme "
                        "prochains repères."
                    ),
                    context_notes=(
                        "Acceptation hors du range overnight = structure "
                        "d'extension de session."
                    ),
                )
            )

        elif "OVERNIGHT LOW" in name:
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si test de l'Overnight Low ({p:.1f}) avec rejet rapide "
                        f"(sweep de la liquidité basse)"
                    ),
                    then_plan=(
                        "alors observer la réintégration du range avec un setup "
                        "de retour vers l'équilibre de session."
                    ),
                    context_notes=(
                        "Balayage classique des stops sous les bas de nuit."
                    ),
                )
            )
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si clôture et travail sous l'Overnight Low ({p:.1f}) sans "
                        f"réaction acheteuse"
                    ),
                    then_plan=(
                        "alors décalage structurel d'extension : surveiller le "
                        "Put Support et la borne basse de l'Expected Move."
                    ),
                    context_notes=(
                        "Continuation hors du range de nuit."
                    ),
                )
            )

        elif "EXPECTED MOVE HAUT" in name or "EM HIGH" in name:
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si le prix atteint la borne haute de l'Expected Move ({p:.1f})"
                    ),
                    then_plan=(
                        "alors épuisement statistique d'amplitude journalière "
                        "(68 % des séances contenues) : prudence maximale sur les "
                        "breakouts impulsifs, risque élevé de fausse sortie sans nouvelle."
                    ),
                    context_notes=(
                        "Statistiquement, l'extension au-delà de 1σ requiert un "
                        "catalyseur Tier 1 non pricé."
                    ),
                )
            )

        elif "EXPECTED MOVE BAS" in name or "EM LOW" in name:
            scenarios.append(
                ScenarioCard(
                    level_name=lvl.name,
                    level_price=p,
                    level_type=lvl.level_type,
                    if_condition=(
                        f"Si le prix atteint la borne basse de l'Expected Move ({p:.1f})"
                    ),
                    then_plan=(
                        "alors épuisement statistique d'amplitude attendue : "
                        "surveiller un ralentissement du momentum et éviter de vendre "
                        "au plus bas de l'amplitude attendue."
                    ),
                    context_notes="Borne 1-sigma CBOE ACT/365.",
                )
            )

    return scenarios


def export_levels_to_csv(
    levels: list[KeyLevel],
    filepath: Path | str | None = None,
    now_utc: datetime | None = None,
) -> str:
    """Exporte les niveaux clés en format CSV standard compatible TradingView et ATAS."""
    if now_utc is None:
        now_utc = datetime.now(UTC)
    alg_str = now_utc.astimezone(TZ_ALGIERS).strftime(_ALGIERS_FMT)

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "Symbol",
        "Level_Name",
        "Price_NQ",
        "Distance_Pts",
        "Distance_Pct",
        "Type",
        "Source",
        "Updated_Algiers",
        "Description",
    ])

    for lvl in levels:
        writer.writerow([
            lvl.symbol,
            lvl.name,
            f"{lvl.price:.2f}",
            f"{lvl.distance_pts:+.2f}",
            f"{lvl.distance_pct:+.2f}%",
            lvl.level_type,
            lvl.source,
            alg_str,
            lvl.description,
        ])

    csv_text = output.getvalue()
    if filepath is not None:
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(csv_text, encoding="utf-8")

    return csv_text


def build_day_profile(  # noqa: C901
    *,
    conn: Any | None = None,
    config: AppConfig | None = None,
    now_utc: datetime | None = None,
    target_date: str | None = None,
) -> DayProfile:
    """Construit le profil de journée complet intégrant P04, P05, P06 et P07."""
    if config is None:
        config = load_config()
    if now_utc is None:
        now_utc = datetime.now(UTC)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)

    target_dt = target_date or now_utc.astimezone(TZ_ET).strftime("%Y-%m-%d")
    as_of_utc_str = now_utc.isoformat()
    as_of_algiers_str = now_utc.astimezone(TZ_ALGIERS).strftime(_ALGIERS_FMT)
    as_of_et_str = now_utc.astimezone(TZ_ET).strftime(_ET_FMT)

    component_statuses: dict[str, ComponentHealth] = {}

    # 1. Événements (P05/P06)
    event_risk_level = "GREEN"
    event_risk_reason = "Aucun événement Tier 1 imminent"
    next_t1_event = None
    next_t1_countdown = None
    is_red_window = False
    try:
        from nqcockpit.events.radar import fetch_event_radar

        radar = fetch_event_radar(config=config, ref_utc=now_utc)
        if hasattr(radar.risk_level, "value"):
            event_risk_level = radar.risk_level.value
        else:
            event_risk_level = str(radar.risk_level)
        upcoming_t1 = [
            ev for ev in radar.events_14d
            if ev.tier == 1 and ev.scheduled_utc >= now_utc
        ]
        if upcoming_t1:
            next_ev = upcoming_t1[0]
            next_t1_event = next_ev.name
            delta = next_ev.scheduled_utc - now_utc
            total_sec = int(delta.total_seconds())
            if total_sec > 0:
                h = total_sec // 3600
                m = (total_sec % 3600) // 60
                next_t1_countdown = f"{h}h {m}m"
            else:
                next_t1_countdown = "imminent"

        if (
            hasattr(radar, "active_window")
            and radar.active_window
            and event_risk_level == "RED"
        ):
            is_red_window = True
        elif event_risk_level == "RED":
            is_red_window = True

        component_statuses["events"] = ComponentHealth(
            name="Calendrier Événements (P05/P06)",
            status="OK" if radar.risk_level else "DÉGRADÉ",
            detail=f"Risque {event_risk_level} ({radar.reason})",
            timestamp_utc=as_of_utc_str,
        )
    except Exception as exc:
        log.warning("Impossible de charger le radar événements : %s", exc)
        component_statuses["events"] = ComponentHealth(
            name="Calendrier Événements (P05/P06)",
            status="DÉGRADÉ: radar inaccessible",
            detail=str(exc),
            timestamp_utc=as_of_utc_str,
        )

    # 2. Contexte Macro & Overnight (P07)
    vix_val = None
    vxn_val = None
    overnight_range = None
    overnight_high = None
    overnight_low = None
    vol_regime = "VOLATILITÉ NORMALE"
    try:
        from nqcockpit.macro.engine import compute_macro_snapshot

        bars_nq = None
        if conn is not None:
            try:
                from nqcockpit.data.db import get_bars
                bars_nq = get_bars(conn, "NQ=F", "1m", limit=2000)
            except Exception:
                pass

        macro_snap = compute_macro_snapshot(
            config=config, bars_nq=bars_nq, now_utc=now_utc
        )
        if "vix" in macro_snap.metrics:
            vix_val = macro_snap.metrics["vix"].current_value
        if "vxn" in macro_snap.metrics:
            vxn_val = macro_snap.metrics["vxn"].current_value
        if macro_snap.overnight and macro_snap.overnight.range_pts is not None:
            overnight_range = macro_snap.overnight.range_pts
            overnight_high = macro_snap.overnight.high_price
            overnight_low = macro_snap.overnight.low_price

        if vix_val is not None:
            if vix_val < 14.5:
                vol_regime = "VOLATILITÉ COMPRIMÉE"
            elif vix_val > 22.0:
                vol_regime = "VOLATILITÉ ÉLEVÉE"
            else:
                vol_regime = "VOLATILITÉ NORMALE"

        if macro_snap.status == "OK":
            c_status = "OK"
        else:
            c_status = f"DÉGRADÉ: {macro_snap.status_detail}"

        component_statuses["macro"] = ComponentHealth(
            name="Contexte Macro & Cross-Asset (P07)",
            status=c_status,
            detail=f"VIX={vix_val}, VXN={vxn_val}",
            timestamp_utc=as_of_utc_str,
        )
        if overnight_range is not None:
            on_st = "OK"
            on_det = f"Range nuit = {overnight_range} pts"
        else:
            on_st = "DÉGRADÉ: cours indisponibles"
            on_det = "N/A"

        component_statuses["overnight"] = ComponentHealth(
            name="Overnight NQ CME (P07)",
            status=on_st,
            detail=on_det,
            timestamp_utc=as_of_utc_str,
        )
    except Exception as exc:
        log.warning("Impossible de charger le snapshot macro : %s", exc)
        component_statuses["macro"] = ComponentHealth(
            name="Contexte Macro & Cross-Asset (P07)",
            status="DÉGRADÉ: échec calcul macro",
            detail=str(exc),
            timestamp_utc=as_of_utc_str,
        )
        component_statuses["overnight"] = ComponentHealth(
            name="Overnight NQ CME (P07)",
            status="DÉGRADÉ: échec overnight",
            detail=str(exc),
            timestamp_utc=as_of_utc_str,
        )

    # 3. Niveaux Gamma, Spot & Expected Move (P04 & P07)
    spot_nq = 20000.0
    gamma_flip = None
    call_wall = None
    put_support = None
    net_gex = None
    gamma_regime = "POSITIVE_GAMMA"
    dist_to_flip = None
    base_em = 150.0
    basis_anomaly = False
    basis_anomaly_detail = ""

    if conn is not None:
        try:
            row = conn.execute(
                """
                SELECT spot, gamma_flip, call_wall, put_support, expected_move,
                       regime, source, status, created_at_utc, basis, synthetic_basis
                FROM snapshots ORDER BY timestamp_utc DESC LIMIT 1
                """
            ).fetchone()
            if row:
                spot_nq = float(row[0]) if row[0] is not None else spot_nq
                gamma_flip = float(row[1]) if row[1] is not None else None
                call_wall = float(row[2]) if row[2] is not None else None
                put_support = float(row[3]) if row[3] is not None else None
                base_em = float(row[4]) if row[4] is not None else base_em
                gamma_regime = str(row[5]) if row[5] else gamma_regime
                snap_status = str(row[7])

                basis_val = float(row[9]) if row[9] is not None else None
                synth_val = float(row[10]) if row[10] is not None else None
                if basis_val is not None and synth_val is not None:
                    if abs(basis_val - synth_val) > 100.0:
                        basis_anomaly = True
                        basis_anomaly_detail = (
                            f"Écart basis ({basis_val:.1f}) vs synthétique "
                            f"({synth_val:.1f}) > 100 pts"
                        )

                g_status = "OK" if snap_status == "OK" else f"DÉGRADÉ: {snap_status}"
                g_detail = (
                    f"Spot={spot_nq:.1f}, Flip={gamma_flip}, "
                    f"CW={call_wall}, PS={put_support}"
                )
                component_statuses["gamma"] = ComponentHealth(
                    name="Niveaux Gamma & Options NDX (P04)",
                    status=g_status,
                    detail=g_detail,
                    timestamp_utc=str(row[8]),
                )
        except Exception as exc:
            log.warning("Erreur lecture snapshot DB : %s", exc)

    if "gamma" not in component_statuses:
        component_statuses["gamma"] = ComponentHealth(
            name="Niveaux Gamma & Options NDX (P04)",
            status="DÉGRADÉ: aucun snapshot disponible",
            detail="Utilisation des repères de secours",
            timestamp_utc=as_of_utc_str,
        )

    if conn is not None:
        try:
            from nqcockpit.data.db import get_bars
            recent_bars = get_bars(conn, "NQ=F", "1m", limit=5)
            if recent_bars:
                spot_nq = float(recent_bars[-1].close)
        except Exception:
            pass

    if gamma_flip is not None:
        dist_to_flip = round(spot_nq - gamma_flip, 2)
        if spot_nq >= gamma_flip:
            gamma_regime = "POSITIVE_GAMMA"
        else:
            gamma_regime = "NEGATIVE_GAMMA"

    em_consumption_pct = None
    if overnight_range is not None and base_em > 0:
        em_consumption_pct = round((overnight_range / base_em) * 100.0, 1)

    key_levels: list[KeyLevel] = []

    def _add_key_level(
        name: str, price: float | None, lvl_type: str, src: str, desc: str
    ):
        if price is not None and price > 0:
            d_pts = round(price - spot_nq, 2)
            d_pct = round((d_pts / spot_nq) * 100.0, 2)
            key_levels.append(
                KeyLevel(
                    name=name,
                    symbol="NQ=F",
                    price=round(price, 2),
                    level_type=lvl_type,
                    distance_pts=d_pts,
                    distance_pct=d_pct,
                    source=src,
                    description=desc,
                )
            )

    _add_key_level(
        "Call Wall",
        call_wall,
        "GAMMA",
        "CBOE NDX (P04)",
        "Plus forte concentration d'OI Call (résistance dealer)",
    )
    _add_key_level(
        "Expected Move Haut (+1σ)",
        spot_nq + base_em / 2.0,
        "EXPECTED_MOVE",
        "CBOE ACT/365 (P04)",
        "Borne haute d'amplitude statistique 1σ",
    )
    _add_key_level(
        "Overnight High",
        overnight_high,
        "OVERNIGHT",
        "CME NQ=F (P07)",
        "Sommet de la session de nuit CME (18:00 - 09:30 ET)",
    )
    _add_key_level(
        "Gamma Flip",
        gamma_flip,
        "GAMMA",
        "CBOE NDX (P04)",
        "Niveau pivot de basculement de régime gamma institutionnel",
    )
    _add_key_level(
        "Overnight Low",
        overnight_low,
        "OVERNIGHT",
        "CME NQ=F (P07)",
        "Creux de la session de nuit CME (18:00 - 09:30 ET)",
    )
    _add_key_level(
        "Expected Move Bas (-1σ)",
        spot_nq - base_em / 2.0,
        "EXPECTED_MOVE",
        "CBOE ACT/365 (P04)",
        "Borne basse d'amplitude statistique 1σ",
    )
    _add_key_level(
        "Put Support",
        put_support,
        "GAMMA",
        "CBOE NDX (P04)",
        "Plus forte concentration d'OI Put (support dealer)",
    )

    day_type_reasons: list[str] = []
    probable_type = "range"
    if gamma_regime == "POSITIVE_GAMMA":
        day_type_reasons.append(
            "Régime gamma positif (dealer long gamma favorisant le mean-reversion)"
        )
    else:
        day_type_reasons.append(
            "Régime gamma négatif (dealer short gamma favorisant les mouvements d'expansion)"
        )

    if vol_regime == "VOLATILITÉ COMPRIMÉE":
        probable_type = "range"
        day_type_reasons.append(
            f"VIX bas ({vix_val}) : probabilité accrue de séance comprimée"
        )
    elif vol_regime == "VOLATILITÉ ÉLEVÉE" or event_risk_level == "RED":
        probable_type = "volatile"
        day_type_reasons.append(
            "Risque événementiel ou volatilité élevée : "
            "probabilité accrue de séance expansive"
        )
    else:
        probable_type = "range / trend modéré"
        day_type_reasons.append(
            "Volatilité normale : probabilités statistiques réparties selon le "
            "test de Wilson"
        )

    wall_prox = 40.0
    if hasattr(config, "levels") and hasattr(config.levels, "wall_proximity_points"):
        wall_prox = float(config.levels.wall_proximity_points)

    stale_thresh = 30.0
    if hasattr(config, "levels") and hasattr(config.levels, "stale_data_minutes"):
        stale_thresh = float(config.levels.stale_data_minutes)

    loss_limit_cfg = 2.0
    if hasattr(config, "rules") and hasattr(config.rules, "daily_loss_limit_r"):
        loss_limit_cfg = float(config.rules.daily_loss_limit_r)

    no_trade_eval = evaluate_no_trade_flags(
        event_risk_level=event_risk_level,
        is_red_window_active=is_red_window,
        event_risk_reason=event_risk_reason,
        spot_nq=spot_nq,
        call_wall=call_wall,
        put_support=put_support,
        wall_proximity_points=wall_prox,
        component_statuses=component_statuses,
        stale_data_minutes=stale_thresh,
        basis_anomaly=basis_anomaly,
        basis_anomaly_detail=basis_anomaly_detail,
        daily_loss_r=None,
        daily_loss_limit_r=loss_limit_cfg,
    )

    scenarios = build_scenario_map(
        key_levels=key_levels,
        gamma_regime=gamma_regime,
        base_em_pts=base_em,
    )

    is_any_degraded = any("DÉGRADÉ" in c.status for c in component_statuses.values())
    profile_status = "DÉGRADÉ" if is_any_degraded else "OK"
    degraded_list = [
        f"{k} ({v.status})"
        for k, v in component_statuses.items()
        if "DÉGRADÉ" in v.status
    ]
    if degraded_list:
        profile_status_detail = f"Composants dégradés : {', '.join(degraded_list)}"
    else:
        profile_status_detail = ""

    return DayProfile(
        as_of_utc=as_of_utc_str,
        as_of_algiers=as_of_algiers_str,
        as_of_et=as_of_et_str,
        target_date=target_dt,
        spot_nq=spot_nq,
        event_risk_level=event_risk_level,
        event_risk_reason=event_risk_reason,
        next_tier1_event=next_t1_event,
        next_tier1_countdown=next_t1_countdown,
        volatility_regime=vol_regime,
        vix_level=vix_val,
        vxn_level=vxn_val,
        overnight_range_pts=overnight_range,
        gamma_regime=gamma_regime,
        net_gex_dollars=net_gex,
        distance_to_flip_pts=dist_to_flip,
        base_expected_move_pts=base_em,
        em_consumption_pct=em_consumption_pct,
        probable_day_type=probable_type,
        day_type_reasons=day_type_reasons,
        key_levels=key_levels,
        scenarios=scenarios,
        no_trade=no_trade_eval,
        component_statuses=component_statuses,
        status=profile_status,
        status_detail=profile_status_detail,
    )
