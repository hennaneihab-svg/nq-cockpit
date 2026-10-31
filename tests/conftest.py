"""Isolation de l'environnement de test.

- Aucun test n'écrit dans la base de production ``data/nqcockpit.db`` :
  ``NQ_DATA_DB_PATH`` pointe vers un fichier temporaire propre à chaque test.
- Aucun test ne lit le vrai ``.env`` ni n'envoie de vrai message Telegram :
  les secrets connus sont retirés de ``os.environ``, le chargement du vrai
  ``.env`` est bloqué, et tout appel HTTP sortant vers ``api.telegram.org``
  est interdit.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_db(tmp_path, monkeypatch):
    """Redirige la base de données et les exports de niveaux vers le tmp_path du test."""
    monkeypatch.setenv("NQ_DATA_DB_PATH", str(tmp_path / "nqcockpit_test.db"))
    monkeypatch.setenv("NQ_LEVELS_OUTPUT_DIR", str(tmp_path / "levels"))


# Clés secrètes connues (miroir de nqcockpit.env.KNOWN_SECRET_KEYS).
_KNOWN_SECRET_KEYS = (
    "FRED_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "MT5_LOGIN",
    "MT5_PASSWORD",
    "MT5_SERVER",
    "MT5_PATH",
)


@pytest.fixture(autouse=True)
def _isolate_secrets_and_network(tmp_path, monkeypatch):
    """Empêche les tests de lire le vrai .env ou de joindre Telegram.

    1. Retire toutes les clés secrètes connues de ``os.environ``.
    2. Neutralise ``load_environment()`` : seuls les ``.env`` situés sous le
       ``tmp_path`` du test (fixtures) restent chargeables.
    3. Bloque tout appel HTTP sortant vers ``api.telegram.org``.
    """
    # 1. Secrets hors de l'environnement du processus.
    for key in _KNOWN_SECRET_KEYS:
        monkeypatch.delenv(key, raising=False)

    # 2. Neutralise load_dotenv pour le vrai .env (et ses parents).
    import nqcockpit.env as env_mod

    real_load_dotenv = env_mod.load_dotenv
    tmp_root = tmp_path.resolve()

    def _guarded_load_dotenv(dotenv_path=None, **kwargs):
        if dotenv_path is None:
            return False
        resolved = Path(dotenv_path).resolve()
        if not str(resolved).startswith(str(tmp_root)):
            return False  # .env réel ou parent -> bloqué
        return real_load_dotenv(dotenv_path=dotenv_path, **kwargs)

    monkeypatch.setattr(env_mod, "load_dotenv", _guarded_load_dotenv)

    # 3. Bloque le réseau sortant vers Telegram.
    import urllib.request

    real_urlopen = urllib.request.urlopen

    def _guarded_urlopen(url, *args, **kwargs):
        if "api.telegram.org" in str(url):
            raise RuntimeError("Blocked outbound HTTP to api.telegram.org in tests")
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", _guarded_urlopen)
