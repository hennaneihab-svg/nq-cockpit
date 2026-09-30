"""Classificateur d'événements : Tier 1 / Tier 2 + détection de divergences.

Règles :
- Tier 1 si le nom (insensible à la casse) figure dans config.events.tier1.
- Tier 2 si dans config.events.tier2 ou si ForexFactory = "Medium".
- Divergence = même nom, même jour, heure différente > 5 min entre deux sources.
"""

from __future__ import annotations

from datetime import timezone

from nqcockpit.events.models import CalendarEvent

UTC = timezone.utc
_DIVERGENCE_THRESHOLD_SECONDS = 5 * 60  # 5 minutes


def classify_event(event: CalendarEvent, tier1_names: list[str], tier2_names: list[str]) -> int:
    """Retourne le tier (1 ou 2) pour un événement selon la config.

    Priorité : tier1 > tier2 > tier implicite de la source > 2 par défaut.
    Comparaison insensible à la casse.
    """
    name_lower = event.name.lower()
    if any(t.lower() == name_lower for t in tier1_names):
        return 1
    if any(t.lower() == name_lower for t in tier2_names):
        return 2
    # Garder le tier de la source si déjà 1
    if event.tier == 1:
        return 1
    return 2


def merge_and_classify(
    all_events: list[CalendarEvent],
    tier1_names: list[str],
    tier2_names: list[str],
) -> tuple[list[CalendarEvent], list[str]]:
    """Fusionne les événements de sources multiples, classifie et détecte les divergences.

    Règle de fusion :
    - Deux événements sont considérés identiques si même nom normalisé ET même jour.
    - Si deux sources donnent des heures différentes (> 5 min), c'est une DIVERGENCE.
    - L'événement retenu prend l'heure de la source principale
      (fed_html > bls > bea > fred > forexfactory).
    - L'événement retenu liste toutes les sources dans `all_sources`.

    Retourne:
        (events_merged, divergences)
    """
    SOURCE_PRIORITY = {
        "fed_html": 0,
        "fed_rss": 1,
        "bls": 2,
        "bea": 3,
        "ism": 3,
        "forexfactory": 4,
        "static": 5,
        "fred": 6,  # Règle estimée : ne doit jamais primer sur une source datée
    }

    # Index : (name_lower, day) → CalendarEvent (meilleure source)
    index: dict[tuple[str, str], CalendarEvent] = {}
    divergences: list[str] = []

    for ev in all_events:
        # Reclassifier selon config
        ev.tier = classify_event(ev, tier1_names, tier2_names)
        if not ev.all_sources and ev.source:
            ev.all_sources = [ev.source]

        # Recherche d'un événement correspondant (même nom dans un rayon de ±7 jours)
        matched_key = None
        for k, existing in index.items():
            if existing.name.lower() == ev.name.lower():
                days_gap = abs((ev.scheduled_utc.date() - existing.scheduled_utc.date()).days)
                if days_gap <= 7:
                    matched_key = k
                    break

        if matched_key is None:
            index[(ev.name.lower(), ev.scheduled_utc.strftime("%Y-%m-%d"))] = ev
        else:
            existing = index[matched_key]
            if not existing.all_sources and existing.source:
                existing.all_sources = [existing.source]

            # 1. Divergence de JOUR
            if ev.scheduled_utc.date() != existing.scheduled_utc.date():
                days_gap = abs((ev.scheduled_utc.date() - existing.scheduled_utc.date()).days)
                div_msg = (
                    f"[DIVERGENCE DATE] [{ev.name}] "
                    f"Source '{existing.source}' : {existing.scheduled_utc.strftime('%Y-%m-%d')} | "
                    f"Source '{ev.source}' : {ev.scheduled_utc.strftime('%Y-%m-%d')} "
                    f"(écart {days_gap} jour{'s' if days_gap > 1 else ''})"
                )
                divergences.append(div_msg)
            else:
                # 2. Divergence d'HEURE (> 5 min)
                diff_s = abs((ev.scheduled_utc - existing.scheduled_utc).total_seconds())
                if diff_s > _DIVERGENCE_THRESHOLD_SECONDS:
                    div_msg = (
                        f"[DIVERGENCE HEURE] [{ev.name} {ev.scheduled_utc.strftime('%Y-%m-%d')}] "
                        f"Source '{existing.source}' : "
                        f"{existing.scheduled_utc.strftime('%H:%MZ')} | "
                        f"Source '{ev.source}' : "
                        f"{ev.scheduled_utc.strftime('%H:%MZ')} "
                        f"(écart {diff_s/60:.1f} min)"
                    )
                    divergences.append(div_msg)

            # Garder la source de plus haute priorité pour la date/heure
            existing_prio = SOURCE_PRIORITY.get(existing.source, 99)
            new_prio = SOURCE_PRIORITY.get(ev.source, 99)
            if new_prio < existing_prio:
                # Nouvelle source prioritaire : prendre sa date/heure
                merged = CalendarEvent(
                    name=existing.name,
                    tier=min(existing.tier, ev.tier),
                    scheduled_utc=ev.scheduled_utc,
                    source=ev.source,
                    description=existing.description or ev.description,
                    consensus=existing.consensus or ev.consensus,
                    previous=existing.previous or ev.previous,
                    actual=existing.actual or ev.actual,
                    source_fetched_utc=ev.source_fetched_utc,
                    source_age_seconds=ev.source_age_seconds,
                    status=existing.status,
                    all_sources=list(set(existing.all_sources + ev.all_sources)),
                    time_provenance=ev.time_provenance or existing.time_provenance,
                    consensus_source=ev.consensus_source or existing.consensus_source,
                    verified=ev.verified if ev.verified is not None else existing.verified,
                    primary_source_url=ev.primary_source_url or existing.primary_source_url,
                    consultation_date=ev.consultation_date or existing.consultation_date,
                )
                del index[matched_key]
                index[(merged.name.lower(), merged.scheduled_utc.strftime("%Y-%m-%d"))] = merged
            else:
                # Enrichir avec les données de la nouvelle source
                existing.all_sources = list(
                    set(existing.all_sources + ev.all_sources)
                )
                if not existing.time_provenance and ev.time_provenance:
                    existing.time_provenance = ev.time_provenance
                if not existing.consensus and ev.consensus:
                    existing.consensus = ev.consensus
                if not existing.previous and ev.previous:
                    existing.previous = ev.previous
                if not existing.actual and ev.actual:
                    existing.actual = ev.actual
                if not existing.consensus_source and ev.consensus_source:
                    existing.consensus_source = ev.consensus_source
                if not existing.primary_source_url and ev.primary_source_url:
                    existing.primary_source_url = ev.primary_source_url
                if not existing.consultation_date and ev.consultation_date:
                    existing.consultation_date = ev.consultation_date
                if not ev.verified:
                    existing.verified = False

    merged_list = sorted(index.values(), key=lambda e: e.scheduled_utc)
    return merged_list, divergences
