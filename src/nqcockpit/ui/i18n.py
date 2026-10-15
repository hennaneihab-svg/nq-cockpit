"""Module d'internationalisation (i18n) Frontend pour THE COCKPIT (FR / EN).

Ce module gère exclusivement la couche de présentation (UI) sans modifier
aucune logique métier du backend. Il permet de basculer instantanément
l'intégralité de l'application entre le Français (FR) et l'Anglais (EN)
via un simple bouton.
"""
# ruff: noqa: E501

from __future__ import annotations

import re

import streamlit as st

LANG_SESSION_KEY = "lang"
SUPPORTED_LANGS = ("FR", "EN")
DEFAULT_LANG = "FR"


def get_lang() -> str:
    """Retourne la langue active ('FR' ou 'EN') depuis la session Streamlit."""
    try:
        lang = str(st.session_state.get(LANG_SESSION_KEY, DEFAULT_LANG)).upper()
        return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    except Exception:
        return DEFAULT_LANG


def set_lang(lang: str) -> None:
    """Définit la langue active ('FR' ou 'EN') dans la session Streamlit."""
    norm = str(lang).upper()
    st.session_state[LANG_SESSION_KEY] = (
        norm if norm in SUPPORTED_LANGS else DEFAULT_LANG
    )


def toggle_lang() -> None:
    """Bascule instantanément entre Français ('FR') et Anglais ('EN')."""
    current = get_lang()
    set_lang("EN" if current == "FR" else "FR")


def t(fr: str, en: str) -> str:
    """Retourne le texte dans la langue active (FR ou EN)."""
    return en if get_lang() == "EN" else fr


def render_lang_selector(key_prefix: str = "global") -> str:
    """Affiche le bouton de bascule directe FR <-> EN dans la barre latérale."""
    lang = get_lang()
    btn_label = (
        "🇬🇧 Switch to English (EN)"
        if lang == "FR"
        else "🇫🇷 Traduire en Français (FR)"
    )
    badge_html = (
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "background:#0f172a;border:1px solid #334155;border-radius:4px;"
        "padding:4px 10px;margin-bottom:6px;font-family:JetBrains Mono,monospace;font-size:0.74rem;'>"
        f"<span style='color:#94a3b8;'>{t('LANGUE ACTIVE', 'ACTIVE LANGUAGE')}</span>"
        f"<span style='color:#00e676;font-weight:700;'>"
        f"{'🇫🇷 FRANÇAIS (FR)' if lang == 'FR' else '🇬🇧 ENGLISH (EN)'}</span>"
        "</div>"
    )
    st.markdown(badge_html, unsafe_allow_html=True)
    st.button(
        btn_label,
        key=f"{key_prefix}_lang_toggle_btn",
        on_click=toggle_lang,
        use_container_width=True,
        type="primary",
    )
    return get_lang()


# ---------------------------------------------------------------------------
# Traduction à la volée des textes dynamiques issus des moteurs backend
# ---------------------------------------------------------------------------

