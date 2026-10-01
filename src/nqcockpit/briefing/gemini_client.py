"""Client Gemini optionnel avec garde-fou anti-hallucination (P12).

Le rôle du LLM est strictement rédactionnel : reformuler/résumer en langage
naturel les données déjà calculées et fournies en entrée.
AUCUNE donnée manquante ne doit être devinée ou complétée.
 Validation obligatoire post-génération : si le texte généré contient
un nombre non présent dans les données sources, le résultat Gemini est
rejeté et le système bascule sur le fallback texte brut (Markdown déterministe).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from nqcockpit.config import AppConfig, load_config
from nqcockpit.briefing.models import GeminiResult

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> Any:
    """Sérialiseur par défaut pour dataclasses, objets et datetime en JSON."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    if hasattr(obj, "value"):
        return obj.value
    return str(obj)


def generate_gemini_summary(
    structured_data: dict[str, Any],
    source_numbers: set[float | int | str],
    validator_func: Callable[[str, set[float | int | str]], tuple[bool, str | None]],
    config: AppConfig | None = None,
    api_key_override: str | None = None,
) -> GeminiResult:
    """Appelle l'API Gemini de manière sécurisée et valide l'absence d'hallucinations.

    Args:
        structured_data: Dictionnaire contenant l'ensemble des données sources validées.
        source_numbers: Ensemble des nombres valides présents dans les données sources.
        validator_func: Fonction de validation anti-hallucination.
        config: Configuration globale (défaut: load_config()).
        api_key_override: Clé d'API explicite (optionnelle, pour les tests).

    Returns:
        GeminiResult avec statut OK, DISABLED, REJECTED_HALLUCINATION ou FAILED.
    """
    if config is None:
        config = load_config()

    api_key = api_key_override or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.info("Clé GEMINI_API_KEY non configurée — bascule sur fallback texte brut.")
        return GeminiResult(
            status="DISABLED",
            content=None,
            warning="Gemini non configuré (clé GEMINI_API_KEY absente dans .env) — fallback texte brut",
        )

    model_name = getattr(config, "briefing_gemini_model", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    json_str = json.dumps(structured_data, default=_json_default, ensure_ascii=False, indent=2)
    prompt = (
        "Tu es un assistant de trading discipliné et neutre. "
        "Voici les données d'analyse pré-séance pour l'indice NQ (Nasdaq-100 Futures) au format JSON.\n"
        "INSTRUCTIONS STRICTES :\n"
        "1. Rédige un briefing synthétique en Markdown structuré en français.\n"
        "2. N'invente AUCUN chiffre, prix, niveau, pourcentage ou statistique. "
        "Utilise UNIQUEMENT les nombres présents dans le JSON ci-dessous.\n"
        "3. Ne donne aucun conseil directionnel haussier ou baissier. N'utilise jamais les termes "
        "'viser' ou 'cibler'. Décris les scénarios de manière conditionnelle (si... alors...).\n"
        "4. Si une section indique un statut DÉGRADÉ, mentionne-le clairement sans le masquer.\n\n"
        f"DONNÉES SOURCES JSON :\n```json\n{json_str}\n```"
    )

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.95,
        },
    }

    try:
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15.0) as response:
            resp_body = response.read().decode("utf-8")
            resp_json = json.loads(resp_body)

        candidates = resp_json.get("candidates", [])
        if not candidates:
            return GeminiResult(
                status="FAILED",
                content=None,
                warning="Réponse API Gemini vide (aucun candidat généré) — fallback texte brut",
            )

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts or "text" not in parts[0]:
            return GeminiResult(
                status="FAILED",
                content=None,
                warning="Format de réponse Gemini inattendu — fallback texte brut",
            )

        generated_text = parts[0]["text"].strip()

        # Garde-fou anti-hallucination obligatoire
        is_valid, validation_warn = validator_func(generated_text, source_numbers)
        if not is_valid:
            logger.warning("Hallucination Gemini détectée : %s", validation_warn)
            return GeminiResult(
                status="REJECTED_HALLUCINATION",
                content=None,
                warning=f"Hallucination Gemini détectée et rejetée ({validation_warn}) — fallback texte brut",
            )

        return GeminiResult(status="OK", content=generated_text, warning=None)

    except urllib.error.URLError as e:
        logger.warning("Erreur de connexion à l'API Gemini : %s", e)
        return GeminiResult(
            status="FAILED",
            content=None,
            warning=f"Erreur réseau API Gemini ({e}) — fallback texte brut",
        )
    except Exception as e:
        logger.warning("Exception inattendue lors de l'appel Gemini : %s", e)
        return GeminiResult(
            status="FAILED",
            content=None,
            warning=f"Échec appel Gemini ({e}) — fallback texte brut",
        )
