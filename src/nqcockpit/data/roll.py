"""Détection trimestrielle du roll de contrat futures NQ (CME).

Cycles :
- H : Mars
- M : Juin
- U : Septembre
- Z : Décembre

L'expiration a lieu le 3ème vendredi du mois de contrat.
La fenêtre de roll commence généralement le lundi de la semaine d'expiration
(ou ~8 jours calendaires avant l'expiration) lorsque le volume migre vers le contrat suivant.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from nqcockpit.data.models import RollInfo

MONTH_CODES = {
    3: "H",
    6: "M",
    9: "U",
    12: "Z",
}

QUARTERS = [3, 6, 9, 12]


def third_friday_of_month(year: int, month: int) -> date:
    """Calcule la date du 3ème vendredi d'un mois donné."""
    # Le premier jour du mois
    first_day = date(year, month, 1)
    # Jour de la semaine (0 = Lundi, ..., 4 = Vendredi)
    w = first_day.weekday()
    # Jours jusqu'au premier vendredi
    days_to_first_friday = (4 - w) % 7
    first_friday = first_day + timedelta(days=days_to_first_friday)
    # Le 3ème vendredi est 2 semaines plus tard
    return first_friday + timedelta(weeks=2)


def get_quarterly_expiries(year: int) -> list[tuple[int, date, str]]:
    """Retourne la liste des (mois, date_expiration, code_symbole) pour une année."""
    res = []
    for m in QUARTERS:
        exp = third_friday_of_month(year, m)
        code = f"NQ{MONTH_CODES[m]}{str(year)[-1]}"
        res.append((m, exp, code))
    return res


def detect_nq_roll(reference_date: date | datetime | None = None) -> RollInfo:
    """Détecte le contrat actif, le prochain contrat, et si la date est en roll.

    Si reference_date est le jour d'expiration ou avant, le contrat est front month
    mais en cours de roll vers le contrat suivant.
    """
    if reference_date is None:
        ref_d = datetime.now(timezone.utc).date()
    elif isinstance(reference_date, datetime):
        ref_d = reference_date.date()
    else:
        ref_d = reference_date

    # Construire la liste des échéances pour l'année courante et la suivante
    all_expiries: list[tuple[date, str]] = []
    for y in [ref_d.year, ref_d.year + 1]:
        for _, exp, code in get_quarterly_expiries(y):
            all_expiries.append((exp, code))

    # Trouver le premier contrat dont la date d'expiration est >= ref_d
    active_idx = 0
    for i, (exp, _) in enumerate(all_expiries):
        if ref_d <= exp:
            active_idx = i
            break

    active_exp, active_code = all_expiries[active_idx]
    next_exp, next_code = all_expiries[active_idx + 1]

    days_to_expiry = (active_exp - ref_d).days

    # Fenêtre de roll : commence 8 jours avant l'expiration
    roll_start = active_exp - timedelta(days=8)
    is_roll_window = ref_d >= roll_start

    if is_roll_window:
        status = "ROLL_WINDOW"
        message = (
            f"Fenêtre de roll active pour {active_code} -> {next_code}. "
            f"Expiration le {active_exp.isoformat()} ({days_to_expiry}j restants). "
            f"La liquidité migre vers le contrat {next_code}."
        )
    else:
        status = "NORMAL"
        message = (
            f"Contrat actif standard : {active_code}. "
            f"Expiration le {active_exp.isoformat()} ({days_to_expiry}j restants)."
        )

    return RollInfo(
        reference_date=ref_d,
        active_contract=active_code,
        next_contract=next_code,
        expiry_date=active_exp,
        roll_window_start=roll_start,
        is_roll_window=is_roll_window,
        days_to_expiry=days_to_expiry,
        status=status,
        message=message,
    )