_EXACT_MAP_FR_TO_EN: dict[str, str] = {
    # Catégories et Titres des 6 cartes Macro Radar (news_radar.py)
    "TAUX & RENDEMENTS": "RATES & YIELDS",
    "Taux US 10 ans & 2 ans": "US 10Y & 2Y Yields",
    "INFLATION & PRIX": "INFLATION & PRICES",
    "Inflation US (CPI YoY)": "US Inflation (CPI YoY)",
    "MEGA-CAPS TECH": "TECH MEGA-CAPS",
    "Résultats Megacaps": "Mega-Cap Earnings",
    "BANQUES CENTRALES": "CENTRAL BANKS",
    "Réserve Fédérale & FOMC": "Federal Reserve & FOMC",
    "ÉNERGIE & MATIÈRES": "ENERGY & COMMODITIES",
    "Pétrole Brut WTI (CL=F)": "WTI Crude Oil (CL=F)",
    "DEVISES & DOLLAR": "FX & DOLLAR",
    "Dollar Index (DXY)": "US Dollar Index (DXY)",
    # Cartes Macro Radar (statuts et valeurs fixes)
    "PROCHAIN ÉVÉNEMENT US": "NEXT US EVENT",
    "FENÊTRE NO-TRADE": "NO-TRADE WINDOW",
    "RÉGIME VOLATILITÉ": "VOLATILITY REGIME",
    "BIAIS TAUX (US10Y / DXY)": "RATES BIAS (US10Y / DXY)",
    "GAMMA & NIVEAUX CLÉS": "GAMMA & KEY LEVELS",
    "STATUT SESSION": "SESSION STATUS",
    "AUCUN ÉVÉNEMENT MAJEUR": "NO MAJOR EVENT",
    "Agenda calme — aucun événement High/Medium à venir": "Quiet calendar — no upcoming High/Medium events",
    "CALENDRIER DÉGRADÉ": "CALENDAR DEGRADED",
    "DÉGRADÉ": "DEGRADED",
    "CRITIQUE": "CRITICAL",
    "IMMÉDIAT": "IMMEDIATE",
    "À VENIR": "UPCOMING",
    "CALME": "CLEAR",
    "FENÊTRE ACTIVE": "WINDOW ACTIVE",
    "NO-TRADE EN COURS": "NO-TRADE ACTIVE",
    "SOURCE ABSENTE": "SOURCE MISSING",
    "Calendrier indisponible — prudence requise": "Calendar unavailable — caution required",
    "AUCUNE FENÊTRE": "NO ACTIVE WINDOW",
    "INCONNU": "UNKNOWN",
    "Aucune fenêtre no-trade programmée": "No scheduled no-trade window",
    "VIX INDISPONIBLE": "VIX UNAVAILABLE",
    "VOL HAUTE": "HIGH VOL",
    "VOL BASSE": "LOW VOL",
    "NORMAL": "NORMAL",
    "ÉLEVÉ": "HIGH",
    "BAS": "LOW",
    "TAUX INDISPONIBLES": "RATES UNAVAILABLE",
    "Sources US10Y et DXY dégradées": "US10Y and DXY sources degraded",
    "POSITIF": "POSITIVE",
    "NÉGATIF": "NEGATIVE",
    "NEUTRE": "NEUTRAL",
    "INDISPONIBLE": "UNAVAILABLE",
    "ERREUR RÉSEAU": "NETWORK ERROR",
    "SESSION BLOQUÉE": "SESSION LOCKED",
    "HORS FENÊTRE": "OUT OF WINDOW",
    "ATTENTE": "STANDBY",
    "AUTORISÉ": "AUTHORIZED",
    "PRÊT": "READY",
    "Aucune violation": "No violations",
    "Aucun": "None",
    "Aucun Tier 1 imminent": "No imminent Tier 1 event",
    "Aucun événement Tier 1 imminent": "No imminent Tier 1 event",
    "imminent": "imminent",
    "VOLATILITÉ COMPRIMÉE": "COMPRESSED VOLATILITY",
    "VOLATILITÉ ÉLEVÉE": "HIGH VOLATILITY",
    "VOLATILITÉ NORMALE": "NORMAL VOLATILITY",
    # Live wire tags & sources
    "FED / TAUX": "FED / RATES",
    "MACRO / NASDAQ": "MACRO / NASDAQ",
    "Federal Reserve (Conseil des Gouverneurs)": "Federal Reserve (Board of Governors)",
    "Presse Financière": "Financial Press",
    "Scan en direct": "Live scan",
    "Publication officielle": "Official release",
    "Fin de séance NYMEX": "NYMEX session close",
    "Fin de séance ICE": "ICE session close",
    "Données incomplètes": "Incomplete data",
    "Calcul YoY impossible": "YoY calculation unavailable",
    "Historique vide": "Empty history",
    "Calendrier non reçu": "Calendar not received",
    "Aucun communiqué récent": "No recent press release",
    "Fourchette Fed : INDISPONIBLE": "Fed Target Range: UNAVAILABLE",
    "FRED / Federal Reserve (Officiel)": "FRED / Federal Reserve (Official)",
    # Composants & santé (profile/engine.py)
    "Calendrier Événements (P05/P06)": "Events Calendar (P05/P06)",
    "Contexte Macro & Cross-Asset (P07)": "Macro & Cross-Asset Context (P07)",
    "Overnight NQ CME (P07)": "Overnight NQ CME (P07)",
    "Niveaux Gamma & Options NDX (P04)": "NDX Gamma & Options Levels (P04)",
    "Niveaux de structure incomplets": "Incomplete structure levels",
    "Moteur non exécuté": "Engine not executed",
    "OK": "OK",
    # Noms et descriptions des niveaux clés (profile/engine.py)
    "Expected Move Haut (+1σ)": "Expected Move High (+1σ)",
    "Expected Move Bas (-1σ)": "Expected Move Low (-1σ)",
    "Plus forte concentration d'OI Call (résistance dealer)": "Highest Call OI concentration (dealer resistance)",
    "Borne haute d'amplitude statistique 1σ": "1σ statistical upper amplitude bound",
    "Sommet de la session de nuit CME (18:00 - 09:30 ET)": "CME overnight session high (18:00 - 09:30 ET)",
    "Niveau pivot de basculement de régime gamma institutionnel": "Institutional gamma regime flip pivot",
    "Creux de la session de nuit CME (18:00 - 09:30 ET)": "CME overnight session low (18:00 - 09:30 ET)",
    "Borne basse d'amplitude statistique 1σ": "1σ statistical lower amplitude bound",
    "Plus forte concentration d'OI Put (support dealer)": "Highest Put OI concentration (dealer support)",
    # Discipline & Checklist
    "Journée terminée après le 1er trade gagnant (règle active).": "Session ended after 1st winning trade (rule active).",
    "Fenêtre horaire autorisée non validée.": "Authorized time window not confirmed.",
    "Absence de fenêtre no-trade macro non confirmée.": "Absence of macro no-trade window not confirmed.",
    "Niveau structurel ou GEX non identifié.": "Structural or GEX level not identified.",
    "Stop-loss défini et calcul de taille non confirmés.": "Defined stop-loss and position sizing not confirmed.",
    "Vérification anti-tilt (pas de revenge trade) non confirmée.": "Anti-tilt check (no revenge trade) not confirmed.",
    "Distance stop invalide (doit être > 0 points).": "Invalid stop distance (must be > 0 points).",
    "Montant de risque invalide (doit être > 0 $).": "Invalid risk amount (must be > $0).",
    # Journal & Coaching
    "Aucune fuite identifiable sur cet échantillon.": "No identifiable leak on this sample.",
    "Aucune violation dominante détectée — maintenir la rigueur.": "No dominant violation detected — maintain discipline.",
    "Continuer à documenter chaque trade pour affiner l'analyse.": "Continue documenting every trade to refine analysis.",
    "Limiter la série de pertes : arrêter la séance après 2 pertes consécutives.": "Cap loss streaks: stop the session after 2 consecutive losses.",
    "Maintenir les niveaux actuels de discipline sur la prochaine période.": "Maintain current discipline levels over the next period.",
    "(sans tag)": "(untagged)",
    "(aucun événement)": "(no event)",
    "Lun": "Mon",
    "Mar": "Tue",
    "Mer": "Wed",
    "Jeu": "Thu",
    "Ven": "Fri",
    "Sam": "Sat",
    "Dim": "Sun",
    # Profile & Playbook & Forecast & MT5 exact strings
    "range / trend modéré": "range / moderate trend",
    "AUTORISÉ (sous conditions de setup)": "ALLOWED (subject to setup conditions)",
    "ACTIF": "ACTIVE",
    "INACTIF": "INACTIVE",
    "Événement RED / Tampon post-événement": "RED Event / Post-Event Buffer",
    "Compression entre murs gamma": "Gamma Wall Compression",
    "Donnée de marché périmée": "Stale Market Data",
    "Base NDX/NQ anormale": "Abnormal NDX/NQ Basis",
    "Limite de perte journalière (-2R)": "Daily Loss Limit (-2R)",
    "Toutes sources (P04-P07)": "All sources (P04-P07)",
    "P09 Journal (en attente)": "P09 Journal (pending)",
    "Utilisation des repères de secours": "Using fallback benchmarks",
    "calibré": "calibrated",
    "non calibré": "uncalibrated",
    "Expected move de base non disponible": "Base expected move unavailable",
    "Connecté au terminal MT5": "Connected to MT5 terminal",
    "Package Python MetaTrader5 non disponible dans l'environnement.": "Python MetaTrader5 package not available in environment.",
    "Package Python MetaTrader5 non disponible.": "Python MetaTrader5 package not available.",
}

