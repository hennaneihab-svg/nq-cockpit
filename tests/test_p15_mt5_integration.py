"""Tests pytest unitaires et d'intégration pour la passerelle MetaTrader 5 (P15).

Couvre :
- RàƒÂ¨gle R9 : lecture seule absolue, interdiction d'envoi d'ordres
- Statut honnàƒÂªte : terminal absent/non lancé -> Dàƒâ€°GRADàƒâ€° explicite
- Authentification échouée -> Dàƒâ€°GRADàƒâ€° explicite
- Connexion réussie et récupération des infos de compte
- Récupération des positions ouvertes
- Réconciliation des deals en round-trips et détection du stop loss
- Auto-import dans SQLite avec calcul du R et déduplication stricte
- Stockage sécurisé des identifiants dans .env (sans altération du reste du fichier)
- Conversion rigoureuse des fuseaux horaires (serveur -> NY & Alger via zoneinfo)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from nqcockpit.broker.mt5_client import (
    MT5Client,
    MT5ImportSummary,
    MT5Status,
)
from nqcockpit.config import load_config
from nqcockpit.env import (
    get_mt5_credentials,
    get_mt5_raw_credentials,
    save_mt5_credentials,
)
from nqcockpit.journal.models import TradeDirection, TradeOutcome
from nqcockpit.journal.store import init_journal_db, load_trades

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_conn():
    """Base SQLite en mémoire pour isoler les tests de journal."""
    return init_journal_db(":memory:")


@pytest.fixture()
def config():
    """Configuration de test standard."""
    return load_config()


@pytest.fixture()
def mock_mt5():
    """Mock complet du module MetaTrader5."""
    with patch("nqcockpit.broker.mt5_client.mt5") as mock:
        yield mock


# ---------------------------------------------------------------------------
# 1. RàƒÂ¨gle R9 : Interdiction formelle d'envoi d'ordres
# ---------------------------------------------------------------------------


def test_r9_read_only_enforcement():
    """Vérifie que le client est strictement en lecture seule selon R9."""
    client = MT5Client()
    assert client.READ_ONLY is True
    assert "read_only=True" in repr(client)

    with pytest.raises(NotImplementedError) as exc_info:
        client.order_send(symbol="NQ", action=1)
    assert "R9" in str(exc_info.value)
    assert "lecture seule" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 2. Statut honnàƒÂªte : Terminal absent / échec IPC
# ---------------------------------------------------------------------------


def test_status_terminal_not_found(mock_mt5):
    """Simule l'absence du terminal MT5 sur la machine hàƒÂ´te."""
    mock_mt5.initialize.return_value = False
    mock_mt5.last_error.return_value = (-10003, "IPC initialize failed, MetaTrader 5 x64 not found")

    client = MT5Client(login=11111, server="DemoServer")
    status = client.connect()

    assert isinstance(status, MT5Status)
    assert status.is_ok is False
    assert status.connected is False
    assert status.terminal_detected is False
    assert status.error_code == -10003
    assert "non d\u00e9tect\u00e9" in status.reason.lower()
    assert "IPC initialize failed" in status.reason


def test_import_when_disconnected_returns_degraded(mock_mt5, mem_conn, config):
    """Vérifie que l'import renvoie un statut Dàƒâ€°GRADàƒâ€° propre si le terminal est absent."""
    mock_mt5.initialize.return_value = False
    mock_mt5.last_error.return_value = (-10003, "Terminal not found")

    client = MT5Client()
    summary = client.import_trades_to_journal(mem_conn, config=config)

    assert isinstance(summary, MT5ImportSummary)
    assert summary.imported == 0
    assert len(summary.errors) == 1
    assert "inactive" in summary.errors[0].lower()


# ---------------------------------------------------------------------------
# 3. Authentification échouée
# ---------------------------------------------------------------------------


def test_status_login_failed(mock_mt5):
    """Simule un échec de login sur un serveur MT5."""
    mock_mt5.initialize.return_value = True
    mock_mt5.account_info.return_value = None
    mock_mt5.login.return_value = False
    mock_mt5.last_error.return_value = (-1, "Invalid credentials")

    client = MT5Client(login=22222, password="wrong_password", server="DemoServer")
    status = client.connect()

    assert status.is_ok is False
    assert status.status == "D\u00c9GRAD\u00c9"
    assert "\u00c9chec d'authentification" in status.reason
    mock_mt5.shutdown.assert_called()


