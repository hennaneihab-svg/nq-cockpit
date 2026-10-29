"""Tests Étape 5 — i18n par codes, badges, layout radar et graphique NQ.

Couvre :
- Un dictionnaire en/fr unique couvre tous les codes de statut et toutes les
  clés de composant/motif réellement renvoyées par le moteur de profil.
- Le moteur ne renvoie que des codes ASCII (aucune phrase française).
- Langue par défaut = Anglais, pilotée par `config.yaml` (`ui.language`).
- Badges : vert OK, ambre périmé/dégradé, rouge uniquement sans donnée.
- Constructeur de graphique : bougies + lignes gamma, sinon message d'état vide.
- Layout : aucune colonne Streamlit imbriquée > 2 niveaux, radar en grille fluide.
- COT : catégorie « Leveraged Funds » et colonnes 7/8 du rapport CFTC.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import nqcockpit.ui.i18n as i18n
from nqcockpit.config import load_config
from nqcockpit.data.db import apply_migrations, insert_bars
from nqcockpit.data.models import Bar
from nqcockpit.macro.fetcher import parse_cftc_report
from nqcockpit.macro.models import CotPositioning
from nqcockpit.profile.models import ComponentHealth
from nqcockpit.ui.chart import (
    TZ_ET,
    build_session_chart,
    format_bar_timestamp,
    load_latest_session_bars,
)
from nqcockpit.ui.components import health_badge_html
from nqcockpit.ui.i18n import (
    LABELS,
    STATUS_CODES,
    configured_default_lang,
    get_lang,
    label,
    status_kind,
    status_label,
)

UTC_TZ = UTC
NOW_UTC = datetime(2026, 10, 20, 14, 0, tzinfo=UTC_TZ)


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch):
    """Libellés EN déterministes, indépendamment de la session Streamlit."""
    monkeypatch.setattr(i18n, "get_lang", lambda: "EN")


# ---------------------------------------------------------------------------
# 1. Dictionnaire i18n : couverture en + fr
# ---------------------------------------------------------------------------


def test_every_label_has_english_and_french() -> None:
    """Chaque entrée du dictionnaire possède bien une version EN et FR."""
    assert LABELS
    for key, translations in LABELS.items():
        assert translations.get("en", "").strip(), f"EN manquant pour {key}"
        assert translations.get("fr", "").strip(), f"FR manquant pour {key}"


def test_every_status_code_has_both_languages() -> None:
    """Chaque code renvoyé par les moteurs a un libellé court en EN et FR."""
    for code in STATUS_CODES:
        entry = LABELS[f"status.{code}"]
        assert entry["en"].strip()
        assert entry["fr"].strip()


def test_engine_component_and_reason_keys_exist_in_i18n() -> None:
    """Toute clé `component.*` / `reason.*` utilisée par le moteur est traduite."""
    from nqcockpit.profile import engine as profile_engine

    source = Path(profile_engine.__file__).read_text(encoding="utf-8")
    keys = set(re.findall(r'"(component\.[a-z0-9_]+|reason\.[a-z0-9_]+)"', source))
    assert keys, "aucune clé i18n trouvée dans profile/engine.py"
    missing = sorted(key for key in keys if key not in LABELS)
    assert not missing, f"clés non traduites : {missing}"


def test_status_helpers_normalize_legacy_and_codes() -> None:
    """Les anciens statuts texte sont normalisés, les codes restent stables."""
    assert status_label("OK") == "OK"
    assert status_label("NO_DATA") == "No data"
    assert status_label("DÉGRADÉ") == "Degraded"
    assert status_kind("OK") == "ok"
    assert status_kind("DEGRADED") == "warn"
    assert status_kind("STALE") == "warn"
    assert status_kind("NO_DATA") == "error"


# ---------------------------------------------------------------------------
# 2. Moteur : codes seulement, aucune phrase française
# ---------------------------------------------------------------------------


def test_engine_returns_ascii_status_codes_only(monkeypatch) -> None:
    """Un profil hors-ligne expose des codes ASCII, jamais de statut en français."""
    from nqcockpit.profile.engine import build_day_profile

    def _offline(*args, **kwargs):
        raise RuntimeError("sources hors ligne (test)")

    monkeypatch.setattr("nqcockpit.events.radar.fetch_event_radar", _offline)
    monkeypatch.setattr("nqcockpit.macro.engine.compute_macro_snapshot", _offline)

    profile = build_day_profile(conn=None, config=load_config(), now_utc=NOW_UTC)

    assert profile.component_statuses, "aucun composant suivi"
    for health in profile.component_statuses.values():
        assert health.status in STATUS_CODES, health.status
        for value in (health.name, health.status, health.detail):
            assert value.isascii(), f"valeur non neutre renvoyée : {value!r}"
        if health.reason_key:
            assert health.reason_key in LABELS
    assert profile.status in ("OK", "DEGRADED")
    assert profile.status_detail.isascii()

    for flag in profile.no_trade.all_flags:
        assert flag.status in ("ACTIVE", "INACTIVE", "DEGRADED"), flag.status


# ---------------------------------------------------------------------------
# 3. Langue par défaut par config
# ---------------------------------------------------------------------------


def test_default_language_is_english_via_config() -> None:
    """`ui.language` dans config.yaml est la bascule unique, EN par défaut."""
    config = load_config()
    assert config.ui.language == "EN"
    assert get_lang() == "EN"
    assert configured_default_lang() == "EN"
    assert label("status.NO_DATA") == "No data"


# ---------------------------------------------------------------------------
# 4. Badges simples, couleurs sémantiques
# ---------------------------------------------------------------------------


def test_health_badges_are_plain_short_with_reason() -> None:
    """Badge court + motif, sans mot brut effrayant (DEGRADED/DÉGRADÉ)."""
    degraded = ComponentHealth(
        name="component.gamma",
        status="DEGRADED",
        reason_key="reason.no_snapshot",
    )
    html = health_badge_html(degraded)
    assert "Degraded" in html
    assert "No options snapshot available" in html
    assert "DEGRADED" not in html
    assert "DÉGRADÉ" not in html
    assert "chip-degraded" in html

    ok_html = health_badge_html(
        ComponentHealth(name="component.macro", status="OK", detail="VIX=15.0")
    )
    assert "chip-ok" in ok_html

    no_data_html = health_badge_html(
        ComponentHealth(name="component.overnight", status="NO_DATA")
    )
    # Rouge uniquement quand la source n'a aucune donnée.
    assert "chip-error" in no_data_html
    assert "No data" in no_data_html


# ---------------------------------------------------------------------------
# 5. Graphique NQ : bougies, niveaux, état vide
# ---------------------------------------------------------------------------


def _bar(ts: datetime, price: float = 20000.0) -> Bar:
    return Bar(
        timestamp_utc=ts,
        open=price,
        high=price + 10,
        low=price - 10,
        close=price + 5,
        volume=100.0,
    )


def test_chart_builder_returns_empty_state_message_without_bars() -> None:
    """Sans barres : aucun cadre vide, un message d'état vide explicite."""
    result = build_session_chart([])
    assert result.figure is None
    assert result.has_data is False
    assert result.message.startswith("No chart data")
    assert "NQ=F" in result.message

    last = datetime(2026, 10, 28, 20, 0, tzinfo=UTC_TZ)
    with_last = build_session_chart([], last_bar_utc=last)
    assert with_last.figure is None
    assert "No chart data" in with_last.message
    assert format_bar_timestamp(last) in with_last.message