_SUBSTRING_REPLACEMENTS_FR_TO_EN: list[tuple[str, str]] = [
    # Briefing Markdown headings & labels (briefing/engine.py)
    ("# Briefing Pré-Séance NQ — ", "# NQ Pre-Session Briefing — "),
    ("# BRIEFING PRÉ-SESSION NQ — ", "# NQ PRE-SESSION BRIEFING — "),
    ("## 1. Statut de Séance & Risque", "## 1. Session Status & Risk"),
    ("- **Horodatage d'émission (Alger) :** ", "- **Issued Timestamp (Algiers):** "),
    ("- **Horodatage marché (New York) :** ", "- **Market Timestamp (New York):** "),
    ("- **Statut d'intégrité global :** ", "- **Overall Integrity Status:** "),
    ("## 1. Profil de Séance & Scénarios Conditionnels (P08)", "## 1. Session Profile & Conditional Scenarios (P08)"),
    ("- **Type de Profil Identifié :** ", "- **Identified Profile Type:** "),
    ("- **Régime Volatilité :** ", "- **Volatility Regime:** "),
    ("- **Régime Gamma :** ", "- **Gamma Regime:** "),
    ("### Scénarios Conditionnels :", "### Conditional Scenarios:"),
    ("  - *Condition :* ", "  - *Condition:* "),
    ("  - *Plan :* ", "  - *Plan:* "),
    ("- *Condition :* ", "- *Condition:* "),
    ("- *Plan :* ", "- *Plan:* "),
    ("> Profil de séance non disponible (Statut DÉGRADÉ).", "> Session profile unavailable (DEGRADED Status)."),
    ("## 2. Niveaux Gamma & Expected Move NQ (P02/P04)", "## 2. NQ Gamma Levels & Expected Move (P02/P04)"),
    ("- **Gamma Flip NQ :** ", "- **NQ Gamma Flip:** "),
    ("- **Call Wall NQ (Résistance Opérative) :** ", "- **NQ Call Wall (Operative Resistance):** "),
    ("- **Put Wall NQ (Support Opératif) :** ", "- **NQ Put Wall (Operative Support):** "),
    ("- **Expected Move Journalier :** ", "- **Daily Expected Move:** "),
    ("- **Bande Expected Move NQ :** ", "- **NQ Expected Move Band:** "),
    ("> Niveaux de positionnement optionnel non disponibles (Statut DÉGRADÉ).", "> Options positioning levels unavailable (DEGRADED Status)."),
    ("## 3. Radar d'Événements Macro & Risque (P03)", "## 3. Macro Events & Risk Radar (P03)"),
    ("- **Niveau de Risque Événementiel :** ", "- **Event Risk Level:** "),
    ("- **Constat Factuel :** ", "- **Factual Assessment:** "),
    ("- **Prochain Événement :** ", "- **Next Event:** "),
    ("> Évaluation des risques événementiels non disponible (Statut DÉGRADÉ).", "> Event risk assessment unavailable (DEGRADED Status)."),
    ("## 4. Playbook Événementiel & Repères (P06)", "## 4. Event Playbook & Benchmarks (P06)"),
    ("- **Événement Repère :** ", "- **Benchmark Event:** "),
    ("- **Statut du Champ :** ", "- **Field Status:** "),
    ("- **Scénarios de Réaction Événementielle :**", "- **Event Reaction Scenarios:**"),
    ("Aucun événement majeur nécessitant une fiche de playbook sur la séance.", "No major event requiring a playbook card for this session."),
    ("## 5. Prévisions d'Amplitude & Contexte Macro (P07)", "## 5. Amplitude Forecast & Macro Context (P07)"),
    ("- **État de Calibration :** ", "- **Calibration Status:** "),
    ("- **Amplitude Prévue (1-Sigma) :** ", "- **Forecasted Amplitude (1-Sigma):** "),
    ("- **Probabilités par Type de Journée :**", "- **Probabilities by Day Type:**"),
    ("> Prévision d'amplitude non disponible (Statut DÉGRADÉ).", "> Amplitude forecast unavailable (DEGRADED Status)."),
    ("## 6. Drapeaux No-Trade & Alertes (P05/P08)", "## 6. No-Trade Flags & Alerts (P05/P08)"),
    ("✅ **Aucun drapeau No-Trade actif.** Trading autorisé sous réserve de validation P09.", "✅ **No active No-Trade flag.** Trading authorized subject to P09 checklist validation."),
    ("⚠️ **Drapeaux No-Trade Actifs :**", "⚠️ **Active No-Trade Flags:**"),
    ("(Sévérité : ", "(Severity: "),
    ("## 7. Anti-Biais & Responsabilité", "## 7. Anti-Bias & Disclaimer"),
    ("> Ce briefing est un outil d'aide à la décision factuel et non directionnel.", "> This briefing is a factual, non-directional decision-support tool."),
    ("> Il ne constitue en aucun cas un conseil en investissement ou un signal de trading.", "> It does not constitute investment advice or a trading signal under any circumstances."),
    ("> L'exécution des trades reste sous la responsabilité exclusive de l'opérateur.", "> Trade execution remains the sole responsibility of the operator."),
    ("Événement Tier 1 imminent ou en cours (Statut ROUGE)", "Imminent or active Tier 1 event (RED Status)"),
    ("DayProfile indisponible", "DayProfile unavailable"),
    ("EventRisk indisponible", "EventRisk unavailable"),
    ("Niveaux gamma en statut ", "Gamma levels in status "),
    ("GEMINI_API_KEY absente dans .env — fallback texte brut", "GEMINI_API_KEY missing in .env — plain-text fallback"),
    ("Réponse API Gemini vide (aucun candidat généré) — fallback texte brut", "Empty Gemini API response (no candidate generated) — plain-text fallback"),
    ("Telegram non configuré (TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID absent)", "Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing)"),
    ("[DRY-RUN] Envoi Telegram prévisualisé avec succès", "[DRY-RUN] Telegram send previewed successfully"),
    ("Message Telegram transmis avec succès", "Telegram message sent successfully"),
    ("Message Telegram transmis (texte brut sans Markdown)", "Telegram message sent (plain text without Markdown)"),
    ("Erreur API Telegram", "Telegram API Error"),
    ("Inconnu", "Unknown"),
    # Profile & Events & Playbook & Forecast dynamic strings
    ("range / trend modéré", "range / moderate trend"),
    ("Régime gamma positif (dealer long gamma favorisant le mean-reversion)", "Positive gamma regime (dealer long gamma favoring mean-reversion)"),
    ("Régime gamma négatif (dealer short gamma favorisant les mouvements d'expansion)", "Negative gamma regime (dealer short gamma favoring expansion moves)"),
    (" : probabilité accrue de séance comprimée", ": higher probability of compressed session"),
    ("VIX bas (", "Low VIX ("),
    ("Risque événementiel ou volatilité élevée : probabilité accrue de séance expansive", "Event risk or high volatility: higher probability of expansive session"),
    ("Volatilité normale : probabilités statistiques réparties selon le test de Wilson", "Normal volatility: statistical probabilities distributed according to Wilson test"),
    ("Composants dégradés : ", "Degraded components: "),
    ("Aucun drapeau bloquant actif. Respecter impérativement les règles de Kill Zone et la limite de 2 trades/jour.", "No active blocking flag. Strictly follow Kill Zone rules and the 2 trades/day limit."),
    (" drapeau(x) bloquant(s) actif(s) : ", " active blocking flag(s): "),
    ("AUTORISÉ (sous conditions de setup)", "ALLOWED (subject to setup conditions)"),
    ("DÉGRADÉ: module P09 (journal) non encore livré — non bloquant", "DEGRADED: P09 module (journal) not yet delivered — non-blocking"),
    ("Utilisation des repères de secours", "Using fallback benchmarks"),
    ("Aucun événement significatif détecté dans les fenêtres de trading.", "No significant event detected in the trading windows."),
    ("Aucun événement Tier 1 imminent", "No imminent Tier 1 event"),
    (" — couvre la fenêtre ", " — overlaps window "),
    (" (±tampon ", " (±buffer "),
    (" — dans la zone AMBER de ", " — inside AMBER zone of "),
    (" — proche de la fenêtre ", " — near window "),
    ("Prochain : ", "Next: "),
    ("Range nuit = ", "Overnight range = "),
    ("Écart basis (", "Basis spread ("),
    (") vs synthétique (", ") vs synthetic ("),
    (" périmé (", " stale ("),
    ("échantillon insuffisant (", "insufficient sample ("),
    ("échantillon suffisant (", "sufficient sample ("),
    (" séances requises)", " sessions required)"),
    (" séances >= ", " sessions >= "),
    ("Plus forte concentration d'OI Call (résistance dealer)", "Highest Call OI concentration (dealer resistance)"),
    ("Borne haute d'amplitude statistique 1σ", "1σ statistical amplitude upper bound"),
    ("Sommet de la session de nuit CME (18:00 - 09:30 ET)", "CME overnight session high (18:00 - 09:30 ET)"),
    ("Niveau pivot de basculement de régime gamma institutionnel", "Institutional gamma regime flip pivot level"),
    ("Creux de la session de nuit CME (18:00 - 09:30 ET)", "CME overnight session low (18:00 - 09:30 ET)"),
    ("Borne basse d'amplitude statistique 1σ", "1σ statistical amplitude lower bound"),
    ("Plus forte concentration d'OI Put (support dealer)", "Highest Put OI concentration (dealer support)"),
    ("Sources dégradées : ", "Degraded sources: "),
    ("VOLATILITÉ NORMALE", "NORMAL VOLATILITY"),
    ("VOLATILITÉ ÉLEVÉE", "HIGH VOLATILITY"),
    ("VOLATILITÉ COMPRIMÉE", "COMPRESSED VOLATILITY"),
    ("Expected Move Haut (+1σ)", "Expected Move High (+1σ)"),
    ("Expected Move Bas (-1σ)", "Expected Move Low (-1σ)"),
    ("Expected Move Haut", "Expected Move High"),
    ("Expected Move Bas", "Expected Move Low"),
    # MT5 Client dynamic strings (broker/mt5_client.py)
    ("Package Python MetaTrader5 non disponible dans l'environnement.", "Python MetaTrader5 package not available in environment."),
    ("Package Python MetaTrader5 non disponible.", "Python MetaTrader5 package not available."),
    ("Erreur d'initialisation MT5 : ", "MT5 initialization error: "),
    ("Terminal MT5 non détecté ou non lancéé (", "MT5 terminal not detected or not running ("),
    ("Terminal MT5 non détecté ou non lancé (", "MT5 terminal not detected or not running ("),
    ("Échec d'authentification MT5 pour le compte ", "MT5 authentication failed for account "),
    ("ÉÉchec d'authentification MT5 pour le compte ", "MT5 authentication failed for account "),
    ("Connecté au terminal MT5", "Connected to MT5 terminal"),
    ("Connexion au terminal perdue (", "Terminal connection lost ("),
    ("Connexion MT5 inactive : ", "MT5 connection inactive: "),
    (" ignorée (hors NQ)", " ignored (outside NQ)"),
    ("non défini", "not set"),
    # Macro Radar dynamic values & reasons (news_radar.py)
    ("Yahoo ^TNX/10 [différé 15 min]", "Yahoo ^TNX/10 [15m delayed]"),
    ("FRED (cache local)", "FRED (local cache)"),
    ("Taux 2 ans : FRED direct indisponible, repli cache local ", "2Y Yield: Direct FRED unavailable, local cache fallback "),
    ("Taux 2 ans : FRED direct indisponible, aucune observation en cache", "2Y Yield: Direct FRED unavailable, no cached observation"),
    ("Taux 10 ans : repli Yahoo Finance ^TNX cotation différée de 15 min", "10Y Yield: Yahoo Finance ^TNX fallback (15-min delayed quote)"),
    ("(pentifiée)", "(steepened)"),
    ("(inversée)", "(inverted)"),
    ("Spread calcul impossible [donnée incomplète]", "Spread calculation unavailable [incomplete data]"),
    ("Historique insuffisant pour calcul annuel", "Insufficient history for YoY calculation"),
    ("Historique FRED CPIAUCSL < 13 mois", "FRED CPIAUCSL history < 13 months"),
    ("Mois correspondant an n-1 introuvable", "Prior-year reference month not found"),
    ("Pas de valeur CPI pour ", "No CPI value for "),
    ("Indice: ", "Index: "),
    ("Indice : ", "Index: "),
    ("(Réf: ", "(Ref: "),
    ("Mois: ", "Month: "),
    ("Plus proche : ", "Nearest: "),
    (", dans ", ", in "),
    (" jours)", " days)"),
    ("Dernier : ", "Latest: "),
    ("(passé il y a ", "(passed "),
    ("Échec récupération pour: ", "Fetch failed for: "),
    ("Fourchette FOMC : ", "FOMC Target Range: "),
    ("Fourchette Fed : INDISPONIBLE", "Fed Target Range: UNAVAILABLE"),
    ("Données de taux directeurs non reçues de FRED", "Policy rate data not received from FRED"),
    ("Clôture officielle : ", "Official close: "),
    ("Dernière clôture officielle : ", "Last official close: "),
    ("Aucune cotation reçue pour CL=F", "No quote received for CL=F"),
    ("Exception réseau CL=F: ", "Network exception CL=F: "),
    ("[Repli clôture vendredi ", "[Friday close fallback "),
    ("] Marché ICE fermé", "] ICE market closed"),
    ("Cotation directe fermée (week-end ICE/CME). Repli sur clôture officielle.", "Live quote closed (ICE/CME weekend). Official close fallback."),
    ("Aucune donnée retournée pour DX-Y.NYB", "No data returned for DX-Y.NYB"),
    ("Exception réseau DX-Y.NYB: ", "Network exception DX-Y.NYB: "),
    ("Communiqués Fed (press_all.xml) : ", "Fed Press Releases (press_all.xml): "),
    ("Source indisponible ou marché fermé", "Source unavailable or market closed"),
    # Scenarios (build_scenario_map in profile/engine.py)
    ("Si le prix s'établit au-dessus du Gamma Flip (", "If price establishes above the Gamma Flip ("),
    (") et s'y maintient", ") and holds"),
    ("alors régime d'amortissement dealer (Mean Reversion) : observer les replis vers la VWAP et éviter les poursuites impulsives tardives.", "then dealer dampening regime (Mean Reversion): watch pullbacks toward VWAP and avoid chasing late impulsive moves."),
    ("Régime gamma positif : les market makers vendent la force et achètent les faiblesses.", "Positive gamma regime: market makers sell strength and buy weakness."),
    ("Si le prix casse franchement et clôture sous le Gamma Flip (", "If price breaks cleanly and closes below the Gamma Flip ("),
    (") avec accélération", ") with acceleration"),
    ("alors passage en régime de volatilité expansive : le hedging dealer devient pro-cyclique (chasse à la liquidité, amplitude accrue, réduire les tailles).", "then transition to expansive volatility regime: dealer hedging becomes pro-cyclical (liquidity sweeps, wider swings, reduce size)."),
    ("Régime gamma négatif : risque de cascade d'ordres stop et d'amplification des amplitudes.", "Negative gamma regime: risk of stop cascades and amplified swings."),
    ("Si le prix teste le Call Wall (", "If price tests the Call Wall ("),
    (") avec essoufflement du flux et absorption visible au carnet", ") with flow exhaustion and visible order-book absorption"),
    ("alors résistance majeure attendue par couverture vendeuse dealer : observer un setup de rejet ou d'absorption.", "then major resistance expected from dealer selling hedge: look for a rejection or absorption setup."),
    ("Plus gros strike d'Open Interest Call : zone naturelle de friction institutionnelle.", "Largest Call Open Interest strike: natural institutional friction zone."),
    ("Si le prix traverse le Call Wall (", "If price breaks through the Call Wall ("),
    (") avec fort volume institutionnel et acceptation", ") with strong institutional volume and acceptance"),
    ("alors risque de squeeze de delta dealer : ne pas anticiper de retournement contre-tendance tant qu'aucune structure de rejet M5/M15 n'est validée.", "then risk of dealer delta squeeze: do not fade counter-trend until an M5/M15 rejection structure is confirmed."),
    ("Débouclage forcé possible des vendeurs d'options si le mur cède.", "Potential forced covering by option sellers if the wall gives way."),
    ("Si le prix teste le Put Support (", "If price tests the Put Support ("),
    (") avec épuisement vendeur et absorption des stops", ") with seller exhaustion and stop absorption"),
    ("alors zone de soutien dealer majeure : observer la formation d'un setup de retournement (CHoCH/BOS) pour un retour statistique vers la zone médiane.", "then major dealer support zone: watch for a reversal structure (CHoCH/BOS) for a statistical rotation toward mid-range."),
    ("Plus grand strike d'Open Interest Put : zone de rebond technique statistiquement défendue.", "Largest Put Open Interest strike: statistically defended technical bounce zone."),
    ("Si enfoncement soutenu sous le Put Support (", "If sustained breakdown below Put Support ("),
    (") sans réintégration immédiate", ") without immediate reclaim"),
    ("alors rupture de support institutionnel : risque d'accélération par hedging vendeur des dealers, suspendre les achats aveugles.", "then institutional support breakdown: risk of downside acceleration from dealer selling hedge, suspend blind buying."),
    ("En cas de cassure de mur bas, l'expected move journalier devient le prochain repère.", "On a lower wall breakdown, the daily expected move becomes the next benchmark."),
    ("Si test de l'Overnight High (", "If test of the Overnight High ("),
    (") avec rejet immédiat (balayage de liquidité sans acceptation)", ") with immediate rejection (liquidity sweep without acceptance)"),
    ("alors scénario de liquidity sweep : observer une réintégration du range de nuit en direction de la VWAP de session.", "then liquidity sweep scenario: watch for re-entry into the overnight range toward session VWAP."),
    ("Les extrêmes de nuit concentrent les ordres stop des participants asiatiques et européens.", "Overnight extremes concentrate stop orders from Asian and European participants."),
    ("Si franchissement de l'Overnight High (", "If breakout above the Overnight High ("),
    (") avec ré-accumulation au-dessus du niveau", ") with re-accumulation above the level"),
    ("alors décalage structurel d'extension : surveiller le Call Wall et la borne haute de l'Expected Move comme prochains repères.", "then structural extension shift: monitor the Call Wall and Expected Move upper bound as next benchmarks."),
    ("Acceptation hors du range overnight = structure d'extension de session.", "Acceptance outside the overnight range = session extension structure."),
    ("Si test de l'Overnight Low (", "If test of the Overnight Low ("),
    (") avec rejet rapide (sweep de la liquidité basse)", ") with fast rejection (downside liquidity sweep)"),
    ("alors observer la réintégration du range avec un setup de retour vers l'équilibre de session.", "then watch for range reclaim with a rotation setup back toward session equilibrium."),
    ("Balayage classique des stops sous les bas de nuit.", "Classic stop sweep below overnight lows."),
    ("Si clôture et travail sous l'Overnight Low (", "If close and acceptance below the Overnight Low ("),
    (") sans réaction acheteuse", ") without buyer response"),
    ("alors décalage structurel d'extension : surveiller le Put Support et la borne basse de l'Expected Move.", "then structural extension shift: monitor Put Support and Expected Move lower bound."),
    ("Continuation hors du range de nuit.", "Continuation outside the overnight range."),
    ("Si le prix atteint la borne haute de l'Expected Move (", "If price reaches the Expected Move upper bound ("),
    ("alors épuisement statistique d'amplitude journalière (68 % des séances contenues) : prudence maximale sur les breakouts impulsifs, risque élevé de fausse sortie sans nouvelle.", "then statistical daily amplitude exhaustion (68% of sessions contained): maximum caution on impulsive breakouts, high risk of false breakout without news."),
    ("Statistiquement, l'extension au-delà de 1σ requiert un catalyseur Tier 1 non pricé.", "Statistically, extension beyond 1σ requires an unpriced Tier 1 catalyst."),
    ("Si le prix atteint la borne basse de l'Expected Move (", "If price reaches the Expected Move lower bound ("),
    ("alors épuisement statistique d'amplitude attendue : surveiller un ralentissement du momentum et éviter de vendre au plus bas de l'amplitude attendue.", "then statistical expected amplitude exhaustion: watch for momentum deceleration and avoid selling at the bottom of the expected range."),
    ("Borne 1-sigma CBOE ACT/365.", "CBOE ACT/365 1-sigma bound."),
    # NoTradeFlags & ComponentHealth (profile/engine.py)
    ("Événement économique Tier 1 actif ou dans le tampon post-événement : ", "Active Tier 1 economic event or within post-event buffer: "),
    ("Aucun événement économique Tier 1 en cours ni dans le tampon post-événement", "No active Tier 1 economic event or post-event buffer"),
    ("Distance entre murs gamma suffisante pour opérer", "Sufficient distance between gamma walls to operate"),
    ("Prix coincé entre deux murs gamma à moins de ", "Price compressed between two gamma walls within "),
    ("Toutes les sources sont fraîches et dans les seuils", "All data sources are fresh and within thresholds"),
    ("Écart de base NDX/NQ et parité synthétique normaux", "Normal NDX/NQ basis spread and synthetic parity"),
    ("Limite de perte journalière atteinte ", "Daily loss limit reached "),
    ("Pertes du jour sous contrôle ", "Daily losses under control "),
    ("Suivi des pertes P09 non disponible (statut dégradé sans blocage du trading)", "P09 loss tracking unavailable (degraded status without blocking trading)"),
    ("Calendrier Événements (P05/P06)", "Events Calendar (P05/P06)"),
    ("Contexte Macro & Cross-Asset (P07)", "Macro & Cross-Asset Context (P07)"),
    ("Overnight NQ CME (P07)", "Overnight NQ CME (P07)"),
    ("Niveaux Gamma & Options NDX (P04)", "NDX Gamma & Options Levels (P04)"),
    ("DÉGRADÉ: radar inaccessible", "DEGRADED: radar unreachable"),
    ("DÉGRADÉ: cours indisponibles", "DEGRADED: quotes unavailable"),
    ("DÉGRADÉ: échec calcul macro", "DEGRADED: macro calculation failed"),
    ("DÉGRADÉ: échec overnight", "DEGRADED: overnight calculation failed"),
    ("DÉGRADÉ: aucun snapshot disponible", "DEGRADED: no snapshot available"),
    ("DÉGRADÉ: ", "DEGRADED: "),
    ("DÉGRADÉ", "DEGRADED"),
    ("données âgées de ", "data aged "),
    ("différée ou marché fermé", "delayed or market closed"),
    ("source CBOE", "CBOE source"),
    ("Risque ", "Risk "),
    # Discipline lock & blocking reasons (discipline/engine.py & risk.py)
    ("Limite de perte journalière atteinte (", "Daily loss limit reached ("),
    ("). Séance verrouillée.", "). Session locked."),
    ("Trade 2 annulé : le premier trade de la séance a terminé en perte (règle stricte anti-revenge trading).", "Trade 2 cancelled: the first trade of the session ended in a loss (strict anti-revenge trading rule)."),
    ("Nombre maximal de trades dépassé (", "Maximum number of trades exceeded ("),
    (" trades enregistrés). Séance terminée.", " trades recorded). Session ended."),
    ("Nombre maximal de trades atteint (", "Maximum number of trades reached ("),
    ("). Séance terminée.", "). Session ended."),
    ("Pause obligatoire active après SL : reste ", "Mandatory post-SL cooldown active: "),
    (" avant toute nouvelle entrée (cooldown ", " remaining before any new entry (cooldown "),
    ("Hors fenêtre horaire autorisée. Fenêtres d'Alger : ", "Outside authorized trading window. Algiers windows: "),
    ("Événement Tier 1 imminent ou en cours (statut ROUGE). Trading strictement interdit.", "Imminent or active Tier 1 event (RED status). Trading strictly prohibited."),
    ("Profil de séance P08 non consulté (confirmation requise).", "P08 session profile not reviewed (confirmation required)."),
    ("Plan de trade manquant ou insuffisant (au moins 10 caractères requis).", "Trading plan missing or insufficient (at least 10 characters required)."),
    ("Calcul de taille de position non exécuté.", "Position sizing calculation not executed."),
    ("Taille de position nulle (0 contrat) : ", "Zero position size (0 contracts): "),
    ("budget insuffisant", "insufficient budget"),
    ("Erreur de sizing : ", "Sizing error: "),
    ("Capital du compte nul ou négatif.", "Account capital is zero or negative."),
    ("Distance de Stop Loss invalide (doit être > 0 points).", "Invalid Stop-Loss distance (must be > 0 points)."),
    ("Budget insuffisant (", "Insufficient budget ("),
    (") pour 1 contrat (nécessite ", ") for 1 contract (requires "),
    (" pour ", " for "),
    (" pts de stop).", " pts stop)."),
    ("Alerte Prop Firm : la perte journalière potentielle (", "Prop Firm Alert: potential daily loss ("),
    (") dépasserait la limite fixée (", ") would exceed the set limit ("),
    ("Alerte Prop Firm : le risque de ce trade (", "Prop Firm Alert: this trade's risk ("),
    (") dépasse le drawdown max toléré (", ") exceeds the max allowed drawdown ("),
    ("Quota de trades atteint (", "Trade quota reached ("),
    ("Perte journalière maximale atteinte (", "Maximum daily loss reached ("),
    ("Série de pertes maximale atteinte (", "Maximum loss streak reached ("),
    (" pertes consécutives).", " consecutive losses)."),
    ("Cooldown post-SL actif : ", "Post-SL cooldown active: "),
    (" min restantes.", " min remaining."),
    ("Fenêtre no-trade événementielle active : ", "Event no-trade window active: "),
    ("Hors fenêtre d'exécution autorisée (heure actuelle : ", "Outside authorized execution window (current time: "),
    ("Ratios R:R insuffisants : ", "Insufficient R:R ratio: "),
    ("Stop invalide : ", "Invalid stop: "),
    ("Risque par contrat MNQ (", "Risk per MNQ contract ("),
    (") supérieur au budget de risque (", ") exceeds risk budget ("),
    ("). Stop trop large pour la taille de compte.", "). Stop too wide for account size."),
    ("Aucun contrat autorisé après application du plafond (", "No contracts allowed after applying cap ("),
    # Violations & Tilt Alerts (journal/engine.py)
    (" inconnue dans la config (fenêtres valides : ", " unknown in config (valid windows: "),
    ("Aucune fenêtre de trading renseignée — trade hors kill zone.", "No trading window specified — trade outside kill zone."),
    (" de la séance dépasse la limite de ", " of the session exceeds the limit of "),
    (" trades/jour.", " trades/day."),
    ("Trade2 pris alors que le Trade1 (", "Trade2 taken while Trade1 ("),
    (") était en perte. Règle cancel_trade2_if_trade1_loss activée.", ") was a loss. Rule cancel_trade2_if_trade1_loss active."),
    ("Rentrée ", "Re-entry "),
    (" min après le dernier SL (cooldown requis : ", " min after last SL (required cooldown: "),
    ("Stop Loss déplacé après l'entrée (sl_moved=True).", "Stop Loss moved after entry (sl_moved=True)."),
    ("Sortie avant TP/SL planifié (early_exit=True).", "Exited before planned TP/SL (early_exit=True)."),
    ("Risque utilisé ", "Risk used "),
    (" > limite ", " > limit "),
    (" du compte.", " of account."),
    ("2 pertes consécutives détectées sur la séance.", "2 consecutive losses detected in the session."),
    ("Sur-trading : ", "Overtrading: "),
    (" trades enregistrés sur la séance (seuil configuré : ", " trades recorded in the session (configured threshold: "),
    (" trades/jour max).", " max trades/day)."),
    ("Vengeance trading : nouveau trade pris ", "Revenge trading: new trade taken "),
    (" min après une perte (seuil configuré : < ", " min after a loss (configured threshold: < "),
    ("Taille de position anormale : ", "Abnormal position size: "),
    (" contrat(s) exécuté(s) (moyenne observée : ", " contract(s) executed (observed mean: "),
    (" contrat(s), seuil configuré : >= ", " contract(s), configured threshold: >= "),
    ("Accélération de fréquence : ", "Frequency acceleration: "),
    (" trades exécutés en ", " trades executed in "),
    (" min (seuil configuré : > ", " min (configured threshold: > "),
    (" trades en ", " trades in "),
    ("pertes_consécutives", "consecutive_losses"),
    ("surtrading", "overtrading"),
    ("vengeance_trading", "revenge_trading"),
    ("taille_anormale", "abnormal_size"),
    ("accélération_fréquence", "frequency_acceleration"),
    # Coaching report strings (journal/engine.py)
    ("Échantillon insuffisant : ", "Insufficient sample: "),
    (" — pas de conclusion possible sur les fuites.", " — no conclusion possible on leaks."),
    ("Trades non conformes (SL déplacé / sortie anticipée) : ", "Non-compliant trades (SL moved / early exit): "),
    (", espérance=", ", expectancy="),
    (" vs conformes ", " vs compliant "),
    ("(écart ", "(gap "),
    (" par trade)", " per trade)"),
    ("Rentrées rapides après SL (<", "Quick re-entries after SL (<"),
    ("Trades hors fenêtre : ", "Out-of-window trades: "),
    ("Réduire les violations «", "Reduce '"),
    ("» (détectées ", "' violations (detected "),
    (" fois sur la période).", " times over the period)."),
    ("Taux de conformité élevé : ", "High compliance rate: "),
    (" — maintenir cette discipline d'exécution.", " — maintain this execution discipline."),
    ("Série de pertes consécutives maîtrisée (max ", "Controlled consecutive loss streak (max "),
    (") — bonne gestion de la perte.", ") — solid loss management."),
    ("Porter le taux de conformité de ", "Increase compliance rate from "),
]

