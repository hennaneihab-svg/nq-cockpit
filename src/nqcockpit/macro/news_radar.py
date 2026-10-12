"""Module de veille macroéconomique et radar d'actualités influençant le Nasdaq (Tâche 5).

Sources 100 % gratuites et directes :
1. Taux US 10Y & 2Y : FRED (DGS10, DGS2) avec repli cache/Yahoo ^TNX (étiqueté différé).
2. Inflation : FRED (CPIAUCSL) avec calcul YoY officiel et date de prochaine publication.
3. Mega-Caps : Calendrier des résultats des 7 géants de la tech (yfinance / SEC).
4. Banques Centrales : Fourchette Fed Funds (DFEDTARL/U) & RSS officiel Federal Reserve.
5. Pétrole Brut : WTI (CL=F) avec clôture officielle et variation.
6. Dollar Index : DXY (DX-Y.NYB) avec statut dégradé explicite hors cotation active.
7. Fil d'actualités en direct : Flux Fed Press Releases RSS & Google News US Macro/Nasdaq.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import yfinance as yf

from nqcockpit.data.cache import DEFAULT_CACHE_DIR, DiskCache
from nqcockpit.data.fetcher import DataFetcher
from nqcockpit.data.models import DataStatus
from nqcockpit.macro.fetcher import fetch_fred_history

log = logging.getLogger(__name__)

TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# Règle de fraîcheur des données : flux intraday <= 60 s, séries quotidiennes FRED <= 1800 s
CACHE_TTL_CONFIG: dict[str, float] = {
    "FRED_DAILY": 1800.0,  # Séries quotidiennes/mensuelles officielles FRED
    "YAHOO_WTI": 60.0,  # Pétrole brut WTI (CL=F)
    "YAHOO_DXY": 60.0,  # Dollar Index (DX-Y.NYB)
    "YAHOO_TNX": 60.0,  # Rendement 10 ans de repli (^TNX)
    "MAG7_CALENDAR": 60.0,  # Calendrier des résultats trimestriels
    "RSS_FED": 60.0,  # Communiqués officiels de la Fed
    "RSS_GOOGLE_NEWS": 60.0,  # Google News US Macro & Nasdaq
}

# Motifs textuels (en minuscules) identifiant les communiqués administratifs ou procéduraux
# sans impact macroéconomique ni volatilité sur le Nasdaq (bruit exclu du Live Wire).
FED_ADMIN_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "comment period",
    "enforcement action",
    "proposes to extend",
    "proposal to extend",
    "correction to",
    "public comment",
    "request for comment",
    "requests comment",
    "seek comment",
    "seeking comment",
    "approval of application",
    "approves application",
    "cease and desist",
    "written agreement with",
    "paperwork reduction act",
    "freedom of information act",
    "foia",
    "advisory council",
    "branch director",
    "election of directors",
    "appointment of director",
    "appointments of director",
    "deputy chair",
    "office of inspector general",
    "oig report",
)


def is_relevant_fed_wire_item(title: str) -> bool:
    """Filtre de pertinence pour les dépêches de la Réserve Fédérale (Live Wire).

    Exclut le bruit administratif et procédural sans impact sur le Nasdaq
    (actions disciplinaires, consultations réglementaires, errata, nominations non-votantes),
    tout en conservant par défaut l'ensemble des dépêches économiques et de politique monétaire
    (taux FOMC, discours de gouverneurs, Beige Book, minutes, projections).
    """
    if not title or not isinstance(title, str):
        return False
    t_lower = title.strip().lower()
    return not any(pattern in t_lower for pattern in FED_ADMIN_EXCLUDE_PATTERNS)


@dataclass
class MacroRadarCard:
    """Représente une des 6 fenêtres du Radar Macro."""

    category: str
    title: str
    main_value: str
    sub_value: str
    source: str
    timestamp_utc: datetime | None
    observation_date: str
    age_str: str
    status: str  # "OK" ou "DÉGRADÉ"
    is_ok: bool
    details: list[str] = field(default_factory=list)
    degraded_reason: str = ""

    @property
    def timestamp_algiers_str(self) -> str:
        """Horodatage formaté en heure d'Alger."""
        if not self.timestamp_utc:
            return self.observation_date or "N/A"
        return self.timestamp_utc.astimezone(TZ_ALGIERS).strftime("%d/%m/%Y %H:%M (Alger)")

    @property
    def timestamp_et_str(self) -> str:
        """Horodatage formaté en heure de New York."""
        if not self.timestamp_utc:
            return self.observation_date or "N/A"
        return self.timestamp_utc.astimezone(TZ_ET).strftime("%d/%m/%Y %H:%M ET")


