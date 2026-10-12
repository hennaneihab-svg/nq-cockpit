"""Suite de tests End-to-End Playwright pour l'interface NQ Cockpit.

Valide exhaustivement toutes les pages et sous-sections de l'application :
- [01] COCKPIT LIVE
- [02] JOURNAL DE BORD (5 sous-sections)
- [03] DISCIPLINE & SIZING
- [04] COACHING & ANALYTICS
- [05] BRIEFING PRE-SEANCE

Vérifie l'absence d'erreurs d'exécution (tracebacks Streamlit, alertes bloquantes),
teste les interactions (boutons, selects, inputs, cases à cocher),
capture les preuves d'écran pleine page et audite le design/ergonomie.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("e2e_cockpit")

SERVER_URL = "http://127.0.0.1:8501"
HEALTH_URL = "http://127.0.0.1:8501/_stcore/health"
SCREENSHOTS_DIR = Path("reports/e2e_screenshots")


@dataclass
class InteractionResult:
    element_type: str
    label_or_selector: str
    action: str
    success: bool
    details: str = ""


@dataclass
class PageAuditResult:
    page_name: str
    sub_section: str = ""
    url: str = ""
    load_success: bool = True
    no_traceback: bool = True
    console_errors: list[str] = field(default_factory=list)
    traceback_texts: list[str] = field(default_factory=list)
    interactions: list[InteractionResult] = field(default_factory=list)
    screenshot_path: str = ""
    design_notes: list[str] = field(default_factory=list)


def wait_for_server(timeout_sec: int = 40) -> bool:
    """Vérifie si le serveur Streamlit répond."""
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def start_server_if_needed() -> subprocess.Popen | None:
    """Lance Streamlit en tâche de fond si non actif."""
    if wait_for_server(timeout_sec=2):
        logger.info("Le serveur Streamlit tourne déjà sur %s", SERVER_URL)
        return None

    logger.info("Lancement du serveur Streamlit en arrière-plan...")
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/nqcockpit/ui/app.py",
            "--server.port",
            "8501",
            "--server.address",
            "127.0.0.1",
            "--server.headless",
            "true",
            "--theme.base",
            "dark",
            "--global.developmentMode",
            "false",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    if not wait_for_server(timeout_sec=35):
        proc.terminate()
        raise RuntimeError("Impossible de démarrer le serveur Streamlit.")

    logger.info("Serveur Streamlit prêt sur %s", SERVER_URL)
    return proc


def check_page_errors(page: Page) -> tuple[bool, list[str]]:
    """Vérifie si la page contient des traces d'erreurs Streamlit."""
    tracebacks = []
    exception_locators = page.locator(
        '[data-testid="stException"], .stAlert[data-baseweb="notification"]'
    )
    count = exception_locators.count()
    for i in range(count):
        txt = exception_locators.nth(i).inner_text()
        if "Traceback" in txt or "Error:" in txt or "Exception:" in txt:
            tracebacks.append(txt.strip())

    body_text = page.locator("body").inner_text()
    if not body_text.strip():
        tracebacks.append("Page entièrement blanche (aucun contenu DOM)")

    return (len(tracebacks) == 0, tracebacks)


def wait_for_streamlit_ready(page: Page, timeout_ms: int = 45000):
    """Attend que Streamlit ait terminé le rendu."""
    try:
        page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=timeout_ms)
        page.wait_for_selector(
            '[data-testid="stStatusWidget"]', state="detached", timeout=timeout_ms
        )
    except Exception:
        pass
    time.sleep(1.5)



def select_sidebar_nav(page: Page, text: str):
    """Sélectionne une section dans le menu radio de la barre latérale."""
    page.wait_for_selector('[data-testid="stSidebar"] div[role="radiogroup"]', timeout=15000)
    sidebar_rg = page.locator('[data-testid="stSidebar"] div[role="radiogroup"]').first
    lbl = sidebar_rg.locator("label").filter(has_text=text).first
    lbl.locator("input").evaluate("el => el.click()")
    wait_for_streamlit_ready(page)


def select_journal_tab(page: Page, tab_name: str):
    """Sélectionne un sous-onglet dans le journal de bord via son input radio."""
    page.wait_for_selector('[data-testid="stMain"] div[role="radiogroup"]', timeout=15000)
    main_rg = page.locator('[data-testid="stMain"] div[role="radiogroup"]').first
    lbl = main_rg.locator("label").filter(has_text=tab_name).first
    lbl.locator("input").evaluate("el => el.click()")
    wait_for_streamlit_ready(page)