# ---------------------------------------------------------------------------
# 4. Connexion réussie et lecture de compte
# ---------------------------------------------------------------------------


def test_successful_connection_and_account_info(mock_mt5):
    """Simule une connexion réussie avec lecture des KPIs de compte."""
    mock_mt5.initialize.return_value = True

    mock_acc = MagicMock()
    mock_acc._asdict.return_value = {
        "login": 987654,
        "trade_mode": 0,  # DEMO
        "server": "ICMarkets-Demo",
        "currency": "USD",
        "balance": 25000.0,
        "equity": 25420.50,
        "profit": 420.50,
        "margin": 1200.0,
        "margin_free": 24220.50,
        "margin_level": 2118.37,
        "leverage": 100,
        "company": "IC Markets Global",
        "name": "Trader Cockpit",
    }
    mock_acc.login = 987654
    mock_mt5.account_info.return_value = mock_acc

    client = MT5Client(login=987654, password="valid_password", server="ICMarkets-Demo")
    status = client.connect()

    assert status.status == "OK"
    assert status.is_ok is True
    assert status.connected is True
    assert status.account_login == 987654
    assert status.balance == 25000.0
    assert status.equity == 25420.50

    acc_info = client.get_account_info()
    assert acc_info is not None
    assert acc_info.login == 987654
    assert acc_info.trade_mode == "DEMO"
    assert acc_info.currency == "USD"
    assert acc_info.balance == 25000.0


# ---------------------------------------------------------------------------
# 5. Récupération des positions ouvertes
# ---------------------------------------------------------------------------


def test_get_open_positions(mock_mt5):
    """Simule la récupération des positions ouvertes en cours."""
    mock_mt5.initialize.return_value = True
    mock_acc = MagicMock()
    mock_acc._asdict.return_value = {"login": 987654, "balance": 10000.0}
    mock_mt5.account_info.return_value = mock_acc

    # Simulation d'une position longue ouverte
    pos1 = MagicMock()
    pos1._asdict.return_value = {
        "ticket": 501,
        "symbol": "NQ",
        "type": 0,  # BUY
        "volume": 2.0,
        "price_open": 20850.25,
        "sl": 20800.0,
        "tp": 20950.0,
        "price_current": 20880.0,
        "profit": 119.0,
        "swap": 0.0,
        "time": 1727712000,  # Horodatage epoch
        "comment": "BOS retest",
    }

    mock_mt5.positions_get.return_value = (pos1,)

    client = MT5Client()
    positions = client.get_open_positions()

    assert len(positions) == 1
    p = positions[0]
    assert p.ticket == 501
    assert p.symbol == "NQ"
    assert p.direction == TradeDirection.LONG
    assert p.price_open == 20850.25
    assert p.sl == 20800.0
    assert p.tp == 20950.0
    assert p.price_current == 20880.0
    assert p.profit == 119.0
    assert p.time_open_ny.tzinfo is not None
    assert p.time_open_algiers.tzinfo is not None


# ---------------------------------------------------------------------------
# 6. Réconciliation des deals et Stop Loss initial
# ---------------------------------------------------------------------------