def test_chart_builder_draws_candles_and_gamma_lines() -> None:
    """Avec barres + niveaux : bougies et 3 lignes horizontales, pas de message."""
    bars = [
        _bar(NOW_UTC - timedelta(minutes=3), 20000.0),
        _bar(NOW_UTC - timedelta(minutes=2), 20010.0),
        _bar(NOW_UTC - timedelta(minutes=1), 20020.0),
    ]
    result = build_session_chart(
        bars,
        gamma_flip=20000.0,
        call_wall=20200.0,
        put_support=19800.0,
    )
    assert result.figure is not None
    assert result.message == ""
    assert len(result.figure.data) == 1
    assert result.figure.data[0].type == "candlestick"
    assert len(result.figure.layout.shapes) == 3
    annotations = " ".join(str(a.text) for a in result.figure.layout.annotations)
    for expected in ("Gamma flip", "Call wall", "Put support"):
        assert expected in annotations


def test_load_latest_session_bars_reads_bars_table(tmp_path: Path) -> None:
    """La séance retenue est la date ET du dernier bar stocké (table `bars`)."""
    conn = sqlite3.connect(str(tmp_path / "chart.db"))
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    # 22:00 UTC = 18:00 ET le 27/10 ; 02:00 UTC = 22:00 ET le 28/10.
    bars = [
        _bar(datetime(2026, 10, 27, 22, 0, tzinfo=UTC_TZ)),
        _bar(datetime(2026, 10, 28, 15, 0, tzinfo=UTC_TZ)),
        _bar(datetime(2026, 10, 28, 18, 0, tzinfo=UTC_TZ)),
    ]
    insert_bars(conn, bars, "NQ=F", "1m", "test", NOW_UTC)

    session_bars, last_ts = load_latest_session_bars(conn)
    conn.close()

    assert last_ts == datetime(2026, 10, 28, 18, 0, tzinfo=UTC_TZ)
    assert len(session_bars) == 2
    session_date = last_ts.astimezone(TZ_ET).date()
    assert all(
        bar.timestamp_utc.astimezone(TZ_ET).date() == session_date
        for bar in session_bars
    )


