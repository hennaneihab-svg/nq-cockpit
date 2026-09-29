"""Vérification de l'environnement d'exécution."""

import sys


def test_environment_python_version() -> None:
    assert sys.version_info >= (3, 11)