def test_closed_trades_reconciliation_and_sl(mock_mt5):
    """Vérifie l'association deal entrée/sortie et la récupération du SL d'ordre."""
    mock_mt5.initialize.return_value = True
    mock_acc = MagicMock()
    mock_acc._asdict.return_value = {"login": 987654, "balance": 10000.0}
    mock_mt5.account_info.return_value = mock_acc

    # Position 7001 : Entrée LONG 20800, Sortie TP 20850
    d_in = MagicMock()
    d_in._asdict.return_value = {
        "ticket": 1001,
        "position_id": 7001,
        "symbol": "NAS100",
        "type": 0,  # BUY
        "entry": 0,  # IN
        "volume": 1.0,
        "price": 20800.0,
        "profit": 0.0,
        "commission": -2.5,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727712000,
        "time_msc": 1727712000000,
        "comment": "Buy limit",
    }

    d_out = MagicMock()
    d_out._asdict.return_value = {
        "ticket": 1002,
        "position_id": 7001,
        "symbol": "NAS100",
        "type": 1,  # SELL
        "entry": 1,  # OUT
        "volume": 1.0,
        "price": 20850.0,
        "profit": 100.0,
        "commission": -2.5,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727715600,
        "time_msc": 1727715600000,
        "reason": 4,  # TP
        "comment": "[tp 20850.00]",
    }

    # Opération non-trade (balance / dépàƒÂ´t) -> doit àƒÂªtre ignorée
    d_balance = MagicMock()
    d_balance._asdict.return_value = {
        "ticket": 999,
        "position_id": 0,
        "symbol": "",
        "type": 2,  # BALANCE
        "entry": 0,
        "volume": 0.0,
        "price": 0.0,
        "profit": 1000.0,
        "commission": 0.0,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727700000,
        "time_msc": 1727700000000,
        "comment": "Deposit",
    }

    mock_mt5.history_deals_get.return_value = (d_in, d_out, d_balance)

    # Ordre associé avec stop loss initial
    order_mock = MagicMock()
    order_mock._asdict.return_value = {
        "ticket": 3001,
        "position_id": 7001,
        "sl": 20760.0,
        "tp": 20850.0,
    }
    mock_mt5.history_orders_get.return_value = (order_mock,)

    client = MT5Client()
    trades = client.get_closed_trades()

    assert len(trades) == 1
    tr = trades[0]
    assert tr.position_id == 7001
    assert tr.symbol == "NAS100"
    assert tr.direction == TradeDirection.LONG
    assert tr.entry_price == 20800.0
    assert tr.exit_price == 20850.0
    assert tr.stop_price == 20760.0  # SL initial récupéré
    assert tr.take_profit == 20850.0
    assert tr.pnl == 100.0
    assert tr.commission == -5.0  # -2.5 + -2.5
    assert tr.exit_reason == "TP1"


# ---------------------------------------------------------------------------
# 7. Auto-import vers Journal SQLite & Déduplication
# ---------------------------------------------------------------------------


def test_import_trades_to_journal_and_deduplication(mock_mt5, mem_conn, config):
    """Vérifie l'importation complàƒÂ¨te dans SQLite, le calcul du R et le rejet des doublons."""
    mock_mt5.initialize.return_value = True
    mock_acc = MagicMock()
    mock_acc._asdict.return_value = {"login": 987654, "balance": 10000.0}
    mock_mt5.account_info.return_value = mock_acc

    # Trade 1 : Gagnant +1.25R (Risk 40pts, Gain 50pts)
    t1_in = MagicMock()
    t1_in._asdict.return_value = {
        "ticket": 201,
        "position_id": 8001,
        "symbol": "MNQ",
        "type": 0,
        "entry": 0,
        "volume": 1.0,
        "price": 20800.0,
        "profit": 0.0,
        "commission": 0.0,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727712000,
        "time_msc": 1727712000000,
    }
    t1_out = MagicMock()
    t1_out._asdict.return_value = {
        "ticket": 202,
        "position_id": 8001,
        "symbol": "MNQ",
        "type": 1,
        "entry": 1,
        "volume": 1.0,
        "price": 20850.0,
        "profit": 100.0,
        "commission": 0.0,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727715600,
        "time_msc": 1727715600000,
        "reason": 4,
    }

    # Trade 2 : Perdant SHORT -1.0R (Entrée 20900, SL 20940, Sortie 20940)
    t2_in = MagicMock()
    t2_in._asdict.return_value = {
        "ticket": 203,
        "position_id": 8002,
        "symbol": "MNQ",
        "type": 1,  # SELL
        "entry": 0,
        "volume": 1.0,
        "price": 20900.0,
        "profit": 0.0,
        "commission": 0.0,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727720000,
        "time_msc": 1727720000000,
    }
    t2_out = MagicMock()
    t2_out._asdict.return_value = {
        "ticket": 204,
        "position_id": 8002,
        "symbol": "MNQ",
        "type": 0,  # BUY
        "entry": 1,
        "volume": 1.0,
        "price": 20940.0,
        "profit": -80.0,
        "commission": 0.0,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727723600,
        "time_msc": 1727723600000,
        "reason": 3,  # SL
    }

    mock_mt5.history_deals_get.return_value = (t1_in, t1_out, t2_in, t2_out)

    def mock_orders_get(position=None):
        if position == 8001:
            o = MagicMock()
            o._asdict.return_value = {"sl": 20760.0, "tp": 20850.0}
            return (o,)
        if position == 8002:
            o = MagicMock()
            o._asdict.return_value = {"sl": 20940.0, "tp": 20800.0}
            return (o,)
        return ()

    mock_mt5.history_orders_get.side_effect = mock_orders_get

    client = MT5Client()

    # Premier import : doit importer les 2 trades
    sum1 = client.import_trades_to_journal(mem_conn, config=config)
    assert sum1.is_success is True
    assert sum1.imported == 2
    assert sum1.duplicates == 0

    saved_trades = load_trades(mem_conn)
    assert len(saved_trades) == 2

    # Vérification des calculs de R
    t1 = next(t for t in saved_trades if t.trade_id == "mt5_8001")
    assert t1.direction == TradeDirection.LONG
    assert t1.outcome == TradeOutcome.WIN
    assert t1.r_realized > 1.2  # 50 / 40 = 1.25R
    assert t1.session_date != ""

    t2 = next(t for t in saved_trades if t.trade_id == "mt5_8002")
    assert t2.direction == TradeDirection.SHORT
    assert t2.outcome == TradeOutcome.LOSS
    assert t2.r_realized == -1.0  # -40 / 40 = -1.0R

    # DeuxiàƒÂ¨me import : màƒÂªmes deals -> 100 % doublons ignorés
    sum2 = client.import_trades_to_journal(mem_conn, config=config)
    assert sum2.imported == 0
    assert sum2.duplicates == 2

    saved_after = load_trades(mem_conn)
    assert len(saved_after) == 2


