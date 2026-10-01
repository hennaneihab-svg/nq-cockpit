"""Wrapper d'envoi Telegram optionnel (P12).

Si les identifiants Telegram (TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID) ne sont
pas configurés dans l'environnement, l'envoi est désactivé proprement avec un
statut DÉGRADÉ dans les logs sans aucun crash.

Transmet uniquement le texte déjà généré et validé (Gemini ou fallback brut).
Prend en charge le mode --dry-run pour simuler l'envoi sans appel réseau.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from nqcockpit.briefing.models import TelegramResult

logger = logging.getLogger(__name__)


def send_telegram_message(
    message_text: str,
    dry_run: bool = False,
    bot_token_override: str | None = None,
    chat_id_override: str | None = None,
) -> TelegramResult:
    """Envoie un message via le bot Telegram.

    Args:
        message_text: Texte du briefing à transmettre.
        dry_run: Si True, simule l'envoi sans effectuer d'appel réseau.
        bot_token_override: Token de bot explicite (optionnel, pour tests).
        chat_id_override: ID de chat explicite (optionnel, pour tests).

    Returns:
        TelegramResult indiquant le statut et le résultat d'envoi.
    """
    token = bot_token_override or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id_override or os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.info("Telegram non configuré (token/chat_id absent) — envoi désactivé.")
        return TelegramResult(
            status="DISABLED",
            sent=False,
            message="Telegram non configuré (TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID absent)",
        )

    if dry_run:
        logger.info("[DRY-RUN] Envoi Telegram prévisualisé sans transmission réseau.")
        return TelegramResult(
            status="DRY_RUN",
            sent=False,
            message="[DRY-RUN] Envoi Telegram prévisualisé avec succès",
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Tentative 1 : avec parse_mode Markdown
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            resp_body = resp.read().decode("utf-8")
            resp_json = json.loads(resp_body)

        if resp_json.get("ok"):
            return TelegramResult(
                status="OK",
                sent=True,
                message="Message Telegram transmis avec succès",
            )
    except urllib.error.HTTPError as http_err:
        # Si erreur 400 (échec de parsing Markdown), réessaye sans parse_mode
        if http_err.code == 400:
            logger.warning("Échec parse_mode Markdown Telegram. Réessai en texte brut...")
            payload.pop("parse_mode", None)
            try:
                req_data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp2:
                    resp_body2 = resp2.read().decode("utf-8")
                    resp_json2 = json.loads(resp_body2)

                if resp_json2.get("ok"):
                    return TelegramResult(
                        status="OK",
                        sent=True,
                        message="Message Telegram transmis (texte brut sans Markdown)",
                    )
            except Exception as retry_err:
                logger.error("Échec du réessai Telegram : %s", retry_err)
                return TelegramResult(
                    status="FAILED",
                    sent=False,
                    error=f"Erreur API Telegram ({retry_err})",
                )

        return TelegramResult(
            status="FAILED",
            sent=False,
            error=f"Erreur HTTP Telegram {http_err.code} : {http_err.reason}",
        )
    except Exception as e:
        logger.error("Exception lors de l'envoi Telegram : %s", e)
        return TelegramResult(
            status="FAILED",
            sent=False,
            error=f"Exception Telegram ({e})",
        )

    return TelegramResult(
        status="FAILED",
        sent=False,
        error="Réponse API Telegram inattendue",
    )
