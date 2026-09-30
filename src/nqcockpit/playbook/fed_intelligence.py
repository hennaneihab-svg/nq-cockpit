"""Intelligence Fed : diff de communiqués FOMC, lecture de ton (gabarit sans LLM).

Sources primaires : federalreserve.gov (gratuit, accessible depuis l'Algérie).
Garde-fous :
- Le gabarit ne calcule aucun chiffre : il reçoit du JSON et ne restitue que ce qui s'y trouve.
- validate_llm_output() rejette tout nombre absent du JSON source.
- Étiquetage obligatoire : 'aide de lecture, pas un signal'.

Note : google.genai non disponible — lecture de ton par gabarit structurel uniquement.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from nqcockpit.playbook.models import FomcDiff, FomcMinutesWatch

log = logging.getLogger(__name__)
UTC = timezone.utc

# URL des communiqués FOMC (federalreserve.gov — gratuit, pas de clé)
_STATEMENT_BASE = "https://www.federalreserve.gov"
_STATEMENT_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"

# Expressions régulières pour extraire les nombres d'un texte
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

# Mots-clés hawkish / dovish pour le gabarit sans LLM
_HAWKISH_KEYWORDS = [
    "inflation remains elevated",
    "inflation is elevated",
    "tighter",
    "restrictive",
    "further increases",
    "additional firming",
    "upside risks",
    "labor market remains tight",
    "above target",
]
_DOVISH_KEYWORDS = [
    "inflation has eased",
    "labor market has cooled",
    "slowing",
    "moderated",
    "downside risks",
    "below target",
    "pause",
    "patient",
    "gradual",
]


def _fetch_text(url: str, timeout: int = 15) -> tuple[str, str]:
    """Télécharge un document texte depuis federalreserve.gov.

    Returns:
        (text, status) où status = 'OK' | 'DÉGRADÉ: <raison>'
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        # Décoder en UTF-8 avec repli latin-1
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        return text, "OK"
    except urllib.error.HTTPError as exc:
        msg = f"DÉGRADÉ: HTTP {exc.code} lors du fetch de {url}"
        log.warning(msg)
        return "", msg
    except (urllib.error.URLError, OSError) as exc:
        msg = f"DÉGRADÉ: réseau inaccessible pour {url} — {exc}"
        log.warning(msg)
        return "", msg


def _strip_html(text: str) -> str:
    """Retire les balises HTML et normalise les espaces."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    """Découpe un texte en phrases (délimiteurs : '. ', '.\n', '! ', '? ')."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def _word_diff(prev_sentences: list[str], curr_sentences: list[str]) -> tuple[list[str], list[str]]:
    """Diff ligne à ligne (phrase à phrase) entre deux listes de phrases.

    Returns:
        (added, removed) — listes de phrases ajoutées / retirées.
    """
    prev_set = set(prev_sentences)
    curr_set = set(curr_sentences)
    added = [s for s in curr_sentences if s not in prev_set]
    removed = [s for s in prev_sentences if s not in curr_set]
    return added, removed


def _analyze_tone_template(
    added: list[str],
    removed: list[str],
    source_json: dict,
) -> tuple[str | None, list[str]]:
    """Lecture de ton par gabarit sans LLM (google.genai non disponible).

    Le gabarit ne produit aucun chiffre absent du source_json.
    Étiquetage : 'aide de lecture, pas un signal'.

    Returns:
        (tone_label, extracts)
    """
    hawkish_score = 0
    dovish_score = 0
    extracts: list[str] = []

    all_new_text = " ".join(added).lower()
    all_removed_text = " ".join(removed).lower()

    for kw in _HAWKISH_KEYWORDS:
        if kw in all_new_text:
            hawkish_score += 2
            # Trouver la phrase source
            for s in added:
                if kw in s.lower() and s not in extracts:
                    extracts.append(f"[+] {s[:200]}")
                    break
        if kw in all_removed_text:
            dovish_score += 1  # Retrait d'un mot hawkish = signal dovish

    for kw in _DOVISH_KEYWORDS:
        if kw in all_new_text:
            dovish_score += 2
            for s in added:
                if kw in s.lower() and s not in extracts:
                    extracts.append(f"[+] {s[:200]}")
                    break
        if kw in all_removed_text:
            hawkish_score += 1  # Retrait d'un mot dovish = signal hawkish

    if hawkish_score > dovish_score + 1:
        tone_label: str | None = "hawkish"
    elif dovish_score > hawkish_score + 1:
        tone_label = "dovish"
    elif hawkish_score == 0 and dovish_score == 0:
        tone_label = None  # Pas assez de signal
    else:
        tone_label = "neutre"

    return tone_label, extracts[:5]  # Max 5 extraits