# ---------------------------------------------------------------------------
# 8. Gestion sécurisée des identifiants dans .env
# ---------------------------------------------------------------------------


def test_env_credentials_security_and_preservation(tmp_path, monkeypatch):
    """Vérifie la mise àƒÂ  jour ciblée de .env sans altérer les autres lignes ni logger."""
    env_file = tmp_path / ".env"
    initial_content = (
        "# Configuration existante\n"
        "FRED_API_KEY=test_fred_key_12345\n"
        "GEMINI_API_KEY=secret_gemini\n"
        "# Commentaire préservé\n"
    )
    env_file.write_text(initial_content, encoding="utf-8")

    # 1. Sauvegarde des identifiants MT5
    ok = save_mt5_credentials(
        login=1234567,
        password="MySecretPassword123!",
        server="BrokerSC-Demo",
        path="C:\\Program Files\\MetaTrader 5\\terminal64.exe",
        broker_tz="UTC",
        env_path=env_file,
    )
    assert ok is True

    # 2. Vérification que les anciennes variables et commentaires sont restés intacts
    updated_text = env_file.read_text(encoding="utf-8")
    assert "FRED_API_KEY=test_fred_key_12345" in updated_text
    assert "GEMINI_API_KEY=secret_gemini" in updated_text
    assert "# Commentaire préservé" in updated_text

    # 3. Vérification de la lecture sécurisée (mot de passe masqué)
    status_creds = get_mt5_credentials(env_path=env_file)
    assert status_creds["login"] == 1234567
    assert status_creds["server"] == "BrokerSC-Demo"
    assert status_creds["path"] == "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
    assert status_creds["has_password"] is True
    # Pas de clé 'password' exposée dans le dict public
    assert "password" not in status_creds

    # 4. Lecture interne brute pour le client
    raw_creds = get_mt5_raw_credentials(env_path=env_file)
    assert raw_creds["password"] == "MySecretPassword123!"

    # 5. Sauvegarde avec mot de passe vide -> préserve le mot de passe existant
    ok2 = save_mt5_credentials(
        login=1234567,
        password="",  # vide
        server="BrokerSC-Live",
        env_path=env_file,
    )
    assert ok2 is True
    raw_creds_after = get_mt5_raw_credentials(env_path=env_file)
    assert raw_creds_after["server"] == "BrokerSC-Live"
    assert raw_creds_after["password"] == "MySecretPassword123!"


# ---------------------------------------------------------------------------
# 9. Conversion rigoureuse des fuseaux horaires (zoneinfo)
# ---------------------------------------------------------------------------


def test_timezone_conversion_broker_to_ny_and_algiers():
    """Vérifie la conversion correcte des horodatages vers NY et Alger via zoneinfo."""
    client = MT5Client(broker_tz="UTC")

    # Horodatage 2026-10-05 14:30:00 UTC (10:30 NY / 15:30 Alger)
    epoch_ts = int(datetime(2026, 10, 5, 14, 30, 0, tzinfo=timezone.utc).timestamp())

    t_utc, t_ny, t_algiers = client._convert_broker_time(epoch_ts)

    # Vérification America/New_York (UTC-4 en EDT début octobre 2026)
    assert t_ny.tzinfo is not None
    assert t_ny.tzinfo.key == "America/New_York"
    assert t_ny.hour == 10
    assert t_ny.minute == 30

    # Vérification Africa/Algiers (UTC+1 toute l'année)
    assert t_algiers.tzinfo is not None
    assert t_algiers.tzinfo.key == "Africa/Algiers"
    assert t_algiers.hour == 15
    assert t_algiers.minute == 30


