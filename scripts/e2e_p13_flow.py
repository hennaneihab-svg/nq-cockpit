"""Script d'exécution du parcours complet P13 et capture des 5 pages de l'UI."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nqcockpit.config import load_config
from nqcockpit.discipline.engine import evaluate_checklist
from nqcockpit.discipline.models import (
    ChecklistVerdict,
    PreTradeChecklist,
)
from nqcockpit.discipline.risk import compute_position_size
from nqcockpit.journal.engine import compute_performance_stats, detect_period_tilt_alerts
from nqcockpit.journal.models import (
    GammaRegime,
    TradeDirection,
    TradeEntry,
    TradeOutcome,
    VolRegime,
)
from nqcockpit.journal.store import init_journal_db, load_trades, save_trade
from nqcockpit.profile.engine import build_day_profile

LOG_FILE = Path("logs/p13_execution.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("p13_flow")


def run_parcours():
    logger.info("=== DÉBUT DU PARCOURS COMPLET P13 ===")
    config = load_config()

    # 1. SNAPSHOT (P04)
    logger.info("--- ÉTAPE 1 : Exécution du snapshot de niveaux (CBOE & Marché) ---")
    res_snap = subprocess.run(
        [sys.executable, "-m", "nqcockpit", "snapshot"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    logger.info("Snapshot exit code : %d", res_snap.returncode)
    assert res_snap.returncode == 0, f"Erreur snapshot : {res_snap.stderr}"
    logger.info("Snapshot terminé avec succès.")

    # 2. PROFIL DE SÉANCE (P08)
    logger.info("--- ÉTAPE 2 : Construction du profil de séance unifié ---")
    import sqlite3
    conn = sqlite3.connect(config.data.db_path)
    now_utc = datetime.now(timezone.utc)
    profile = build_day_profile(conn=conn, config=config, now_utc=now_utc)
    logger.info("Profil généré pour la séance : %s", profile.target_date)
    logger.info(
        "Régime Gamma : %s | Volatilité : %s | Expected Move : %.1f pts",
        profile.gamma_regime,
        profile.volatility_regime,
        profile.base_expected_move_pts,
    )
    logger.info("Trading autorisé : %s", profile.no_trade.is_trading_allowed)
    conn.close()

    # 3. CHECKLIST DE DISCIPLINE (P09)
    logger.info("--- ÉTAPE 3 : Évaluation de la checklist pré-trade ---")
    sizing = compute_position_size(
        instrument="MNQ",
        account_size=50000.0,
        risk_pct=1.0,
        stop_points=25.0,
        config=config,
    )
    logger.info(
        "Sizing calculé : %d contrats MNQ pour un stop de %.1f pts (Risque : %.2f $)",
        sizing.contracts,
        sizing.stop_points,
        sizing.actual_risk_dollars,
    )

    checklist = PreTradeChecklist(
        p08_reviewed=True,
        trading_plan="Retest VWAP avec absorption vendeur et ratio 2:1",
        sizing_result=sizing,
        event_risk_tier1_red=False,
    )
    from nqcockpit.discipline.engine import evaluate_session_state
    # A. Test au moment présent (hors fenêtre Kill Zone -> verrou normal)
    session_state_now = evaluate_session_state(
        trades=[],
        now=now_utc,
        config=config,
    )
    verdict_now = evaluate_checklist(
        checklist=checklist,
        session_state=session_state_now,
        config=config,
    )
    logger.info(
        "Verdict checklist instantané (hors KZ) : %s (passed=%s, motifs=%s)",
        verdict_now.verdict,
        verdict_now.passed,
        verdict_now.blocking_reasons,
    )

    # B. Test simulé dans la Kill Zone (16h00 Alger -> GO validé)
    tz_algiers = ZoneInfo("Africa/Algiers")
    now_in_kz = datetime(2026, 10, 5, 16, 0, 0, tzinfo=tz_algiers).astimezone(timezone.utc)
    session_state_kz = evaluate_session_state(
        trades=[],
        now=now_in_kz,
        config=config,
    )
    verdict_kz = evaluate_checklist(
        checklist=checklist,
        session_state=session_state_kz,
        config=config,
    )
    logger.info(
        "Verdict checklist en Kill Zone 16h00 Alger : %s (passed=%s, motifs=%s)",
        verdict_kz.verdict,
        verdict_kz.passed,
        verdict_kz.blocking_reasons,
    )
    assert verdict_kz.verdict == ChecklistVerdict.GO, "La checklist en KZ doit être GO"

    # 4. TRADE FICTIF DE VALIDATION (P10)
    logger.info("--- ÉTAPE 4 : Enregistrement d'un trade fictif dans le journal SQLite ---")
    conn_j = init_journal_db(config.data.db_path)
    trade_fictif_id = f"p13-fictif-{int(time.time())}"
    trade_fictif = TradeEntry(
        trade_id=trade_fictif_id,
        recorded_at=now_utc,
        session_date=profile.target_date,
        instrument="MNQ",
        direction=TradeDirection.LONG,
        entry_price=30850.0,
        stop_price=30825.0,
        tp1_price=30900.0,
        exit_price=30900.0,
        exit_reason="TP1 atteint sur niveau VWAP",
        r_realized=2.0,
        outcome=TradeOutcome.WIN,
        window_name="KZ1 (15h30–17h00 Alger)",
        gamma_regime=GammaRegime.POSITIVE,
        vol_regime=VolRegime.NORMAL,
        day_of_week=now_utc.weekday(),
        setup_tag="VWAP_pullback_long",
        notes="Trade fictif de validation P13 — respects stricts des seuils de risque",
        contracts=sizing.contracts,
        screenshot_path="",
    )
    save_trade(conn_j, trade_fictif)
    logger.info("Trade fictif enregistré avec succès : ID %s", trade_fictif_id)

    # 5. COACHING & ANALYTICS (P11)
    logger.info("--- ÉTAPE 5 : Calcul des analytics et coaching post-séance ---")
    all_trades = load_trades(conn_j)
    stats = compute_performance_stats(all_trades, min_trades=5, config=config)
    tilts = detect_period_tilt_alerts(all_trades, config)
    logger.info(
        "Nombre total de trades : %d | Win rate : %.1f%% | Échantillon suffisant : %s",
        stats.n_trades,
        (stats.win_rate or 0.0) * 100,
        stats.sample_sufficient,
    )
    logger.info("Alertes de tilt détectées : %d", len(tilts))
    conn_j.close()

    logger.info("=== PARCOURS COMPLET P13 ACHEVÉ AVEC SUCCÈS ===")


def capture_pages():
    logger.info("--- CAPTURE D'ÉCRAN DES 5 PAGES DU COCKPIT VIA EDGE HEADLESS ---")
    port = 8507
    edge_exe = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    assert edge_exe.exists(), f"Navigateur Edge introuvable : {edge_exe}"

    cmd_streamlit = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "src/nqcockpit/ui/app.py",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--theme.base",
        "dark",
    ]
    logger.info("Démarrage du serveur Streamlit sur le port %d...", port)
    proc = subprocess.Popen(
        cmd_streamlit,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url_base = f"http://localhost:{port}"
    logger.info("Attente de la disponibilité de %s...", url_base)
    ready = False
    for attempt in range(40):
        try:
            with urllib.request.urlopen(url_base, timeout=1.5) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.5)

    if not ready:
        proc.terminate()
        raise RuntimeError("Le serveur Streamlit n'a pas répondu à temps.")

    logger.info("Serveur Streamlit en ligne et réactif.")
    time.sleep(2)  # Pause pour laisser le premier rendu se stabiliser

    pages = [
        ("cockpit", "reports/p13_01_cockpit.png"),
        ("journal", "reports/p13_02_journal.png"),
        ("discipline", "reports/p13_03_discipline.png"),
        ("coaching", "reports/p13_04_coaching.png"),
        ("briefing", "reports/p13_05_briefing.png"),
    ]

    for page_param, out_file in pages:
        out_path = Path(out_file).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        url_target = f"{url_base}/?page={page_param}"
        logger.info("Capture de %s -> %s", url_target, out_path.name)
        # Appel headless Edge
        cmd_edge = [
            str(edge_exe),
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--screenshot={str(out_path)}",
            "--window-size=1600,1200",
            url_target,
        ]
        time.sleep(2)
        res_edge = subprocess.run(cmd_edge, capture_output=True, timeout=20)
        assert out_path.exists(), f"Capture échouée pour {page_param} : {res_edge.stderr}"
        size_kb = out_path.stat().st_size / 1024
        logger.info("Capture générée : %s (taille : %.1f KB)", out_path.name, size_kb)

    logger.info("Arrêt du serveur Streamlit...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    logger.info("Toutes les captures d'écran ont été générées avec succès.")


if __name__ == "__main__":
    run_parcours()
    capture_pages()