_HEADLINE_EN_TO_FR: list[tuple[str, str]] = [
    ("Federal Reserve Board releases results of the ", "Le Conseil de la Fed publie les résultats de l'enquête "),
    ("Survey of Consumer Finances, which provides the public and policymakers with detailed insights into the economic condition of American families", "Survey of Consumer Finances sur la situation économique des ménages américains"),
    ("Survey of Consumer Finances", "Survey of Consumer Finances (situation financière des ménages)"),
    ("Minutes of the Federal Open Market Committee, ", "Compte-rendu (Minutes) du Comité FOMC de la Fed, "),
    ("Federal Reserve Board finalizes changes to enhance the transparency and public accountability of its stress test and reduce volatility in its stress test-related capital requirements", "La Fed finalise la réforme de transparence de ses stress tests bancaires et des exigences de fonds propres"),
    ("Agencies publish resolution plan feedback letters for ", "Les régulateurs publient leurs retours sur les plans de résolution de "),
    (" banking organizations", " établissements bancaires"),
    ("Federal Reserve issues FOMC statement", "La Réserve Fédérale publie le communiqué officiel du FOMC"),
    ("Federal Reserve announces ", "La Réserve Fédérale annonce "),
    ("Federal Reserve Board ", "Le Conseil de la Réserve Fédérale "),
    ("Nasdaq falls ahead of earnings, economic data while oil rallies", "Le Nasdaq recule avant les résultats et données macro tandis que le pétrole rebondit"),
    ("CPI Forecasts Show Moderated Inflation in September, Keeping the Fed on Hold", "Les prévisions CPI indiquent une inflation modérée en septembre, maintenant la Fed en pause"),
    ("Inflation likely peaked for 2026 but will remain sticky, according to prediction markets", "L'inflation a probablement atteint son pic pour 2026 mais restera persistante selon les marchés"),
    ("Squeezed by inflation, more Americans are falling behind on debt payments", "Sous pression de l'inflation, les retards de paiement sur la dette américaine augmentent"),
    ("electric vehicle boom becomes unexpected tool to combat inflation", "l'essor des véhicules électriques devient un levier inattendu contre l'inflation"),
]