# ---------------------------------------------------------------------------
# 10. Tests d'Acceptance Spécifiques MT5 Mocké (A)
# ---------------------------------------------------------------------------


def test_mt5_mock_winning_trade(mock_mt5, mem_conn, config):
    """Couvre : Trade gagnant MT5 (net profit > 0, outcome WIN, R > 0, SL/TP pré-remplis)."""
    mock_mt5.initialize.return_value = True
    mock_acc = MagicMock()
    mock_acc._asdict.return_value = {"login": 123456, "balance": 50000.0}
    mock_mt5.account_info.return_value = mock_acc

    # Deals round-trip LONG : entrée 20800.0, sortie 20880.0, net profit +155.0
    d_in = MagicMock()
    d_in._asdict.return_value = {
        "ticket": 901,
        "position_id": 9901,
        "symbol": "NQ",
        "type": 0,  # BUY
        "entry": 0,
        "volume": 1.0,
        "price": 20800.0,
        "profit": 0.0,
        "commission": -2.5,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727712000,
        "time_msc": 1727712000000,
    }
    d_out = MagicMock()
    d_out._asdict.return_value = {
        "ticket": 902,
        "position_id": 9901,
        "symbol": "NQ",
        "type": 1,  # SELL
        "entry": 1,
        "volume": 1.0,
        "price": 20880.0,
        "profit": 160.0,
        "commission": -2.5,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727715600,
        "time_msc": 1727715600000,
        "reason": 4,  # TP
    }
    mock_mt5.history_deals_get.return_value = (d_in, d_out)

    # Ordre avec SL initial 20760.0 (risque 40 pts) et TP 20880.0
    order_mock = MagicMock()
    order_mock._asdict.return_value = {
        "ticket": 401,
        "position_id": 9901,
        "sl": 20760.0,
        "tp": 20880.0,
    }
    mock_mt5.history_orders_get.return_value = (order_mock,)

    client = MT5Client()
    summary = client.import_trades_to_journal(mem_conn, config=config)

    assert summary.is_success is True
    assert summary.imported == 1

    trades = load_trades(mem_conn)
    assert len(trades) == 1
    t = trades[0]

    # Vérifications auto-remplissage : prix d'entrée, SL, TP, gain/perte
    assert t.entry_price == 20800.0
    assert t.stop_price == 20760.0
    assert t.tp1_price == 20880.0
    assert t.exit_price == 20880.0
    assert t.outcome == TradeOutcome.WIN  # Trade gagnant
    assert t.r_realized > 1.8  # (80 - 5pts frais) / 40 à¢â€°Ë† 1.875R
    assert "GAIN" in t.notes
    assert "+$155.00" in t.notes


def test_mt5_mock_losing_trade(mock_mt5, mem_conn, config):
    """Couvre : Trade perdant MT5 (net profit < 0, outcome LOSS, R < 0, SL/TP pré-remplis)."""
    mock_mt5.initialize.return_value = True
    mock_acc = MagicMock()
    mock_acc._asdict.return_value = {"login": 123456, "balance": 50000.0}
    mock_mt5.account_info.return_value = mock_acc

    # Deals round-trip LONG touché au Stop Loss : entrée 20800.0, sortie 20760.0 (-85.0 net)
    d_in = MagicMock()
    d_in._asdict.return_value = {
        "ticket": 903,
        "position_id": 9902,
        "symbol": "NQ",
        "type": 0,  # BUY
        "entry": 0,
        "volume": 1.0,
        "price": 20800.0,
        "profit": 0.0,
        "commission": -2.5,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727712000,
        "time_msc": 1727712000000,
    }
    d_out = MagicMock()
    d_out._asdict.return_value = {
        "ticket": 904,
        "position_id": 9902,
        "symbol": "NQ",
        "type": 1,  # SELL
        "entry": 1,
        "volume": 1.0,
        "price": 20760.0,
        "profit": -80.0,
        "commission": -2.5,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727715600,
        "time_msc": 1727715600000,
        "reason": 3,  # SL
    }
    mock_mt5.history_deals_get.return_value = (d_in, d_out)

    order_mock = MagicMock()
    order_mock._asdict.return_value = {
        "ticket": 402,
        "position_id": 9902,
        "sl": 20760.0,
        "tp": 20880.0,
    }
    mock_mt5.history_orders_get.return_value = (order_mock,)

    client = MT5Client()
    summary = client.import_trades_to_journal(mem_conn, config=config)

    assert summary.is_success is True
    assert summary.imported == 1

    trades = load_trades(mem_conn)
    assert len(trades) == 1
    t = trades[0]

    assert t.entry_price == 20800.0
    assert t.stop_price == 20760.0
    assert t.tp1_price == 20880.0
    assert t.exit_price == 20760.0
    assert t.outcome == TradeOutcome.LOSS  # Trade perdant
    assert t.r_realized < -0.9  # R négatif
    assert "PERTE" in t.notes
    assert "-$85.00" in t.notes