def test_empty_bars_table_yields_no_session_and_no_chart(tmp_path: Path) -> None:
    """Table `bars` vide : ([], None) puis message d'état vide (aucune invention)."""
    conn = sqlite3.connect(str(tmp_path / "empty.db"))
    apply_migrations(conn)
    session_bars, last_ts = load_latest_session_bars(conn)
    conn.close()

    assert session_bars == []
    assert last_ts is None
    assert build_session_chart(session_bars).message.startswith("No chart data")


# ---------------------------------------------------------------------------
# 6. Layout : pas de colonnes imbriquées, radar en grille fluide
# ---------------------------------------------------------------------------


def _is_st_columns(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "columns"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
    )


def _max_columns_depth(tree: ast.AST) -> int:
    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0
            self.max_depth = 0

        def visit_With(self, node: ast.With) -> None:
            opens_columns = any(_is_st_columns(item.context_expr) for item in node.items)
            if opens_columns:
                self.depth += 1
                self.max_depth = max(self.max_depth, self.depth)
            self.generic_visit(node)
            if opens_columns:
                self.depth -= 1

    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.max_depth


def test_cockpit_layout_has_no_nested_columns_beyond_two_levels() -> None:
    """Le code de layout ne dépasse jamais 2 niveaux de colonnes imbriquées."""
    from nqcockpit.ui import cockpit_page

    source = Path(cockpit_page.__file__).read_text(encoding="utf-8")
    depth = _max_columns_depth(ast.parse(source))
    assert depth <= 2, f"colonnes imbriquées sur {depth} niveaux"


def test_macro_radar_uses_fluid_grid_not_fixed_columns() -> None:
    """Le radar macro utilise une grille CSS fluide, pas des colonnes fixes."""
    from nqcockpit.ui import macro_page, sections

    source = Path(sections.__file__).read_text(encoding="utf-8")
    assert "radar-grid" in source
    assert "repeat(auto-fit, minmax(" in source
    page_source = Path(macro_page.__file__).read_text(encoding="utf-8")
    assert "st.columns(3)" not in page_source


# ---------------------------------------------------------------------------
# 7. COT : « Leveraged Funds », contrat NASDAQ-100 Consolidated
# ---------------------------------------------------------------------------

CFTC_FIXTURE = (
    "Traders in Financial Futures - Futures Only Positions as of October 20, 2026\n"
    "-----------------------------------------------------------------\n"
    "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE\n"
    "Positions\n"
    "39,302 129,243 8,154 110,983 32,216 4,977 "
    "48,053 55,741 13,764 13,173 10,623 0 47,477 31,164\n"
)


def test_cot_label_is_leveraged_funds_and_contract_matches() -> None:
    """Le rapport financial_lf.htm publie Leveraged Funds, pas « non-commercial »."""
    assert CotPositioning().category_label == "Leveraged Funds"

    config = load_config()
    contract_keyword = str(config.macro.sources["cot_contract_name"]).upper()
    assert "NASDAQ-100 CONSOLIDATED" in contract_keyword


def test_cot_parser_uses_leveraged_funds_long_short_columns() -> None:
    """Colonnes 7 et 8 (indices 6/7) = Leveraged Funds Long puis Short."""
    parsed = parse_cftc_report(CFTC_FIXTURE, "NASDAQ-100")
    assert parsed is not None
    report_date, contract, long_pos, short_pos = parsed
    assert report_date == "2026-10-20"
    assert "NASDAQ-100 Consolidated" in contract
    assert (long_pos, short_pos) == (48053, 55741)
    assert long_pos - short_pos == -7688
