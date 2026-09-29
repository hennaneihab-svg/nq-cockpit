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
        "fred": 4,
        "forexfactory": 5,
        "static": 6,
    }

    # Index : (name_lower, day) → CalendarEvent (meilleure source)
    index: dict[tuple[str, str], CalendarEvent] = {}
    divergences: list[str] = []

    for ev in all_events:
        # Reclassifier selon config
        ev.tier = classify_event(ev, tier1_names, tier2_names)
        if not ev.all_sources and ev.source:
            ev.all_sources = [ev.source]

        key = (ev.name.lower(), ev.scheduled_utc.strftime("%Y-%m-%d"))

        if key not in index:
            index[key] = ev
        else:
            existing = index[key]
            if not existing.all_sources and existing.source:
                existing.all_sources = [existing.source]

            # Détection de divergence horaire
            diff_s = abs(
                (ev.scheduled_utc - existing.scheduled_utc).total_seconds()
            )
            if diff_s > _DIVERGENCE_THRESHOLD_SECONDS:
                div_msg = (
                    f"[DIVERGENCE] [{ev.name} {ev.scheduled_utc.strftime('%Y-%m-%d')}] "
                    f"Source '{existing.source}' : "
                    f"{existing.scheduled_utc.strftime('%H:%MZ')} | "
                    f"Source '{ev.source}' : "
                    f"{ev.scheduled_utc.strftime('%H:%MZ')} "
                    f"(écart {diff_s/60:.1f} min)"
                )
                divergences.append(div_msg)

            # Garder la source de plus haute priorité pour l'heure
            existing_prio = SOURCE_PRIORITY.get(existing.source, 99)
            new_prio = SOURCE_PRIORITY.get(ev.source, 99)
            if new_prio < existing_prio:
                # Nouvelle source prioritaire : prendre son heure
                merged = CalendarEvent(
                    name=existing.name,
                    tier=min(existing.tier, ev.tier),  # Prendre le tier le plus élevé
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
                )
                index[key] = merged
            else:
                # Enrichir avec les données de la nouvelle source
                existing.all_sources = list(
                    set(existing.all_sources + ev.all_sources)
                )
                if not existing.consensus and ev.consensus:
                    existing.consensus = ev.consensus
                if not existing.previous and ev.previous:
                    existing.previous = ev.previous
                if not existing.actual and ev.actual:
                    existing.actual = ev.actual

    merged_list = sorted(index.values(), key=lambda e: e.scheduled_utc)
    return merged_list, divergences