def test_mt5_mock_missing_sl_and_tp(mock_mt5, mem_conn, config):
    """Couvre : Trade sans SL ni TP attachés.

    RàƒÂ¨gles d'honnàƒÂªteté :
    - Stop loss laissé àƒÂ  0.0 (non défini), TP laissé àƒÂ  None
    - Mention explicite 'non défini' dans les notes
    - Aucun chiffre inventé
    - Résultat Gain/Perte déterminé honnàƒÂªtement par le net profit MT5
    - R réalisé reste 0.0 (pas de faux R calculé sur un risque erroné).
    """
    mock_mt5.initialize.return_value = True
    mock_acc = MagicMock()
    mock_acc._asdict.return_value = {"login": 123456, "balance": 50000.0}
    mock_mt5.account_info.return_value = mock_acc

    # Position sans SL ni TP fermée manuellement avec profit net positif +200$
    d_in = MagicMock()
    d_in._asdict.return_value = {
        "ticket": 905,
        "position_id": 9903,
        "symbol": "MNQ",
        "type": 0,
        "entry": 0,
        "volume": 2.0,
        "price": 20800.0,
        "profit": 0.0,
        "commission": 0.0,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727712000,
        "time_msc": 1727712000000,
    }
    d_out = MagicMock()
    d_out._asdict.return_value = {
        "ticket": 906,
        "position_id": 9903,
        "symbol": "MNQ",
        "type": 1,
        "entry": 1,
        "volume": 2.0,
        "price": 20850.0,
        "profit": 200.0,
        "commission": 0.0,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1727715600,
        "time_msc": 1727715600000,
        "reason": 0,  # Sortie manuelle
    }
    mock_mt5.history_deals_get.return_value = (d_in, d_out)

    # Ordres existants mais sans SL ni TP
    order_mock = MagicMock()
    order_mock._asdict.return_value = {
        "ticket": 403,
        "position_id": 9903,
        "sl": 0.0,  # Aucun SL
        "tp": 0.0,  # Aucun TP
    }
    mock_mt5.history_orders_get.return_value = (order_mock,)

    client = MT5Client()
    summary = client.import_trades_to_journal(mem_conn, config=config)

    assert summary.is_success is True
    assert summary.imported == 1

    trades = load_trades(mem_conn)
    assert len(trades) == 1
    t = trades[0]

    assert t.entry_price == 20800.0
    assert t.exit_price == 20850.0
    # Stop loss et Take Profit absents : non inventés
    assert t.stop_price == 0.0
    assert t.tp1_price is None
    # Résultat déduit honnàƒÂªtement du profit net
    assert t.outcome == TradeOutcome.WIN
    # R réalisé nul car absence de risque initial
    assert t.r_realized == 0.0
    assert "SL: non d\u00e9fini" in t.notes
    # Mentions explicites "non défini"


def test_mt5_mock_terminal_down(mock_mt5, mem_conn, config):
    """Couvre : Terminal MT5 indisponible (down/fermé/non installé).

    Vérifie le statut Dàƒâ€°GRADàƒâ€° explicite sans crash ni donnée inventée.
    """
    mock_mt5.initialize.return_value = False
    mock_mt5.last_error.return_value = (-10004, "Terminal MT5 unavailable or terminated")

    client = MT5Client()

    # 1. Statut de santé
    status = client.get_status()
    assert status.is_ok is False
    assert status.connected is False
    assert status.terminal_detected is False
    assert "Terminal MT5 unavailable" in status.reason

    # 2. Tentative d'import
    summary = client.import_trades_to_journal(mem_conn, config=config)
    assert summary.imported == 0
    assert len(summary.errors) == 1
    assert "inactive" in summary.errors[0].lower()

    # 3. Base de données intacte
    trades = load_trades(mem_conn)
    assert len(trades) == 0


