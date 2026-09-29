"""Calendrier de marché et sessions via pandas_market_calendars."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class MarketCalendar:
    """Gestionnaire de sessions et jours fériés pour actions US (NASDAQ/NYSE) et CME."""

    def __init__(self) -> None:
        self._nasdaq = mcal.get_calendar("NASDAQ")
        # CME Globex Equities ou fallback
        cme_cal = mcal.get_calendar("CME_Equity") or mcal.get_calendar("CMEGlobex_Equities")
        self._cme = cme_cal if cme_cal is not None else self._nasdaq

    def is_trading_day(self, d: date, market: str = "NASDAQ") -> bool:
        """Indique si la date donnée est un jour d'ouverture du marché concerné."""
        cal = self._nasdaq if market.upper() == "NASDAQ" else self._cme
        sched = cal.schedule(start_date=d.isoformat(), end_date=d.isoformat())
        return not sched.empty

    def is_us_equity_regular_hours(self, dt: datetime | None = None) -> bool:
        """Vérifie si l'instant se situe pendant la séance régulière (09:30 - 16:00 ET).

        Retourne True UNIQUEMENT si le marché actions US est actuellement ouvert.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dt_et = dt.astimezone(ET)
        target_date = dt_et.date()

        # 1. Vérifier si c'est un jour de cotation NASDAQ
        d_str = target_date.isoformat()
        sched = self._nasdaq.schedule(start_date=d_str, end_date=d_str)
        if sched.empty:
            return False

        row = sched.iloc[0]
        market_open_utc = row["market_open"].to_pydatetime()
        market_close_utc = row["market_close"].to_pydatetime()

        # Comparaison en UTC
        return market_open_utc <= dt <= market_close_utc

    def get_session_status(self, dt: datetime | None = None) -> str:
        """Retourne le statut précis de la session pour l'indice actions US."""
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dt_et = dt.astimezone(ET)
        target_date = dt_et.date()

        d_str = target_date.isoformat()
        sched = self._nasdaq.schedule(start_date=d_str, end_date=d_str)
        if sched.empty:
            # Jour férié ou week-end
            if dt_et.weekday() in (5, 6):
                return "CLOSED_WEEKEND"
            return "CLOSED_HOLIDAY"

        row = sched.iloc[0]
        market_open_utc = row["market_open"].to_pydatetime()
        market_close_utc = row["market_close"].to_pydatetime()

        if dt < market_open_utc:
            # Heures pré-marché (dès 04:00 ET jusqu'à 09:30 ET)
            pre_start_et = datetime.combine(target_date, time(4, 0), tzinfo=ET)
            if dt >= pre_start_et:
                return "PRE_MARKET"
            return "CLOSED_OVERNIGHT"

        if market_open_utc <= dt <= market_close_utc:
            return "REGULAR_HOURS"

        # Après 16:00 ET
        post_end_et = datetime.combine(target_date, time(20, 0), tzinfo=ET)
        if dt <= post_end_et:
            return "POST_MARKET"
        return "CLOSED_OVERNIGHT"

    def get_last_equity_session_close(self, ref_utc: datetime | None = None) -> datetime:
        """Trouve la dernière clôture de séance régulière actions US antérieure à ref_utc.

        Retourne un datetime UTC représentant 16:00:00 ET du dernier jour de cotation régulier.
        """
        if ref_utc is None:
            ref_utc = datetime.now(timezone.utc)
        elif ref_utc.tzinfo is None:
            ref_utc = ref_utc.replace(tzinfo=timezone.utc)

        ref_et = ref_utc.astimezone(ET)
        # Chercher sur les 10 derniers jours ouvrés
        start_date = (ref_et.date() - timedelta(days=12)).isoformat()
        end_date = ref_et.date().isoformat()

        sched = self._nasdaq.schedule(start_date=start_date, end_date=end_date)
        if sched.empty:
            # Fallback théorique : hier 16h ET
            prev_d = ref_et.date() - timedelta(days=1)
            yesterday_et = datetime.combine(prev_d, time(16, 0), tzinfo=ET)
            return yesterday_et.astimezone(timezone.utc)

        # Parcourir en sens inverse pour trouver la dernière séance dont market_close <= ref_utc
        for idx in range(len(sched) - 1, -1, -1):
            row = sched.iloc[idx]
            close_utc = row["market_close"].to_pydatetime()
            if close_utc <= ref_utc:
                return close_utc

        # Si aucune trouvée, prendre la première de la table
        return sched.iloc[0]["market_close"].to_pydatetime()

    def calculate_trading_days_to_expiry(
        self,
        ref_utc: datetime,
        expiry_date: date,
    ) -> float:
        """Calcule le nombre de jours de bourse (trading days) restants jusqu'à l'échéance.

        - 0DTE (échéance le jour même en séance US) : fraction de séance restante
          entre ref_utc et 16:00 ET, rapportée à une séance de 6.5 heures.
        - Futures échéances : nombre de séances de bourse effectives entre la prochaine
          séance ouverte et expiry_date inclusivement.
        - Si ref_utc est après 16:00 ET un vendredi, le samedi ou le dimanche, pour une échéance
          le lundi suivant, le nombre de jours de bourse restants est exactement 1.0 (le lundi).
        - Veille de jour férié : les jours chômés sont exclus par le calendrier NASDAQ.
        """
        ref_et = ref_utc.astimezone(ET)
        ref_date = ref_et.date()

        if expiry_date < ref_date:
            return 0.001

        # Cas 0DTE
        if expiry_date == ref_date:
            if not self.is_trading_day(ref_date):
                return 0.001
            if ref_et.time() < time(9, 30):
                return 1.0
            if ref_et.time() > time(16, 0):
                return 0.001
            close_et = datetime.combine(ref_date, time(16, 0), tzinfo=ET)
            rem_sec = max(0.0, (close_et - ref_et).total_seconds())
            return max(0.001, rem_sec / (6.5 * 3600.0))

        # Échéance future
        after_close = ref_et.time() >= time(16, 0) or not self.is_trading_day(ref_date)
        if after_close:
            start_date = ref_date + timedelta(days=1)
            today_frac = 0.0
        elif ref_et.time() < time(9, 30):
            start_date = ref_date + timedelta(days=1)
            today_frac = 1.0 if self.is_trading_day(ref_date) else 0.0
        else:
            start_date = ref_date + timedelta(days=1)
            close_et = datetime.combine(ref_date, time(16, 0), tzinfo=ET)
            rem_sec = max(0.0, (close_et - ref_et).total_seconds())
            today_frac = max(0.0, rem_sec / (6.5 * 3600.0))

        if start_date <= expiry_date:
            valid_days = self._nasdaq.valid_days(
                start_date=start_date.isoformat(),
                end_date=expiry_date.isoformat(),
            )
            future_trading_days = float(len(valid_days))
        else:
            future_trading_days = 0.0

        total_days = today_frac + future_trading_days
        return max(0.001, total_days)

    def is_more_than_one_session_stale(
        self,
        bar_timestamp_utc: datetime,
        ref_utc: datetime | None = None,
    ) -> bool:
        """Indique si la donnée date de plus d'une séance de bourse clôturée."""
        if ref_utc is None:
            ref_utc = datetime.now(timezone.utc)
        elif ref_utc.tzinfo is None:
            ref_utc = ref_utc.replace(tzinfo=timezone.utc)

        last_close_utc = self.get_last_equity_session_close(ref_utc)
        bar_date = bar_timestamp_utc.astimezone(ET).date()
        last_close_date = last_close_utc.astimezone(ET).date()

        return bool(bar_date < last_close_date)


# Instance singleton
CALENDAR = MarketCalendar()