@dataclass
class NewsWireItem:
    """Représente un titre d'actualité en direct avec lien, source et horodatages."""

    title: str
    link: str
    source: str
    tag: str
    tag_color: str
    timestamp_utc: datetime
    timestamp_algiers_str: str
    timestamp_et_str: str
    age_str: str
    is_ok: bool = True
    status: str = "OK"


@dataclass
class NewsWireReport:
    """Rapport du fil d'actualités avec liste des titres et statuts de santé."""

    items: list[NewsWireItem] = field(default_factory=list)
    degraded_sources: list[str] = field(default_factory=list)
    is_ok: bool = True
    fetched_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class MacroNewsRadar:
    """Conteneur des 6 fenêtres d'actualité pour le cockpit."""

    rates: MacroRadarCard
    inflation: MacroRadarCard
    mega_caps: MacroRadarCard
    fed: MacroRadarCard
    oil: MacroRadarCard
    dollar: MacroRadarCard
    fetched_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_list(self) -> list[MacroRadarCard]:
        return [
            self.rates,
            self.inflation,
            self.mega_caps,
            self.fed,
            self.oil,
            self.dollar,
        ]


def _format_age(delta_seconds: float) -> str:
    """Formate un intervalle en chaîne lisible."""
    if delta_seconds < 60:
        return f"{int(delta_seconds)}s"
    minutes = delta_seconds / 60.0
    if minutes < 60:
        return f"{int(minutes)} min"
    hours = minutes / 60.0
    if hours < 24:
        return f"{int(hours)}h {int(minutes % 60)}m"
    days = hours / 24.0
    return f"{int(days)}j {int(hours % 24)}h"


def get_cached_or_fetch(
    key: str,
    fetcher_fn: Any,
    max_age_seconds: float,
    cache: DiskCache | None = None,
) -> Any:
    """Récupère une donnée du cache disque ou exécute fetcher_fn si le cache est expiré."""
    c = cache or DiskCache(DEFAULT_CACHE_DIR)
    cached = c.get(key, max_age_seconds=max_age_seconds)
    if cached is not None:
        return cached
    data = fetcher_fn()
    c.set(key, data)
    return data