def test_compute_r_without_stop_loss():
    """Vérifie que sans Stop Loss (stop_price=0), le R calculé est forcé àƒÂ  0.0."""
    from nqcockpit.journal.models import TradeDirection, TradeEntry
    trade = TradeEntry(
        trade_id="fake_123",
        recorded_at=None,
        session_date="2026-10-06",
        entry_price=20000.0,
        stop_price=0.0,
        exit_price=20050.0,
        direction=TradeDirection.LONG,
    )
    assert trade.compute_r() == 0.0
def test_history_deals_get_kwargs_bug(monkeypatch):
    """
    Reproduit le comportement réel mesuré en live :
    le SDK C rejette kwargs pour date_from/date_to mais accepte le positionnel.
    """
    from datetime import datetime, timezone

    from nqcockpit.broker.mt5_client import MT5Client

    def mock_history_deals_get(*args, **kwargs):
        if kwargs and ('date_from' in kwargs or 'date_to' in kwargs):
            return None # L'API C renvoie None ou crashe si on utilise des kwargs pour les dates

        # Si appelé avec des positionnels, on simule 2 deals pour notre trade GOLD
        from collections import namedtuple
        Deal = namedtuple('Deal', ['ticket', 'symbol', 'type', 'entry', 'profit',
                     'position_id', 'time', 'time_msc', 'volume', 'price'])
        return [
            Deal(1, 'GOLD', 1, 0, 0.0, 100, 10000, 10000000, 1.0, 2000.0),
            Deal(2, 'GOLD', 0, 1, -41.91, 100, 20000, 20000000, 1.0, 1950.0)
        ]

    import nqcockpit.broker.mt5_client as mt5_module
    class DummyMT5:
        DEAL_TYPE_BUY = 0
        DEAL_TYPE_SELL = 1
        DEAL_ENTRY_IN = 0
        DEAL_ENTRY_OUT = 1
        DEAL_REASON_SL = 3
        DEAL_REASON_TP = 4
        def initialize(self, *args, **kwargs): return True
        def login(self, *args, **kwargs): return True
        def history_deals_get(self, *args, **kwargs): return mock_history_deals_get(*args, **kwargs)

    monkeypatch.setattr(mt5_module, "mt5", DummyMT5())
    monkeypatch.setattr(mt5_module, "HAS_MT5_PACKAGE", True)

    client = MT5Client()
    client._is_connected = True

    trades = client.get_closed_trades(
        date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        date_to=datetime.now(timezone.utc)
    )
    assert len(trades) == 1
    assert trades[0].symbol == "GOLD"
    assert trades[0].pnl == -41.91


