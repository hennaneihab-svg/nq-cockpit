"""Calcul des statistiques de réaction NQ post-événement.

Sources : table event_reactions (SQLite).
Aucun chiffre inventé : statistiques calculées uniquement sur données réelles.
Si n < min_event_samples : is_sufficient=False, note='échantillon insuffisant'.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from datetime import datetime, timezone

from nqcockpit.data.models import Bar
from nqcockpit.playbook.models import ReactionStats

log = logging.getLogger(__name__)

UTC = timezone.utc

# Horizons post-événement supportés (en minutes)
HORIZONS_MIN: dict[str, int] = {
    "+1m": 1,
    "+5m": 5,
    "+15m": 15,
    "+60m": 60,
}


def _price_at_offset(
    event_utc: datetime,
    offset_minutes: int,
    bars: list[Bar],
) -> float | None:
    """Retourne le prix de clôture de la barre la plus proche de event_utc + offset."""
    target_ts = event_utc.timestamp() + offset_minutes * 60
    best: Bar | None = None
    best_diff = float("inf")
    for bar in bars:
        diff = abs(bar.timestamp_utc.timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best = bar
    # Tolérance : ne pas utiliser une barre trop éloignée (> 3 min)
    if best is None or best_diff > 180:
        return None
    return best.close


def compute_reaction_stats(
    event_name: str,
    bars_1m: list[Bar],
    db_conn: sqlite3.Connection,
    min_event_samples: int = 12,
) -> dict[str, ReactionStats]:
    """Calcule les statistiques de réaction NQ par horizon pour un événement.

    Args:
        event_name: Nom de l'événement (ex: 'NFP').
        bars_1m: Barres NQ 1m disponibles.
        db_conn: Connexion SQLite avec la table event_reactions.
        min_event_samples: Seuil de suffisance (config.validation.min_event_samples).

    Returns:
        dict['+5m'|'+15m'|'+60m' -> ReactionStats]
    """
    results: dict[str, ReactionStats] = {}

    try:
        cur = db_conn.execute(
            """
            SELECT er.pre_price, er.post_5m_price, er.post_15m_price, er.post_60m_price,
                   er.post_1m_price
            FROM event_reactions er
            JOIN events ev ON er.event_id = ev.event_id
            WHERE LOWER(ev.name) = LOWER(?)
            ORDER BY ev.timestamp_utc DESC
            """,
            (event_name,),
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError as exc:
        log.warning("event_reactions query failed for %r: %s", event_name, exc)
        rows = []

    n = len(rows)
    sufficient = n >= min_event_samples

    for horizon_label, col_idx in [
        ("+1m", 4),  # post_1m_price
        ("+5m", 1),  # post_5m_price
        ("+15m", 2),  # post_15m_price
        ("+60m", 3),  # post_60m_price
    ]:
        if not sufficient or not rows:
            results[horizon_label] = ReactionStats(
                horizon_label=horizon_label,
                n=n,
                is_sufficient=False,
                note="échantillon insuffisant",
            )
            continue

        moves: list[float] = []
        reversals = 0
        for row in rows:
            pre = row[0]
            post = row[col_idx]
            if pre is None or post is None:
                continue
            move = post - pre
            moves.append(move)

        if len(moves) < min_event_samples:
            results[horizon_label] = ReactionStats(
                horizon_label=horizon_label,
                n=len(moves),
                is_sufficient=False,
                note="échantillon insuffisant",
            )
            continue

        # Retournements : comparer le move au move +1m (si disponible)
        for row in rows:
            pre = row[0]
            post_1m = row[4]
            post = row[col_idx]
            if pre is None or post_1m is None or post is None:
                continue
            initial_move = post_1m - pre
            later_move = post - pre
            if initial_move != 0 and (later_move / initial_move) < 0.5:
                reversals += 1

        reversal_pct = (reversals / len(moves) * 100) if moves else None

        try:
            med = statistics.median(moves)
            q25 = statistics.quantiles(moves, n=4)[0]
            q75 = statistics.quantiles(moves, n=4)[2]
        except statistics.StatisticsError:
            med, q25, q75 = None, None, None

        results[horizon_label] = ReactionStats(
            horizon_label=horizon_label,
            n=len(moves),
            is_sufficient=True,
            median_pts=round(med, 2) if med is not None else None,
            q25_pts=round(q25, 2) if q25 is not None else None,
            q75_pts=round(q75, 2) if q75 is not None else None,
            reversal_pct=round(reversal_pct, 1) if reversal_pct is not None else None,
        )

    return results


def record_post_event_reaction(
    event_id: str,
    event_utc: datetime,
    pre_price: float,
    bars_1m: list[Bar],
    surprise: float | None,
    expected_move_pts: float | None,
    db_conn: sqlite3.Connection,
) -> bool:
    """Enregistre la réaction NQ post-événement dans event_reactions.

    Mesures : +1m, +5m, +15m, +60m depuis event_utc.
    range_vs_expected_move = (max_move / expected_move_pts) si expected_move_pts > 0.

    Returns:
        True si insertion réussie, False sinon (DÉGRADÉ loggé).
    """
    now_utc = datetime.now(UTC)

    post_prices: dict[str, float | None] = {}
    for label, offset in HORIZONS_MIN.items():
        post_prices[label] = _price_at_offset(event_utc, offset, bars_1m)

    post_1m = post_prices["+1m"]
    post_5m = post_prices["+5m"]
    post_15m = post_prices["+15m"]
    post_60m = post_prices["+60m"]

    # Range vs expected move (max move dans les 60 premières minutes)
    moves = [
        abs(p - pre_price)
        for p in [post_1m, post_5m, post_15m, post_60m]
        if p is not None
    ]
    max_move = max(moves) if moves else None
    range_vs_em: float | None = None
    if max_move is not None and expected_move_pts and expected_move_pts > 0:
        range_vs_em = round(max_move / expected_move_pts, 4)

    try:
        db_conn.execute(
            """
            INSERT INTO event_reactions (
                event_id, pre_price,
                post_1m_price, post_5m_price, post_15m_price, post_60m_price,
                max_favorable, max_adverse,
                surprise, range_vs_expected_move,
                recorded_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                pre_price,
                post_1m,
                post_5m,
                post_15m,
                post_60m,
                max_move,
                None,  # max_adverse non calculé ici (nécessiterait barre par barre)
                surprise,
                range_vs_em,
                now_utc.isoformat(),
            ),
        )
        db_conn.commit()
        log.info("Réaction post-événement enregistrée pour event_id=%r", event_id)
        return True
    except sqlite3.Error as exc:
        log.warning("DÉGRADÉ — impossible d'enregistrer la réaction pour %r: %s", event_id, exc)
        return False