def fetch_rates_card(fetcher: DataFetcher | None = None) -> MacroRadarCard:
    """Fenêtre 1 : Taux US 10Y et 2Y (FRED DGS10, DGS2)."""
    f = fetcher or DataFetcher()
    now_utc = datetime.now(UTC)

    obs10 = f.fetch_fred_series("DGS10", max_cache_age_seconds=CACHE_TTL_CONFIG["FRED_DAILY"])
    obs2 = f.fetch_fred_series("DGS2", max_cache_age_seconds=CACHE_TTL_CONFIG["FRED_DAILY"])

    val10 = obs10.value if obs10.status == DataStatus.OK and obs10.value > 0 else None
    val2 = obs2.value if obs2.status == DataStatus.OK and obs2.value > 0 else None

    # Repli 10 ans sur Yahoo ^TNX / 10 si FRED indisponible
    source10 = obs10.source
    is_10_fallback = False
    if val10 is None:
        try:
            ticker_tnx = yf.Ticker("^TNX")
            hist_tnx = ticker_tnx.history(period="1d", interval="1m")
            if not hist_tnx.empty:
                val10 = float(hist_tnx["Close"].iloc[-1]) / 10.0
                source10 = "Yahoo ^TNX/10 [différé 15 min]"
                is_10_fallback = True
        except Exception as exc:
            log.warning("Échec repli Yahoo ^TNX: %s", exc)

    reasons: list[str] = []
    status_str = "OK"
    is_ok = True

    # Traitement du Taux 2 ans avec repli cache local si défaillance réseau
    source2 = obs2.source
    obs2_date = obs2.observation_date or ""
    obs2_ts = obs2.fetched_at_utc if obs2 else now_utc
    is_2_degraded = False

    if val2 is None or obs2.status != DataStatus.OK:
        is_2_degraded = True
        cached_2 = f.cache.get("fred_DGS2", max_age_seconds=86400 * 30)
        if cached_2 is not None and float(cached_2.get("value", 0.0)) > 0:
            val2 = float(cached_2["value"])
            obs2_date = str(cached_2.get("observation_date", ""))
            try:
                obs2_ts = datetime.fromisoformat(cached_2["fetched_at_utc"])
            except Exception:
                obs2_ts = now_utc
            age_c = _format_age((now_utc - obs2_ts).total_seconds())
            source2 = "FRED (cache local)"
            val2_display = f"{val2:.2f}% (Obs: {obs2_date})"
            reasons.append(
                f"Taux 2 ans : FRED direct indisponible, repli cache local "
                f"(Obs: {obs2_date}, âge {age_c})"
            )
        else:
            val2 = None
            val2_display = "INDISPONIBLE"
            reasons.append("Taux 2 ans : FRED direct indisponible, aucune observation en cache")
    else:
        val2_display = f"{val2:.2f}%"

    if is_2_degraded or is_10_fallback or (val10 is None) or (val2 is None):
        status_str = "DÉGRADÉ"
        is_ok = False

    if is_10_fallback:
        reasons.append("Taux 10 ans : repli Yahoo Finance ^TNX cotation différée de 15 min")

    val10_str = f"{val10:.2f}%" if val10 is not None else "INDISPONIBLE"

    if val10 is not None and val2 is not None:
        spread = (val10 - val2) * 100.0  # en bps
        cache_mark = " [cache 2Y]" if is_2_degraded else ""
        main_val = f"10Y: {val10:.2f}% | 2Y: {val2:.2f}%{cache_mark}"
        spread_type = "pentifiée" if spread > 0 else "inversée"
        sub_val = f"Spread 10Y-2Y : {spread:+.0f} bps ({spread_type})"
    else:
        main_val = f"10Y: {val10_str} | 2Y: {val2_display}"
        sub_val = "Spread calcul impossible [donnée incomplète]"

    min_ts = min(obs10.fetched_at_utc if obs10 else now_utc, obs2_ts)
    age_s = _format_age((now_utc - min_ts).total_seconds())

    return MacroRadarCard(
        category="TAUX & RENDEMENTS",
        title="Taux US 10 ans & 2 ans",
        main_value=main_val,
        sub_value=sub_val,
        source=f"FRED ({source10} / {source2})",
        timestamp_utc=min_ts,
        observation_date=obs10.observation_date or obs2_date or "",
        age_str=age_s,
        status=status_str,
        is_ok=is_ok,
        details=[
            f"Rendement 10 ans : {val10_str}",
            f"Rendement 2 ans : {val2_display}",
            f"Date d'observation 10Y : {obs10.observation_date or 'N/A'}",
            f"Date d'observation 2Y : {obs2_date or 'N/A'}",
        ],
        degraded_reason="; ".join(reasons) if reasons else "",
    )