def validate_llm_output(text: str, source_json: dict) -> bool:
    """Garde-fou : vérifie que tous les nombres du texte existent dans le JSON source.

    Args:
        text: Texte généré (par LLM ou gabarit).
        source_json: Données sources (dict).

    Returns:
        True si tous les nombres du texte se trouvent dans le JSON source.
        False si un nombre est absent (hallucination potentielle).
    """
    # Extraire tous les nombres du texte généré
    text_numbers = set(_NUMBER_RE.findall(text))

    # Extraire tous les nombres du JSON source (y compris dans les valeurs)
    json_str = str(source_json)
    source_numbers = set(_NUMBER_RE.findall(json_str))

    # Vérifier que chaque nombre du texte existe dans la source
    hallucinated = text_numbers - source_numbers
    if hallucinated:
        log.warning(
            "GARDE-FOU LLM — nombres absents du JSON source: %s",
            sorted(hallucinated),
        )
        return False
    return True


def fetch_fomc_statement(url: str, timeout: int = 15) -> tuple[str, str]:
    """Télécharge et nettoie un communiqué FOMC.

    Args:
        url: URL du communiqué (federalreserve.gov).
        timeout: Délai en secondes.

    Returns:
        (text_cleaned, status) — status = 'OK' | 'DÉGRADÉ: ...'
    """
    raw, status = _fetch_text(url, timeout=timeout)
    if not raw:
        return "", status
    cleaned = _strip_html(raw)
    return cleaned, status


def diff_statements(
    prev_url: str,
    curr_url: str,
    timeout: int = 15,
) -> FomcDiff:
    """Télécharge et compare deux communiqués FOMC (diff mot à mot).

    Args:
        prev_url: URL du communiqué précédent.
        curr_url: URL du communiqué courant.
        timeout: Délai réseau.

    Returns:
        FomcDiff avec statut DÉGRADÉ si une source est inaccessible.
    """
    fetched_at = datetime.now(UTC)

    prev_text, prev_status = fetch_fomc_statement(prev_url, timeout=timeout)
    curr_text, curr_status = fetch_fomc_statement(curr_url, timeout=timeout)

    degraded = []
    if prev_status != "OK":
        degraded.append(f"Communiqué précédent: {prev_status}")
    if curr_status != "OK":
        degraded.append(f"Communiqué courant: {curr_status}")

    overall_status = "DÉGRADÉ: " + "; ".join(degraded) if degraded else "OK"

    if not prev_text or not curr_text:
        return FomcDiff(
            prev_statement_url=prev_url,
            curr_statement_url=curr_url,
            added_sentences=[],
            removed_sentences=[],
            tone_label=None,
            tone_extracts=[],
            fetched_at_utc=fetched_at,
            status=overall_status,
            status_detail=overall_status,
        )

    prev_sentences = _split_sentences(prev_text)
    curr_sentences = _split_sentences(curr_text)
    added, removed = _word_diff(prev_sentences, curr_sentences)

    # Construire le JSON source pour le garde-fou
    source_json: dict = {
        "prev_url": prev_url,
        "curr_url": curr_url,
        "added_count": len(added),
        "removed_count": len(removed),
    }

    tone_label, extracts = _analyze_tone_template(added, removed, source_json)

    # Validation du garde-fou sur les extraits
    extracts_text = " ".join(extracts)
    if extracts_text and not validate_llm_output(extracts_text, source_json):
        log.warning(
            "GARDE-FOU: extraits contiennent des nombres absents du JSON source — nettoyage"
        )
        # Retirer les extraits problématiques
        extracts = [e for e in extracts if validate_llm_output(e, source_json)]

    return FomcDiff(
        prev_statement_url=prev_url,
        curr_statement_url=curr_url,
        added_sentences=added[:20],  # Max 20 phrases ajoutées
        removed_sentences=removed[:20],
        tone_label=tone_label,
        tone_extracts=extracts,
        tone_note="aide de lecture, pas un signal",
        fetched_at_utc=fetched_at,
        status=overall_status,
        status_detail=overall_status if overall_status != "OK" else "",
    )