def test_mt5_grouping_by_position_id(monkeypatch):
    """
    Vérifie le regroupement :
    - deux deals d'entrée et deux de sortie avec le màªme position_id -> un seul trade, PnL = somme
    - position_id absent -> repli sur ticket, pas de fusion erronée
    """
    from collections import namedtuple
    from datetime import datetime, timezone

    from nqcockpit.broker.mt5_client import MT5Client

    Deal = namedtuple('Deal', ['ticket', 'symbol', 'type', 'entry', 'profit',
                     'position_id', 'time', 'time_msc', 'volume', 'price'])

    def mock_history_deals_get(*args, **kwargs):
        return [
            # Trade 1 : 2 entries, 2 exits sur position_id 100
            Deal(1, 'GOLD', 0, 0, 0.0, 100, 10000, 10000, 1.0, 2000.0),
            Deal(2, 'GOLD', 0, 0, 0.0, 100, 10001, 10001, 1.0, 2001.0),
            Deal(3, 'GOLD', 1, 1, 50.0, 100, 10002, 10002, 1.0, 2050.0),
            Deal(4, 'GOLD', 1, 1, -10.0, 100, 10003, 10003, 1.0, 1991.0),

            # Trade 2 : position_id 0, ticket 200
            Deal(200, 'GOLD', 1, 0, 0.0, 0, 20000, 20000, 1.0, 2000.0),
            Deal(201, 'GOLD', 0, 1, 100.0, 0, 20001, 20001, 1.0, 1900.0),
            # Wait, pas de lien entre eux si pos_id=0!
            # Si pos_id=0, repli sur ticket. Donc ticket 200 sera pos_id=200, ticket 201 pos_id=201.
            # Ils ne seront pas fusionnés!
        ]

    import nqcockpit.broker.mt5_client as mt5_module
    class DummyMT5:
        DEAL_TYPE_BUY = 0
        DEAL_TYPE_SELL = 1
        DEAL_ENTRY_IN = 0
        DEAL_ENTRY_OUT = 1
        DEAL_REASON_SL = 3
        DEAL_REASON_TP = 4
        def initialize(self, *args, **kwargs): return True
        def login(self, *args, **kwargs): return True
        def history_deals_get(self, *args, **kwargs): return mock_history_deals_get(*args, **kwargs)

    monkeypatch.setattr(mt5_module, "mt5", DummyMT5())
    monkeypatch.setattr(mt5_module, "HAS_MT5_PACKAGE", True)

    client = MT5Client()
    client._is_connected = True
    trades = client.get_closed_trades(
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime.now(timezone.utc)
    )

    # On s'attend à  ce que le Trade 1 soit bien fusionné : pos_id=100, PnL=40.0
    t1 = next((t for t in trades if t.position_id == 100), None)
    assert t1 is not None
    assert t1.pnl == 40.0
    assert t1.volume == 2.0

    # Pour le trade 2, puisque pos_id=0, ils sont séparés par ticket,
    # mais une position sans entry ou sans exit est ignorée.
    # Donc ticket 200 a entry mais pas exit -> ignoré.
    # Ticket 201 a exit mais pas entry -> ignoré
    # (sauf si history_deals_get par pos_id fonctionnait).
    # Vérifions que le repli s'effectue sans fusionner par erreur.
    assert len([t for t in trades if t.position_id in (200, 201)]) == 0

def test_no_sensitive_logs(monkeypatch, caplog):
    """Aucun log de login, serveur ni solde."""
    import logging

    import nqcockpit.broker.mt5_client as mt5_module
    from nqcockpit.broker.mt5_client import MT5Client
    class DummyMT5:
        def initialize(self, *args, **kwargs):
            raise Exception("Erreur forcée pour déclencher un log")
            return False

    monkeypatch.setattr(mt5_module, "mt5", DummyMT5())
    monkeypatch.setattr(mt5_module, "HAS_MT5_PACKAGE", True)

    with caplog.at_level(logging.WARNING):
        client = MT5Client(login="999888", password="SECRET_PASSWORD", server="BROKER_SERVER")
        client.connect()

    for record in caplog.records:
        assert "999888" not in record.message
        assert "SECRET_PASSWORD" not in record.message
        assert "BROKER_SERVER" not in record.message


def test_import_ignores_gold_and_out_of_scope(monkeypatch, mem_conn):
    """Vérifie que les symboles hors NQ/MNQ (ex. GOLD) sont ignorés."""
    import nqcockpit.broker.mt5_client as mt5_module
    from nqcockpit.broker.mt5_client import MT5Client

    class DummyMT5:
        def initialize(self, *args, **kwargs): return True
        def login(self, *args, **kwargs): return True
        def account_info(self):
            class Acc:
                def _asdict(self): return {"login": 123456, "balance": 10000.0}
            return Acc()
        def history_deals_get(self, *args, **kwargs):
            class Deal:
                def __init__(self, **kw): self.__dict__.update(kw)
                def _asdict(self): return self.__dict__

            return (
                Deal(
                        ticket=1, position_id=100, symbol="GOLD", type=0, entry=0,
                        volume=1.0, price=2000.0, profit=0.0, commission=0, swap=0,
                        fee=0, time=1700000000, time_msc=1700000000000
                    ),
                Deal(
                        ticket=2, position_id=100, symbol="GOLD", type=1, entry=1,
                        volume=1.0, price=2010.0, profit=100.0, commission=0, swap=0,
                        fee=0, time=1700001000, time_msc=1700001000000, reason=4
                    ),
            )
        def history_orders_get(self, *args, **kwargs): return ()

    monkeypatch.setattr(mt5_module, "mt5", DummyMT5())
    monkeypatch.setattr(mt5_module, "HAS_MT5_PACKAGE", True)

    client = MT5Client()
    summary = client.import_trades_to_journal(mem_conn)

    assert summary.is_success is True
    assert summary.total_positions == 1
    assert summary.ignored_out_of_scope == 1
    assert summary.imported == 0

    from nqcockpit.journal.store import load_trades
    trades = load_trades(mem_conn)
    assert len(trades) == 0