def fetch_inflation_card() -> MacroRadarCard:
    """Fenêtre 2 : Inflation & Anticipations (FRED CPIAUCSL)."""
    now_utc = datetime.now(UTC)
    hist = fetch_fred_history("CPIAUCSL", max_cache_age_seconds=CACHE_TTL_CONFIG["FRED_DAILY"])

    if len(hist) < 13:
        return MacroRadarCard(
            category="INFLATION & PRIX",
            title="Inflation US (CPI YoY)",
            main_value="INDISPONIBLE",
            sub_value="Historique insuffisant pour calcul annuel",
            source="FRED (CPIAUCSL)",
            timestamp_utc=now_utc,
            observation_date="",
            age_str="Données incomplètes",
            status="DÉGRADÉ",
            is_ok=False,
            details=["Moins de 13 mois de données reçus de FRED"],
            degraded_reason="Historique FRED CPIAUCSL < 13 mois",
        )

    last_dt_raw, last_cpi = hist[-1]
    if isinstance(last_dt_raw, str):
        last_dt = datetime.fromisoformat(last_dt_raw).date()
    elif hasattr(last_dt_raw, "date"):
        last_dt = last_dt_raw.date()
    else:
        last_dt = last_dt_raw

    last_year = last_dt.year
    last_month = last_dt.month

    target_year = last_year - 1
    prior_cpi = None
    prior_dt = None

    for dt_raw, val in reversed(hist[:-1]):
        if isinstance(dt_raw, str):
            dt_cur = datetime.fromisoformat(dt_raw).date()
        elif hasattr(dt_raw, "date"):
            dt_cur = dt_raw.date()
        else:
            dt_cur = dt_raw

        if dt_cur.year == target_year and dt_cur.month == last_month:
            prior_cpi = val
            prior_dt = dt_cur
            break

    if prior_cpi is None or prior_cpi <= 0:
        return MacroRadarCard(
            category="INFLATION & PRIX",
            title="Inflation US (CPI YoY)",
            main_value=f"Indice : {last_cpi:.3f}",
            sub_value="Mois correspondant an n-1 introuvable",
            source="FRED (CPIAUCSL)",
            timestamp_utc=now_utc,
            observation_date=str(last_dt),
            age_str="Calcul YoY impossible",
            status="DÉGRADÉ",
            is_ok=False,
            details=[f"Dernier indice : {last_cpi} au {last_dt}"],
            degraded_reason=f"Pas de valeur CPI pour {target_year}-{last_month:02d}",
        )

    cpi_yoy = ((last_cpi - prior_cpi) / prior_cpi) * 100.0
    main_val = f"CPI YoY: {cpi_yoy:+.2f} %"
    sub_val = f"Indice: {last_cpi:.3f} (Réf: {last_dt})"
    age_str = f"Mois: {last_dt.strftime('%B %Y')}"

    return MacroRadarCard(
        category="INFLATION & PRIX",
        title="Inflation US (CPI YoY)",
        main_value=main_val,
        sub_value=sub_val,
        source="FRED (CPIAUCSL)",
        timestamp_utc=now_utc,
        observation_date=str(last_dt),
        age_str=age_str,
        status="OK",
        is_ok=True,
        details=[
            f"Indice actuel : {last_cpi:.3f} ({last_dt})",
            f"Indice il y a 1 an : {prior_cpi:.3f} ({prior_dt})",
            f"Variation annuelle : {cpi_yoy:+.2f} %",
        ],
        degraded_reason="",
    )


def fetch_mega_caps_card() -> MacroRadarCard:
    """Fenêtre 3 : Mega-Caps Tech (Calendrier des résultats trimestriels Tier 1/2)."""
    now_utc = datetime.now(UTC)
    today = now_utc.date()
    from nqcockpit.config import load_config
    from nqcockpit.events.earnings import fetch_earnings_events
    try:
        conf = load_config()
        symbols = list(conf.events.megacaps)
    except Exception:
        symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO"]

    events = fetch_earnings_events(tickers=symbols, now_utc=now_utc, horizon_days=90)
    upcoming = []
    failed = []

    for ev in events:
        if ev.status.value == "OK" and ev.scheduled_utc:
            d_parsed = ev.scheduled_utc.date()
            delta_d = (d_parsed - today).days
            # Add tier info T1/T2
            upcoming.append((ev.ticker, d_parsed.strftime("%d/%m"), delta_d, ev.tier))
        else:
            failed.append(ev.ticker)

    upcoming.sort(key=lambda x: x[2])
    is_ok = len(upcoming) >= len(symbols) // 2
    status_str = "OK" if is_ok else "DÉGRADÉ"

    if upcoming:
        first3 = upcoming[:3]
        main_val = " • ".join([f"[T{t}] {s}: {d}" for s, d, _, t in first3])
        next_sym, next_d, next_days, next_tier = upcoming[0]
        if next_days >= 0:
            sub_val = f"Plus proche : [T{next_tier}] {next_sym} ({next_d}, dans {next_days} jours)"
        else:
            sub_val = f"Dernier : [T{next_tier}] {next_sym} (passé il y a {abs(next_days)} jours)"
    else:
        main_val = "INDISPONIBLE"
        sub_val = "Calendrier non reçu"

    details = [f"[T{t}] {s}: date {d} (J{days:+d})" for s, d, days, t in upcoming]
    reason = f"Échec récupération pour: {', '.join(failed)}" if failed else ""

    return MacroRadarCard(
        category="MEGA-CAPS TECH",
        title="Résultats Megacaps",
        main_value=main_val,
        sub_value=sub_val,
        source="Yahoo Finance / SEC Filings",
        timestamp_utc=now_utc,
        observation_date=str(today),
        age_str="Scan en direct",
        status=status_str,
        is_ok=is_ok,
        details=details,
        degraded_reason=reason,
    )