def _fetch_dgs2_fred(timeout: int = 10) -> tuple[float | None, str | None, str]:
    """Récupère le taux DGS2 (rendement 2 ans US) depuis FRED.

    Source : api.stlouisfed.org (gratuit, sans clé pour les séries publiques).
    Plan B : FRED observations JSON endpoint public.

    Returns:
        (rate_pct, obs_date, status)
    """
    # FRED public endpoint (sans clé API — données publiques)
    url = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2&vintage_date="
        + datetime.now(UTC).strftime("%Y-%m-%d")
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            lines = resp.read().decode("utf-8").strip().splitlines()
        # Format CSV: DATE,DGS2 (avec header)
        data_lines = [ln for ln in lines if ln and not ln.startswith("DATE")]
        if not data_lines:
            return None, None, "DÉGRADÉ: données DGS2 vides"
        # Dernière observation non-nulle
        for line in reversed(data_lines):
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip() not in (".", ""):
                try:
                    rate = float(parts[1].strip())
                    obs_date = parts[0].strip()
                    return rate, obs_date, "OK"
                except ValueError:
                    continue
        return None, None, "DÉGRADÉ: aucune observation valide DGS2"
    except (urllib.error.URLError, OSError) as exc:
        return None, None, f"DÉGRADÉ: {exc}"


def generate_minutes_watch(
    fomc_minutes_event: object,
    prev_statement_url: str = "",
    timeout: int = 15,
) -> FomcMinutesWatch:
    """Génère une fiche 'à surveiller' avant la publication des minutes FOMC.

    Args:
        fomc_minutes_event: CalendarEvent de type 'FOMC Minutes'.
        prev_statement_url: URL du dernier communiqué FOMC (pour les thèmes).
        timeout: Délai réseau.

    Returns:
        FomcMinutesWatch avec thèmes, DGS2, statut.
    """
    scheduled_utc = getattr(fomc_minutes_event, "scheduled_utc", None)
    if scheduled_utc is None:
        return FomcMinutesWatch(
            scheduled_utc=datetime.now(UTC),
            status="DÉGRADÉ",
            status_detail="scheduled_utc manquant dans CalendarEvent",
        )

    # DGS2
    dgs2_rate, dgs2_date, dgs2_status = _fetch_dgs2_fred(timeout=timeout)

    # Thèmes du dernier communiqué (si URL disponible)
    themes: list[str] = []
    if prev_statement_url:
        stmt_text, stmt_status = fetch_fomc_statement(prev_statement_url, timeout=timeout)
        if stmt_text:
            # Extraire les phrases-clés (hawkish/dovish) comme thèmes
            sentences = _split_sentences(stmt_text)
            for s in sentences:
                s_lower = s.lower()
                for kw in _HAWKISH_KEYWORDS + _DOVISH_KEYWORDS:
                    if kw in s_lower:
                        themes.append(s[:200])
                        break
            themes = themes[:6]  # Max 6 thèmes

    # Statuts
    issues = []
    if dgs2_status != "OK":
        issues.append(dgs2_status)

    overall_status = "DÉGRADÉ: " + "; ".join(issues) if issues else "OK"

    return FomcMinutesWatch(
        scheduled_utc=scheduled_utc,
        themes=themes,
        speeches_since=[],  # Alimenté depuis le RSS Fed dans un enrichissement ultérieur
        dgs2_rate=dgs2_rate,
        dgs2_date=dgs2_date,
        dgs2_status=dgs2_status,
        status=overall_status,
        status_detail=overall_status if overall_status != "OK" else "",
    )