def tr_text(text: str | None) -> str:
    """Traduit une chaîne dynamique issue du backend vers la langue active ('FR' ou 'EN').

    - En mode 'EN', traduit toutes les chaînes françaises vers l'anglais.
    - En mode 'FR', conserve toutes les chaînes françaises intactes et traduit
      les dépêches anglophones externes (Fed / RSS) en français.
    """
    if text is None:
        return ""
    if get_lang() != "EN":
        out_fr = text
        for en_sub, fr_sub in _HEADLINE_EN_TO_FR:
            if en_sub in out_fr:
                out_fr = out_fr.replace(en_sub, fr_sub)
        return out_fr

    stripped = text.strip()
    if stripped in _EXACT_MAP_FR_TO_EN:
        return _EXACT_MAP_FR_TO_EN[stripped]

    out = text
    for fr_sub, en_sub in _SUBSTRING_REPLACEMENTS_FR_TO_EN:
        if fr_sub in out:
            out = out.replace(fr_sub, en_sub)

    # Remplacements par expressions régulières pour les motifs paramétrés
    out = re.sub(
        r"Porter le taux de conformité de (\d+%) à (\d+%)\.",
        r"Increase compliance rate from \1 to \2.",
        out,
    )
    out = re.sub(
        r"Increase compliance rate from (\d+%) à (\d+%)\.",
        r"Increase compliance rate from \1 to \2.",
        out,
    )
    out = re.sub(r"(\d+)j (\d+)h", r"\1d \2h", out)
    out = re.sub(r"(\d+)j\b", r"\1d", out)
    out = re.sub(r"\(Alger\)", "(Algiers)", out)
    out = re.sub(r"\bAlger\b", "Algiers", out)
    return out