def fetch_fed_card(fetcher: DataFetcher | None = None) -> MacroRadarCard:
    """Fenêtre 4 : Banques Centrales & Fed (DFEDTARL/U & RSS)."""
    f = fetcher or DataFetcher()
    now_utc = datetime.now(UTC)

    obs_u = f.fetch_fred_series("DFEDTARU", max_cache_age_seconds=CACHE_TTL_CONFIG["FRED_DAILY"])
    obs_l = f.fetch_fred_series("DFEDTARL", max_cache_age_seconds=CACHE_TTL_CONFIG["FRED_DAILY"])

    val_u = obs_u.value if obs_u.status == DataStatus.OK and obs_u.value > 0 else None
    val_l = obs_l.value if obs_l.status == DataStatus.OK and obs_l.value > 0 else None

    # Communiqué récent Fed RSS (filtrage du bruit procédural)
    fed_headline = ""
    try:
        url_fed = "https://www.federalreserve.gov/feeds/press_all.xml"
        req = urllib.request.Request(
            url_fed,
            headers={"User-Agent": "NQCockpit/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            root = ET.fromstring(r.read())
            items = list(root.iter("item"))
            for it in items:
                candidate = (it.findtext("title") or "").strip()
                if is_relevant_fed_wire_item(candidate):
                    fed_headline = candidate
                    break
            if not fed_headline and items:
                fed_headline = (items[0].findtext("title") or "").strip()
    except Exception as exc:
        log.warning("Échec RSS Fed: %s", exc)

    is_ok = (val_u is not None) and (val_l is not None)
    status_str = "OK" if is_ok else "DÉGRADÉ"

    if val_u is not None and val_l is not None:
        main_val = f"Fourchette FOMC : {val_l:.2f}% – {val_u:.2f}%"
    else:
        main_val = "Fourchette Fed : INDISPONIBLE"

    if len(fed_headline) > 70:
        sub_val = fed_headline[:70] + "..."
    else:
        sub_val = fed_headline or "Aucun communiqué récent"

    return MacroRadarCard(
        category="BANQUES CENTRALES",
        title="Réserve Fédérale & FOMC",
        main_value=main_val,
        sub_value=sub_val,
        source="FRED / Federal Reserve (Officiel)",
        timestamp_utc=now_utc,
        observation_date=obs_u.observation_date or "",
        age_str="Publication officielle",
        status=status_str,
        is_ok=is_ok,
        details=[
            f"Fed Funds Target Range : {val_l or 'N/A'}% - {val_u or 'N/A'}%",
            f"Dernier communiqué : {fed_headline or 'N/A'}",
        ],
        degraded_reason="Données de taux directeurs non reçues de FRED" if not is_ok else "",
    )


def fetch_oil_card() -> MacroRadarCard:
    """Fenêtre 5 : Pétrole Brut WTI (CL=F)."""
    now_utc = datetime.now(UTC)
    try:
        ticker = yf.Ticker("CL=F")
        df = ticker.history(period="5d", interval="1d")
        if not df.empty:
            c = float(df["Close"].iloc[-1])
            p = float(df["Close"].iloc[-2]) if len(df) > 1 else c
            chg = c - p
            pct = (chg / p) * 100.0 if p else 0.0
            dt_str = str(df.index[-1]).split()[0]
            main_val = f"{c:.2f} $ ({chg:+.2f} / {pct:+.2f}%)"
            sub_val = f"Clôture officielle : {dt_str}"
            is_ok = True
            status_str = "OK"
            reason = ""
        else:
            main_val = "INDISPONIBLE"
            sub_val = "Historique vide"
            is_ok = False
            status_str = "DÉGRADÉ"
            reason = "Aucune cotation reçue pour CL=F"
            dt_str = ""
    except Exception as exc:
        main_val = "ERREUR RÉSEAU"
        sub_val = str(exc)[:50]
        is_ok = False
        status_str = "DÉGRADÉ"
        reason = f"Exception réseau CL=F: {exc}"
        dt_str = ""

    return MacroRadarCard(
        category="ÉNERGIE & MATIÈRES",
        title="Pétrole Brut WTI (CL=F)",
        main_value=main_val,
        sub_value=sub_val,
        source="Yahoo Finance (CL=F, NYMEX)",
        timestamp_utc=now_utc,
        observation_date=dt_str,
        age_str="Fin de séance NYMEX",
        status=status_str,
        is_ok=is_ok,
        details=[f"Dernier cours WTI : {main_val}", f"Date clôture : {dt_str}"],
        degraded_reason=reason,
    )


def fetch_dollar_card() -> MacroRadarCard:
    """Fenêtre 6 : Dollar Index (DXY, DX-Y.NYB)."""
    now_utc = datetime.now(UTC)
    try:
        ticker = yf.Ticker("DX-Y.NYB")
        df = ticker.history(period="5d", interval="1d")
        if not df.empty:
            c = float(df["Close"].iloc[-1])
            p = float(df["Close"].iloc[-2]) if len(df) > 1 else c
            chg = c - p
            pct = (chg / p) * 100.0 if p else 0.0
            dt_str = str(df.index[-1]).split()[0]
            main_val = f"{c:.2f} ({chg:+.2f} / {pct:+.2f}%)"

            is_weekend = now_utc.weekday() >= 5
            if is_weekend:
                sub_val = f"[Repli clôture vendredi {dt_str}] Marché ICE fermé"
                status_str = "DÉGRADÉ"
                is_ok = False
                reason = "Cotation directe fermée (week-end ICE/CME). Repli sur clôture officielle."
            else:
                sub_val = f"Dernière clôture officielle : {dt_str}"
                status_str = "OK"
                is_ok = True
                reason = ""
        else:
            main_val = "INDISPONIBLE"
            sub_val = "Historique vide"
            is_ok = False
            status_str = "DÉGRADÉ"
            reason = "Aucune donnée retournée pour DX-Y.NYB"
            dt_str = ""
    except Exception as exc:
        main_val = "ERREUR RÉSEAU"
        sub_val = str(exc)[:50]
        is_ok = False
        status_str = "DÉGRADÉ"
        reason = f"Exception réseau DX-Y.NYB: {exc}"
        dt_str = ""

    return MacroRadarCard(
        category="DEVISES & DOLLAR",
        title="Dollar Index (DXY)",
        main_value=main_val,
        sub_value=sub_val,
        source="Yahoo Finance (DX-Y.NYB, ICE)",
        timestamp_utc=now_utc,
        observation_date=dt_str,
        age_str="Fin de séance ICE",
        status=status_str,
        is_ok=is_ok,
        details=[f"Indice DXY : {main_val}", f"Date clôture : {dt_str}"],
        degraded_reason=reason,
    )


def fetch_live_news_wire(
    max_items_per_source: int = 5,
) -> NewsWireReport:
    """Récupère les actualités en direct influençant le Nasdaq (Fed RSS & Google News).

    Garantit une fraîcheur maximale (TTL <= 60s), un horodatage précis Alger et NY,
    et une identification claire des sources officielles avec gestion d'état dégradé.
    """
    now_utc = datetime.now(UTC)
    items: list[NewsWireItem] = []
    degraded_sources: list[str] = []

    # 1. Flux officiel des communiqués de presse de la Réserve Fédérale
    try:
        url_fed = "https://www.federalreserve.gov/feeds/press_all.xml"
        req_fed = urllib.request.Request(
            url_fed,
            headers={"User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)"},
        )
        with urllib.request.urlopen(req_fed, timeout=5) as r:
            root_fed = ET.fromstring(r.read())
            fed_items = list(root_fed.iter("item"))
            fed_count = 0
            for it in fed_items:
                if fed_count >= max_items_per_source:
                    break
                title = (it.findtext("title") or "").strip()
                if not is_relevant_fed_wire_item(title):
                    continue
                link = (it.findtext("link") or "").strip()
                pub_date_str = it.findtext("pubDate") or ""
                try:
                    dt = parsedate_to_datetime(pub_date_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    dt_utc = dt.astimezone(UTC)
                except Exception:
                    dt_utc = now_utc

                age = _format_age(max(0.0, (now_utc - dt_utc).total_seconds()))
                alg_str = dt_utc.astimezone(TZ_ALGIERS).strftime("%d/%m %H:%M Alger")
                et_str = dt_utc.astimezone(TZ_ET).strftime("%d/%m %H:%M ET")

                items.append(
                    NewsWireItem(
                        title=title,
                        link=link,
                        source="Federal Reserve (Conseil des Gouverneurs)",
                        tag="FED / TAUX",
                        tag_color="#818CF8",
                        timestamp_utc=dt_utc,
                        timestamp_algiers_str=alg_str,
                        timestamp_et_str=et_str,
                        age_str=age,
                        is_ok=True,
                        status="OK",
                    )
                )
                fed_count += 1
    except Exception as exc:
        log.warning("Échec flux RSS Fed: %s", exc)
        degraded_sources.append(f"Communiqués Fed (press_all.xml) : {exc}")

    # 2. Flux Google News (Requête US Macro & Nasdaq 100)
    try:
        url_gnews = (
            "https://news.google.com/rss/search?"
            "q=(Nasdaq+OR+FOMC+OR+\"Federal+Reserve\"+OR+CPI+OR+inflation)+when:2d"
            "&hl=en-US&gl=US&ceid=US:en"
        )
        req_gnews = urllib.request.Request(
            url_gnews,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req_gnews, timeout=5) as r:
            root_gnews = ET.fromstring(r.read())
            gnews_items = list(root_gnews.iter("item"))[:max_items_per_source]
            for it in gnews_items:
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                pub_date_str = it.findtext("pubDate") or ""
                s_elem = it.find("source")
                s_name = s_elem.text if s_elem is not None else "Presse Financière"

                try:
                    dt = parsedate_to_datetime(pub_date_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    dt_utc = dt.astimezone(UTC)
                except Exception:
                    dt_utc = now_utc

                age = _format_age(max(0.0, (now_utc - dt_utc).total_seconds()))
                alg_str = dt_utc.astimezone(TZ_ALGIERS).strftime("%d/%m %H:%M Alger")
                et_str = dt_utc.astimezone(TZ_ET).strftime("%d/%m %H:%M ET")

                items.append(
                    NewsWireItem(
                        title=title,
                        link=link,
                        source=f"Google News ({s_name})",
                        tag="MACRO / NASDAQ",
                        tag_color="#38BDF8",
                        timestamp_utc=dt_utc,
                        timestamp_algiers_str=alg_str,
                        timestamp_et_str=et_str,
                        age_str=age,
                        is_ok=True,
                        status="OK",
                    )
                )
    except Exception as exc:
        log.warning("Échec flux Google News: %s", exc)
        degraded_sources.append(f"Google News US Macro : {exc}")

    items.sort(key=lambda x: x.timestamp_utc, reverse=True)
    is_overall_ok = len(degraded_sources) == 0 and len(items) > 0

    return NewsWireReport(
        items=items,
        degraded_sources=degraded_sources,
        is_ok=is_overall_ok,
        fetched_at_utc=now_utc,
    )


def fetch_macro_news_radar() -> MacroNewsRadar:
    """Construit et retourne le radar complet des 6 actualités macro."""
    fetcher = DataFetcher()
    return MacroNewsRadar(
        rates=fetch_rates_card(fetcher),
        inflation=fetch_inflation_card(),
        mega_caps=fetch_mega_caps_card(),
        fed=fetch_fed_card(fetcher),
        oil=fetch_oil_card(),
        dollar=fetch_dollar_card(),
        fetched_at_utc=datetime.now(UTC),
    )
