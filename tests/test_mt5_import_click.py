"""Tests du chemin de clic « Import from MT5 » (feedback utilisateur).

Trois issues de la correction :
- succès : nombre de trades importés + doublons ignorés ;
- aucun trade trouvé : message info avec le nombre de deals bruts ;
- erreur : texte d'erreur exact, jamais de silence.

Le client MT5 est mocké et la base SQLite est en mémoire : aucune écriture
dans le vrai journal de l'utilisateur.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

import nqcockpit.ui.journal_page as jp
from nqcockpit.broker.mt5_client import MT5ImportSummary, MT5Status
from nqcockpit.journal.store import init_journal_db


class _FakeClient:
    def __init__(self, result: MT5ImportSummary | Exception) -> None:
        self._result = result

    def get_status(self) -> MT5Status:
        return MT5Status(status="OK", reason="ok", connected=True, server="Test-Server")

    def get_account_info(self):
        return None

    def get_open_positions(self):
        return []

    def import_trades_to_journal(
        self, conn=None, date_from=None, symbol=None, config=None
    ) -> MT5ImportSummary:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _render_import_page(monkeypatch, result: MT5ImportSummary | Exception) -> AppTest:
    """Rend la page Journal sur l'onglet Import, avec MT5 mocké."""
    monkeypatch.setattr(jp, "MT5Client", lambda: _FakeClient(result))
    monkeypatch.setattr(jp, "get_ui_db", lambda *a, **k: init_journal_db(":memory:"))

    def script() -> None:
        from nqcockpit.ui.journal_page import render_journal_page

        render_journal_page()

    app = AppTest.from_function(script, default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    # Bascule sur l'onglet « MT5 & CSV Import » (index 1).
    app.radio[0].set_value(1)
    app.run()
    assert not app.exception, app.exception
    return app


def _click_import(app: AppTest) -> AppTest:
    btn = next(b for b in app.button if b.label == "Import from MT5")
    btn.click()
    app.run()
    assert not app.exception, app.exception
    return app


def _messages(app: AppTest, kind: str) -> list[str]:
    elements = getattr(app, kind)
    return [element.value for element in elements]


def test_import_click_success(monkeypatch) -> None:
    summary = MT5ImportSummary(
        total_deals=10, total_positions=3, imported=2, duplicates=1
    )
    app = _click_import(_render_import_page(monkeypatch, summary))

    successes = _messages(app, "success")
    assert successes, f"expected a success message, got {successes}"
    assert any("2" in m and "imported" in m and "1" in m for m in successes), successes


def test_import_click_none_found(monkeypatch) -> None:
    summary = MT5ImportSummary(total_deals=0, total_positions=0)
    app = _click_import(_render_import_page(monkeypatch, summary))

    infos = _messages(app, "info")
    assert infos, f"expected an info message, got {infos}"
    assert any("0 raw deal" in m for m in infos), infos


def test_import_click_error(monkeypatch) -> None:
    app = _click_import(_render_import_page(monkeypatch, RuntimeError("boom failure")))

    errors = _messages(app, "error")
    assert errors, f"expected an error message, got {errors}"
    assert any("boom failure" in m for m in errors), errors
