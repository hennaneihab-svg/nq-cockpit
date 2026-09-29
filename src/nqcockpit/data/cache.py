"""Gestionnaire de cache disque pour NQ Cockpit."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/cache")


class DiskCache:
    """Cache fichier JSON avec durée de validité (TTL) en secondes."""

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in key)
        return self.cache_dir / f"{safe_key}.json"

    def get(self, key: str, max_age_seconds: float | None = None) -> Any | None:
        """Récupère la valeur en cache si elle existe et n'est pas expirée."""
        path = self._file_path(key)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            saved_at = datetime.fromisoformat(payload["saved_at_utc"])
            now = datetime.now(timezone.utc)
            age = (now - saved_at).total_seconds()

            if max_age_seconds is not None and age > max_age_seconds:
                return None

            return payload["data"]
        except Exception as e:
            log.warning("Erreur lors de la lecture du cache %s: %s", key, e)
            return None

    def set(self, key: str, data: Any) -> None:
        """Enregistre une donnée en cache avec son horodatage UTC."""
        path = self._file_path(key)
        try:
            payload = {
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                "data": data,
            }
            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, default=str)
            tmp_path.replace(path)
        except Exception as e:
            log.warning("Erreur lors de l'écriture du cache %s: %s", key, e)

    def clear(self, key: str | None = None) -> None:
        """Supprime une entrée du cache ou tout le cache."""
        if key is not None:
            p = self._file_path(key)
            if p.exists():
                p.unlink(missing_ok=True)
        else:
            for p in self.cache_dir.glob("*.json"):
                p.unlink(missing_ok=True)