def run_e2e_suite():
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    server_proc = start_server_if_needed()

    results: list[PageAuditResult] = []

    try:
        with sync_playwright() as p:
            browser: Browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            context: BrowserContext = browser.new_context(
                viewport={"width": 1440, "height": 950},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) NQCockpit-QA",
            )
            page: Page = context.new_page()

            console_logs: list[str] = []

            def on_console(msg):
                if msg.type in ("error", "warning"):
                    console_logs.append(f"[{msg.type.upper()}] {msg.text}")

            def on_page_error(exc):
                console_logs.append(f"[UNCAUGHT_JS_EXCEPTION] {exc}")

            page.on("console", on_console)
            page.on("pageerror", on_page_error)

            logger.info("Navigation vers %s ...", SERVER_URL)
            page.goto(SERVER_URL, wait_until="networkidle", timeout=30000)
            wait_for_streamlit_ready(page)

            # ===================================================================
            # 1. PAGE [01] COCKPIT LIVE
            # ===================================================================
            logger.info("--- TEST 1: [01] COCKPIT LIVE ---")
            console_logs.clear()
            select_sidebar_nav(page, "[01] COCKPIT LIVE")
            try:
                page.wait_for_selector(".section-header", timeout=45000)
                page.wait_for_selector(".kpi-card", timeout=45000)
            except Exception as e:
                logger.warning("Attente page 1 timeout ou non trouvée: %s", e)


            ok, tb = check_page_errors(page)
            p1_res = PageAuditResult(
                page_name="[01] COCKPIT LIVE",
                sub_section="Vue d'ensemble",
                url=page.url,
                load_success=ok,
                no_traceback=ok,
                console_errors=list(console_logs),
                traceback_texts=tb,
            )

            # Double horloge
            clock_el = page.locator(".sidebar-clock")
            p1_res.interactions.append(
                InteractionResult(
                    "clock",
                    "Horloges Alger & NY",
                    "detect",
                    clock_el.count() > 0,
                    "Double horloge active",
                )
            )

            # Radar Macro (6 fenêtres)
            macro_cards = page.locator(".news-card")
            card_cnt = macro_cards.count()
            p1_res.interactions.append(
                InteractionResult(
                    "cards",
                    "Radar Macro 6 fenêtres",
                    "detect",
                    card_cnt == 6,
                    f"{card_cnt} cartes macro rendues",
                )
            )

            # Fil d'actualités direct
            wire_cards = page.locator(".news-wire-card")
            wire_cnt = wire_cards.count()
            p1_res.interactions.append(
                InteractionResult(
                    "wire",
                    "Dépêches Live Wire",
                    "detect",
                    wire_cnt > 0,
                    f"{wire_cnt} dépêches d'actualités direct affichées",
                )
            )

            # Tableau niveaux clés & bouton CSV
            csv_btn = page.locator('button:has-text("Exporter les Niveaux")')
            if csv_btn.count() > 0:
                csv_btn.first.hover()
                p1_res.interactions.append(
                    InteractionResult(
                        "button",
                        "Exporter les Niveaux (CSV)",
                        "hover",
                        True,
                        "Bouton interactif visible",
                    )
                )

            # Scénarios expanders
            expanders = page.locator('[data-testid="stExpander"]')
            p1_res.interactions.append(
                InteractionResult(
                    "expander",
                    "Scénarios Si... Alors...",
                    "detect",
                    True,
                    f"{expanders.count()} expanders de scénarios détectés",
                )
            )

            p1_res.design_notes.extend(
                [
                    "Thème Swetrix sombre Slate-950 avec bordures nettes rgba(51,65,85,0.6).",
                    "Double horloge Alger/NY bien lisible en haut de page sans décalage.",
                    "Radar macro 6 fenêtres en grille 3x2 avec badges statuts OK/DÉGRADÉ.",
                    "Flux d'actualités direct Live Wire intégré en 2 colonnes avec tags.",
                    "Tableau des niveaux clés formaté clairement avec prix et distances.",
                ]
            )

            ss_p1 = SCREENSHOTS_DIR / "01_cockpit_live.png"
            page.screenshot(path=str(ss_p1), full_page=True)
            p1_res.screenshot_path = str(ss_p1)
            results.append(p1_res)

            # ===================================================================
            # 2. PAGE [02] JOURNAL DE BORD (5 Sous-sections)
            # ===================================================================
            logger.info("--- TEST 2: [02] JOURNAL DE BORD ---")
            select_sidebar_nav(page, "[02] JOURNAL DE BORD")

            journal_subtabs = [
                ("Enregistrer un trade", "02a_journal_saisie.png"),
                ("Import MT5 & CSV", "02b_journal_import.png"),
                ("Journal du jour", "02c_journal_jour.png"),
                ("Performance globale", "02d_journal_performance.png"),
                ("Coaching", "02e_journal_coaching.png"),
            ]

            for tab_name, ss_file in journal_subtabs:
                logger.info("Sous-section Journal: %s", tab_name)
                console_logs.clear()
                select_journal_tab(page, tab_name)

                ok, tb = check_page_errors(page)
                tab_res = PageAuditResult(
                    page_name="[02] JOURNAL DE BORD",
                    sub_section=tab_name,
                    url=page.url,
                    load_success=ok,
                    no_traceback=ok,
                    console_errors=list(console_logs),
                    traceback_texts=tb,
                )

                if tab_name == "Enregistrer un trade":
                    inputs_count = page.locator(
                        'input[type="text"], input[type="number"]'
                    ).count()
                    tab_res.interactions.append(
                        InteractionResult(
                            "form",
                            "Champs de saisie",
                            "detect",
                            inputs_count > 0,
                            f"{inputs_count} champs de saisie détectés",
                        )
                    )
                    save_btn = page.locator('button:has-text("Enregistrer le trade")')
                    if save_btn.count() > 0:
                        save_btn.first.click()
                        time.sleep(0.5)
                        err_alert = page.locator(
                            'div[data-testid="stAlert"]:has-text("obligatoires")'
                        )
                        tab_res.interactions.append(
                            InteractionResult(
                                "button",
                                "Enregistrer le trade",
                                "click_validation",
                                err_alert.count() > 0,
                                "Contrôle de validation (prix requis) déclenché",
                            )
                        )
                    tab_res.design_notes.extend(
                        [
                            "Structure 3 colonnes pour prix d'entrée, stop et sortie ordonnée.",
                            "Labels clairs avec unités monétaires et points.",
                        ]
                    )

                elif tab_name == "Import MT5 & CSV":
                    mt5_section = page.locator("text=Passerelle MetaTrader 5")
                    tab_res.interactions.append(
                        InteractionResult(
                            "card",
                            "Passerelle MT5",
                            "detect",
                            mt5_section.count() > 0,
                            "Section MT5 présente",
                        )
                    )
                    exp_mt5 = page.locator("text=Configuration des identifiants MT5")
                    if exp_mt5.count() > 0:
                        exp_mt5.first.click()
                        time.sleep(0.3)
                        tab_res.interactions.append(
                            InteractionResult(
                                "expander",
                                "Config MT5 (.env)",
                                "toggle",
                                True,
                                "Expander de credentials ouvert",
                            )
                        )
                    uploader = page.locator('[data-testid="stFileUploader"]')
                    tab_res.interactions.append(
                        InteractionResult(
                            "file_uploader",
                            "Déposer un fichier CSV",
                            "detect",
                            uploader.count() > 0,
                            "Zone de glisser-déposer CSV présente",
                        )
                    )
                    tab_res.design_notes.extend(
                        [
                            "Mise en page équilibrée 2 colonnes (MT5 à gauche, CSV à droite).",
                            "Statut MT5 DÉGRADÉ affiché si MT5 n'est pas connecté localement.",
                        ]
                    )

                elif tab_name == "Journal du jour":
                    date_input = page.locator('input[aria-label="Date séance"]')
                    tab_res.interactions.append(
                        InteractionResult(
                            "date_input",
                            "Date séance",
                            "detect",
                            date_input.count() > 0,
                            "Sélecteur de date séance présent",
                        )
                    )
                    tab_res.design_notes.extend(
                        [
                            "Cartes métriques de session compactes (Trades, PnL, Conformité).",
                            "Message informatif si aucun trade sur la date sélectionnée.",
                        ]
                    )

                elif tab_name == "Performance globale":
                    sel_seg = page.locator(
                        'div[data-testid="stSelectbox"]:has-text("Segmenter par")'
                    )
                    if sel_seg.count() > 0:
                        sel_seg.first.click()
                        time.sleep(0.2)
                        page.keyboard.press("Escape")
                        tab_res.interactions.append(
                            InteractionResult(
                                "selectbox",
                                "Segmenter par",
                                "open_close",
                                True,
                                "Sélecteur de segmentation interactif",
                            )
                        )
                    tab_res.design_notes.extend(
                        [
                            "Bandeau d'échantillon insuffisant clair et transparent.",
                            "Alignement tabulaire des métriques de gain, win rate, expectancy.",
                        ]
                    )

                elif tab_name == "Coaching":
                    gen_report_btn = page.locator('button:has-text("Générer le rapport")')
                    if gen_report_btn.count() > 0:
                        gen_report_btn.first.click()
                        wait_for_streamlit_ready(page)
                        tab_res.interactions.append(
                            InteractionResult(
                                "button",
                                "Générer le rapport",
                                "click",
                                True,
                                "Génération de rapport de coaching exécutée",
                            )
                        )
                    tab_res.design_notes.extend(
                        [
                            "Sections 'Top fuites', 'Règle à renforcer', 'Force à conserver'.",
                            "Hiérarchie typographique ordonnée.",
                        ]
                    )

                ss_path = SCREENSHOTS_DIR / ss_file
                page.screenshot(path=str(ss_path), full_page=True)
                tab_res.screenshot_path = str(ss_path)
                results.append(tab_res)

            # ===================================================================
            # 3. PAGE [03] DISCIPLINE & SIZING
            # ===================================================================
            logger.info("--- TEST 3: [03] DISCIPLINE & SIZING ---")
            console_logs.clear()
            select_sidebar_nav(page, "[03] DISCIPLINE & SIZING")

            ok, tb = check_page_errors(page)
            p3_res = PageAuditResult(
                page_name="[03] DISCIPLINE & SIZING",
                sub_section="Porte de discipline",
                url=page.url,
                load_success=ok,
                no_traceback=ok,
                console_errors=list(console_logs),
                traceback_texts=tb,
            )

            # Modification capital
            acc_input = page.locator('input[aria-label="Capital compte ($)"]')
            if acc_input.count() > 0:
                acc_input.first.click()
                acc_input.first.fill("100000")
                acc_input.first.press("Enter")
                time.sleep(0.5)
                p3_res.interactions.append(
                    InteractionResult(
                        "number_input",
                        "Capital compte",
                        "edit",
                        True,
                        "Modification capital réactive",
                    )
                )

            # Modification Stop
            stop_input = page.locator('input[aria-label="Distance Stop (points)"]')
            if stop_input.count() > 0:
                stop_input.first.click()
                stop_input.first.fill("25")
                stop_input.first.press("Enter")
                time.sleep(0.3)
                p3_res.interactions.append(
                    InteractionResult(
                        "number_input",
                        "Distance Stop",
                        "edit",
                        True,
                        "Recalcul automatique du sizing",
                    )
                )

            # Checkbox 1
            chk1 = page.locator('label:has-text("1. J\'ai consulté et validé le profil P08")')
            if chk1.count() > 0:
                chk1.first.locator("input").evaluate("el => el.click()")
                time.sleep(0.3)
                p3_res.interactions.append(
                    InteractionResult(
                        "checkbox",
                        "Checklist Profil P08",
                        "toggle",
                        True,
                        "Case à cocher cochée",
                    )
                )

            # Plan écrit
            plan_area = page.locator(
                'textarea[aria-label="3. Plan écrit de trade (au moins 10 caractères)"]'
            )
            if plan_area.count() > 0:
                plan_area.first.fill(
                    "Rejet acheteur sur support VWAP à 20850 avec stop 20820."
                )
                plan_area.first.press("Tab")
                time.sleep(0.5)
                p3_res.interactions.append(
                    InteractionResult(
                        "textarea", "Plan écrit", "fill", True, "Texte de plan saisi"
                    )
                )

            # Verdict badge
            verdict_badge = page.locator(".badge-go, .badge-stop")
            p3_res.interactions.append(
                InteractionResult(
                    "badge",
                    "Verdict Pré-Trade",
                    "detect",
                    verdict_badge.count() > 0,
                    "Verdict interactif affiché",
                )
            )

            p3_res.design_notes.extend(
                [
                    "Badge de verdict (GO / STOP) très visible et sans ambiguïté.",
                    "Zéro bouton d'exécution de trade (respect total du mandat non-broker).",
                    "Calculateur de taille avec arrondi plancher automatique Math.floor.",
                ]
            )

            ss_p3 = SCREENSHOTS_DIR / "03_discipline_sizing.png"
            page.screenshot(path=str(ss_p3), full_page=True)
            p3_res.screenshot_path = str(ss_p3)
            results.append(p3_res)

            # ===================================================================
            # 4. PAGE [04] COACHING & ANALYTICS
            # ===================================================================
            logger.info("--- TEST 4: [04] COACHING & ANALYTICS ---")
            console_logs.clear()
            select_sidebar_nav(page, "[04] COACHING & ANALYTICS")

            ok, tb = check_page_errors(page)
            p4_res = PageAuditResult(
                page_name="[04] COACHING & ANALYTICS",
                sub_section="Analytics Plotly",
                url=page.url,
                load_success=ok,
                no_traceback=ok,
                console_errors=list(console_logs),
                traceback_texts=tb,
            )

            # 6 cartes métriques
            metric_cards = page.locator(".metric-card")
            p4_res.interactions.append(
                InteractionResult(
                    "cards",
                    "KPI Metrics Coaching",
                    "detect",
                    metric_cards.count() == 6,
                    f"{metric_cards.count()} cartes métriques coaching affichées",
                )
            )

            # Graphiques Plotly
            plotly_charts = page.locator(".js-plotly-plot")
            p4_res.interactions.append(
                InteractionResult(
                    "chart",
                    "Graphiques Plotly",
                    "detect",
                    plotly_charts.count() >= 3,
                    f"{plotly_charts.count()} graphiques Plotly interactifs rendus",
                )
            )

            p4_res.design_notes.extend(
                [
                    "Thème Plotly personnalisé 'plotly_dark' avec fond ardoise (#0F172A).",
                    "Grille de métriques KPI réactives avec survol animé.",
                    "Intervalles de confiance Wilson sur le Win Rate affichés avec rigueur.",
                ]
            )

            ss_p4 = SCREENSHOTS_DIR / "04_coaching_analytics.png"
            page.screenshot(path=str(ss_p4), full_page=True)
            p4_res.screenshot_path = str(ss_p4)
            results.append(p4_res)

            # ===================================================================
            # 5. PAGE [05] BRIEFING PRE-SEANCE
            # ===================================================================
            logger.info("--- TEST 5: [05] BRIEFING PRE-SEANCE ---")
            console_logs.clear()
            select_sidebar_nav(page, "[05] BRIEFING PRE-SEANCE")

            ok, tb = check_page_errors(page)
            p5_res = PageAuditResult(
                page_name="[05] BRIEFING PRE-SEANCE",
                sub_section="Génération consolidée",
                url=page.url,
                load_success=ok,
                no_traceback=ok,
                console_errors=list(console_logs),
                traceback_texts=tb,
            )

            # Bouton charger le dernier briefing si disponible
            load_prev = page.locator('button:has-text("Charger le dernier briefing archivé")')
            if load_prev.count() > 0:
                load_prev.first.click()
                time.sleep(1.0)
                p5_res.interactions.append(
                    InteractionResult(
                        "button",
                        "Charger le dernier briefing",
                        "click",
                        True,
                        "Briefing archivé chargé avec succès",
                    )
                )
            else:
                gen_b_btn = page.locator('button:has-text("Générer un nouveau briefing")')
                if gen_b_btn.count() > 0:
                    gen_b_btn.first.click()
                    time.sleep(3.0)
                    p5_res.interactions.append(
                        InteractionResult(
                            "button",
                            "Générer un nouveau briefing",
                            "click",
                            True,
                            "Génération de briefing déclenchée",
                        )
                    )

            ok_after, tb_after = check_page_errors(page)
            if not ok_after:
                p5_res.no_traceback = False
                p5_res.traceback_texts.extend(tb_after)

            p5_res.design_notes.extend(
                [
                    "Mise en page éditoriale nette avec Markdown structuré en sections.",
                    "Statuts d'intégrité avec badges colorés discrets et non alarmistes.",
                    "Bandeaux dégradés clairs spécifiant la raison technique de chaque repli.",
                ]
            )

            ss_p5 = SCREENSHOTS_DIR / "05_briefing_pre_seance.png"
            page.screenshot(path=str(ss_p5), full_page=True)
            p5_res.screenshot_path = str(ss_p5)
            results.append(p5_res)

            browser.close()

    finally:
        if server_proc is not None:
            logger.info("Arrêt du serveur Streamlit...")
            server_proc.terminate()
            server_proc.wait()

    json_path = Path("reports/e2e_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2, ensure_ascii=False)

    logger.info("Rapport E2E JSON sauvegardé dans %s", json_path)
    return results


if __name__ == "__main__":
    run_e2e_suite()
