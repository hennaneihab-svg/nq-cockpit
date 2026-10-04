"""Command Line Interface for NQ Cockpit."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence


def _get_threshold_provenance(param_path: str, fallback_val: Any) -> tuple[Any, str]:
    """Résout la valeur et la provenance d'un seuil (config vs repli)."""
    try:
        from nqcockpit.config import load_config

        cfg = load_config()
        obj: Any = cfg
        for part in param_path.split("."):
            obj = getattr(obj, part)
        return obj, f"config: {param_path}"
    except Exception:
        return fallback_val, f"fallback: {fallback_val}"


def create_parser() -> argparse.ArgumentParser:
    """Creates the argument parser with all required subcommands."""
    parser = argparse.ArgumentParser(
        prog="nqcockpit",
        description="NQ Cockpit — Outil local de préparation, discipline et mesure du trading NQ",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Chemin vers le fichier config.yaml alternatif",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Active la journalisation détaillée (DEBUG)",
    )

    subparsers = parser.add_subparsers(
        title="sous-commandes",
        dest="subcommand",
        help="Action à exécuter",
    )

    # 1. run
    parser_run = subparsers.add_parser(
        "run",
        help="Démarre le cockpit NQ et son planificateur de tâches",
    )
    parser_run.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port d'écoute pour l'interface Streamlit (défaut : 8501)",
    )
    parser_run.add_argument(
        "--no-ui",
        action="store_true",
        help="Démarre uniquement le planificateur sans ouvrir l'interface Streamlit",
    )
    parser_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Exécute un cycle complet sans enregistrement en base",
    )

    # 2. check-sources
    subparsers.add_parser(
        "check-sources",
        help="Vérifie la connectivité et la santé de toutes les sources gratuites",
    )

    # 3. snapshot
    subparsers.add_parser(
        "snapshot",
        help="Effectue un snapshot immédiat de la chaîne d'options NDX et du cours NQ",
    )

    # 4. brief
    subparsers.add_parser(
        "brief",
        help="Génère le briefing de marché du jour à partir des données calculées",
    )

    # 5. ui
    parser_ui = subparsers.add_parser(
        "ui",
        help="Lance l'interface utilisateur Streamlit",
    )
    parser_ui.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port d'écoute Streamlit (défaut : 8501)",
    )

    # 6. data
    parser_data = subparsers.add_parser(
        "data",
        help="Commandes relatives à la couche de données et persistance SQLite",
    )
    data_subparsers = parser_data.add_subparsers(
        title="actions de données",
        dest="data_action",
        help="Action spécifique sur les données",
    )
    data_subparsers.add_parser("migrate", help="Applique les migrations sur data/nqcockpit.db")
    data_subparsers.add_parser("roll", help="Affiche les informations de roll du contrat NQ")
    data_subparsers.add_parser(
        "archive", help="Télécharge et archive les barres intraday dans SQLite"
    )
    data_subparsers.add_parser(
        "status", help="Affiche l'état et les statistiques de la base de données"
    )
    data_subparsers.add_parser(
        "fred", help="Récupère les séries FRED DGS2 et DGS10"
    )

    # 7. events
    parser_events = subparsers.add_parser(
        "events",
        help="Affiche le radar d'événements économiques et le risque (GREEN/AMBER/RED)",
    )
    parser_events.add_argument(
        "--horizon",
        type=int,
        default=None,
        help="Horizon en jours (défaut : config.events.horizon_days)",
    )

    # 8. playbook
    parser_playbook = subparsers.add_parser(
        "playbook",
        help="Fiches d'anticipation événements, diff FOMC, fiche minutes (P06)",
    )
    pb_subparsers = parser_playbook.add_subparsers(
        title="actions playbook",
        dest="playbook_action",
        help="Action spécifique",
    )

    # playbook card
    pb_card = pb_subparsers.add_parser(
        "card",
        help="Génère la fiche d'anticipation pour le prochain événement Tier 1",
    )
    pb_card.add_argument(
        "--event",
        type=str,
        default=None,
        help="Nom de l'événement (ex: 'NFP', 'FOMC Minutes'). Défaut : prochain Tier 1.",
    )
    pb_card.add_argument(
        "--json",
        action="store_true",
        help="Sortie en JSON (défaut : texte console)",
    )

    # playbook fed-diff
    pb_diff = pb_subparsers.add_parser(
        "fed-diff",
        help="Diff mot à mot entre les deux derniers communiqués FOMC + lecture de ton",
    )
    pb_diff.add_argument(
        "--prev-url",
        type=str,
        default="",
        help="URL du communiqué précédent (défaut : auto-détecté)",
    )
    pb_diff.add_argument(
        "--curr-url",
        type=str,
        default="",
        help="URL du communiqué courant (défaut : auto-détecté)",
    )

    # playbook minutes-watch
    pb_subparsers.add_parser(
        "minutes-watch",
        help="Fiche 'à surveiller' avant la publication des minutes FOMC",
    )

    # 9. macro
    parser_macro = subparsers.add_parser(
        "macro",
        help="Contexte macroéconomique et cross-asset (US10Y, 2Y, DXY, VIX/VXN, overnight, COT)",
    )
    parser_macro.add_argument(
        "--json",
        action="store_true",
        help="Sortie en JSON (défaut : console structurée)",
    )

    # 10. amplitude
    parser_amplitude = subparsers.add_parser(
        "amplitude",
        help="Prévisions d'amplitude, calibration 1-sigma et probabilités de séance (P07)",
    )
    parser_amplitude.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date cible (défaut : séance courante YYYY-MM-DD)",
    )
    parser_amplitude.add_argument(
        "--report",
        action="store_true",
        help="Génère ou met à jour le rapport reports/calibration.md",
    )
    parser_amplitude.add_argument(
        "--json",
        action="store_true",
        help="Sortie en JSON (défaut : console structurée)",
    )

    # 11. profile (P08)
    parser_profile = subparsers.add_parser(
        "profile",
        help="Profil de séance, carte de scénarios et drapeaux NO-TRADE (P08)",
    )
    parser_profile.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date cible (défaut : séance courante YYYY-MM-DD)",
    )
    parser_profile.add_argument(
        "--json",
        action="store_true",
        help="Sortie brute en JSON",
    )
    parser_profile.add_argument(
        "--export-csv",
        type=str,
        default=None,
        help="Chemin de fichier pour l'export CSV des niveaux clés",
    )

    # 12. journal (P09)
    parser_journal = subparsers.add_parser(
        "journal",
        help="Journal de bord, discipline et métriques de performance (P09)",
    )
    j_sub = parser_journal.add_subparsers(
        title="actions journal",
        dest="journal_action",
        help="Action spécifique",
    )
    j_sub.add_parser("stats", help="Affiche les statistiques de performance globales")
    j_daily = j_sub.add_parser("daily", help="Statistiques et violations d'une séance")
    j_daily.add_argument(
        "--date", type=str, default=None,
        help="Date YYYY-MM-DD (défaut : aujourd'hui NY)"
    )
    j_coaching = j_sub.add_parser("coaching", help="Génère un rapport de coaching")
    j_coaching.add_argument(
        "--period", type=str, default="hebdo",
        choices=["hebdo", "mensuel"], help="Période"
    )
    j_coaching.add_argument(
        "--label", type=str, default="",
        help="Label de la période (ex. S39-2026)"
    )
    j_ui = j_sub.add_parser("ui", help="Lance l'interface Streamlit du journal")
    j_ui.add_argument(
        "--port", type=int, default=8502,
        help="Port Streamlit (défaut : 8502)"
    )
    j_coaching_ui = j_sub.add_parser(
        "coaching-ui",
        help="Lance l'interface Streamlit dédiée d'analytics et coaching",
    )
    j_coaching_ui.add_argument(
        "--port", type=int, default=8504,
        help="Port Streamlit (défaut : 8504)"
    )
    j_import = j_sub.add_parser(
        "import-csv", help="Importe des trades depuis un fichier CSV"
    )
    j_import.add_argument(
        "csv_path", type=str, help="Chemin du fichier CSV à importer"
    )
    j_attach = j_sub.add_parser(
        "attach-screenshot",
        help="Attache une capture d'écran locale à un trade existant",
    )
    j_attach.add_argument("trade_id", type=str, help="ID unique du trade")
    j_attach.add_argument("image_path", type=str, help="Chemin du fichier image")
    j_backup = j_sub.add_parser(
        "backup", help="Sauvegarde quotidienne transactionnelle de la base SQLite"
    )
    j_backup.add_argument(
        "--dir", type=str, default=None,
        help="Dossier de destination (défaut : config.data.backup_dir)"
    )
    j_backup.add_argument(
        "--retention-days", type=int, default=None,
        help="Nombre de jours de rétention (défaut : config.data.backup_retention_days)"
    )
    j_report = j_sub.add_parser(
        "report",
        help="Génère un rapport de synthèse hebdomadaire ou mensuel en Markdown",
    )
    j_report.add_argument(
        "--period",
        type=str,
        required=True,
        choices=["week", "month"],
        help="Période : 'week' (hebdomadaire) ou 'month' (mensuel)",
    )
    j_report.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date de référence YYYY-MM-DD (défaut : date du jour en America/New_York)",
    )
    j_report.add_argument(
        "--output-dir",
        type=str,
        default="reports/journal",
        help="Dossier de destination (défaut : reports/journal)",
    )

    # 13. discipline (P09 réel)
    parser_disc = subparsers.add_parser(
        "discipline",
        help="Porte de discipline live et gestionnaire de risque (P09 réel)",
    )
    d_sub = parser_disc.add_subparsers(
        title="actions discipline",
        dest="discipline_action",
        help="Action spécifique",
    )
    d_sub.add_parser("status", help="État vivant de la séance (verrous, cooldown)")

    d_check = d_sub.add_parser(
        "check", help="Checklist pré-trade interactive (verdict GO / STOP)"
    )
    d_check.add_argument("--plan", type=str, default="", help="Plan de trade écrit")
    d_check.add_argument(
        "--p08-reviewed", action="store_true", help="Confirmer consultation P08"
    )
    d_check.add_argument(
        "--account", type=float, default=None, help="Capital compte ($)"
    )
    d_check.add_argument(
        "--risk-pct", type=float, default=None, help="Risque (pourcentage)"
    )
    d_check.add_argument(
        "--stop-pts", type=float, default=30.0, help="Stop loss (points)"
    )
    d_check.add_argument(
        "--instrument", type=str, default="MNQ", choices=["NQ", "MNQ"],
        help="Instrument",
    )

    d_sizing = d_sub.add_parser(
        "sizing", help="Calculateur de dimensionnement de position"
    )
    d_sizing.add_argument(
        "--account", type=float, default=50000.0, help="Capital compte ($)"
    )
    d_sizing.add_argument(
        "--risk-pct", type=float, default=0.5, help="Risque (pourcentage)"
    )
    d_sizing.add_argument(
        "--stop-pts", type=float, default=30.0, help="Stop loss (points)"
    )
    d_sizing.add_argument(
        "--instrument", type=str, default="MNQ", choices=["NQ", "MNQ"],
        help="Instrument",
    )
    d_sizing.add_argument(
        "--prop-max-loss", type=float, default=None,
        help="Perte max journalière prop ($)",
    )
    d_sizing.add_argument(
        "--prop-trailing-dd", type=float, default=None,
        help="Drawdown glissant prop ($)",
    )

    d_ui = d_sub.add_parser("ui", help="Lance l'interface Streamlit de discipline")
    d_ui.add_argument(
        "--port", type=int, default=8503, help="Port Streamlit (défaut : 8503)"
    )

    # 14. briefing (P12)
    parser_briefing = subparsers.add_parser(
        "briefing",
        help="Génération du briefing pré-séance et diffusion optionnelle (P12)",
    )
    b_sub = parser_briefing.add_subparsers(
        title="actions briefing",
        dest="briefing_action",
        help="Action spécifique",
    )
    b_gen = b_sub.add_parser(
        "generate",
        help="Agrège les données des modules P02-P08 et génère le briefing",
    )
    b_gen.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule l'envoi Telegram sans appel réseau",
    )
    b_gen.add_argument(
        "--no-gemini",
        action="store_true",
        help="Désactive l'agent rédactionnel Gemini (fallback Markdown)",
    )
    b_gen.add_argument(
        "--no-telegram",
        action="store_true",
        help="Désactive l'envoi Telegram",
    )
    b_gen.add_argument(
        "--output-dir",
        type=str,
        default="reports/briefings",
        help="Dossier de destination (défaut : reports/briefings)",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "run":
        return _handle_run(args)
    elif args.subcommand == "check-sources":
        from nqcockpit.sources.health import run_all_checks

        print("[nqcockpit] Commande 'check-sources' invoquée (santé des sources)...")
        report = run_all_checks()
        print("\n" + report.render_console_table() + "\n")
        report_path = report.save_json("reports/source_check.json")
        print(f"[nqcockpit] Rapport complet enregistré dans {report_path}")
        return 0
    elif args.subcommand == "briefing":
        return _handle_briefing(args)
    elif args.subcommand == "snapshot":

        from nqcockpit.data.cboe import fetch_cboe_options_chain
        from nqcockpit.data.db import get_bars, get_db_connection, insert_bars
        from nqcockpit.data.fetcher import DataFetcher
        from nqcockpit.data.models import DataStatus
        from nqcockpit.levels.engine import LevelsEngine

        print("[nqcockpit] Commande 'snapshot' invoquée (niveaux gamma)...")

        # 1. CBOE : Rechargement forcé en direct avec capture des métadonnées (Tâche 2)
        chain = fetch_cboe_options_chain(force_reload=True)

        # 2. SPOT NQ & NDX : Toujours tenter le flux direct en premier (Tâche 1)
        # Évite le court-circuit par d'anciennes barres SQLite archivées la veille
        fetcher = DataFetcher()
        conn = get_db_connection()
        nq_bars = []
        ndx_bars = []

        from datetime import datetime as _dt
        from datetime import timezone as _tz
        now_req_utc = _dt.now(_tz.utc)

        try:
            live_nq = fetcher.fetch_yahoo_bars("NQ=F", interval="1m", period="1d")
            if live_nq.bars:
                nq_bars = live_nq.bars
                insert_bars(conn, nq_bars, "NQ=F", "1m", "yahoo", now_req_utc)
        except Exception as e:
            print(f"[!] Avertissement réseau NQ=F ({e}) : repli sur SQLite local.")

        try:
            live_ndx = fetcher.fetch_yahoo_bars("^NDX", interval="1m", period="1d")
            if live_ndx.bars:
                ndx_bars = live_ndx.bars
                insert_bars(conn, ndx_bars, "^NDX", "1m", "yahoo", now_req_utc)
        except Exception as e:
            print(f"[!] Avertissement réseau ^NDX ({e}) : repli sur SQLite local.")

        # Repli SQLite si la requête réseau n'a pas retourné de barres
        if not nq_bars:
            nq_bars = get_bars(conn, "NQ=F", "1m", limit=100)
        if not ndx_bars:
            ndx_bars = get_bars(conn, "^NDX", "1m", limit=100)
        conn.close()

        engine = LevelsEngine()
        snap = engine.compute_snapshot(chain=chain, nq_bars=nq_bars, ndx_bars=ndx_bars)

        # Affichage tableau console
        from zoneinfo import ZoneInfo as _ZI
        et_tz = _ZI("America/New_York")
        alg_tz = _ZI("Africa/Algiers")
        snap_ny = snap.timestamp_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
        snap_alg = snap.timestamp_utc.astimezone(alg_tz).strftime("%Y-%m-%d %H:%M:%S (Alger)")
        # Fraîcheur détaillée (Tâche 3)
        cboe_chain_age_s = (
            f"{snap.cboe_chain_age_minutes:.1f} min"
            if snap.cboe_chain_age_minutes is not None
            else (
                f"{snap.data_age_minutes:.1f} min"
                if snap.data_age_minutes is not None
                else "inconnu"
            )
        )
        cboe_quote_delay_s = (
            f"{snap.cboe_active_quote_delay_minutes:.1f} min"
            if snap.cboe_active_quote_delay_minutes is not None
            else "inconnu"
        )

        print("\n" + "=" * 70)
        print("  NQ COCKPIT — SNAPSHOT DE NIVEAUX & RÉGIME GAMMA")
        print(f"  Horodatage          : {snap_ny} | {snap_alg}")
        print(
            f"  Âge chaîne CBOE     : {cboe_chain_age_s} | "
            f"Retard cotations : {cboe_quote_delay_s}"
        )
        print(f"  Statut global       : {snap.status.value}")
        print("=" * 70)

        # --- BLOC CBOE (Tâche 2 : RECHARGEMENT PROUVÉ & TÂCHE 3 : RETARD RÉEL) ---
        print("-" * 70)
        print("  SOURCE CBOE (RECHARGEMENT PROUVÉ & FRAÎCHEUR)")
        cboe_req_et = (
            snap.cboe_request_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
            if snap.cboe_request_time_utc
            else "N/A"
        )
        cboe_req_alg = (
            snap.cboe_request_time_utc.astimezone(alg_tz).strftime("%Y-%m-%d %H:%M:%S (Alger)")
            if snap.cboe_request_time_utc
            else "N/A"
        )
        cboe_int_et = (
            snap.cboe_internal_timestamp_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
            if snap.cboe_internal_timestamp_utc
            else "N/A"
        )
        cboe_int_alg = (
            snap.cboe_internal_timestamp_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            if snap.cboe_internal_timestamp_utc
            else "N/A"
        )
        print(f"  Heure requête HTTP   : {cboe_req_et} | {cboe_req_alg}")
        dur_str = f"{snap.cboe_duration_ms:.1f} ms" if snap.cboe_duration_ms is not None else "N/A"
        print(f"  Code HTTP / Durée    : {snap.cboe_http_status or 200} | {dur_str}")
        print(f"  Horodatage chaîne    : {cboe_int_et} | {cboe_int_alg}")
        print(f"  Âge chaîne JSON      : {cboe_chain_age_s}")
        print(f"  Retard cotations act.: {cboe_quote_delay_s} (délai de rediffusion gratuit CBOE)")
        reloaded_str = "OUI (téléchargement direct forcé)" if snap.cboe_reloaded else "NON (cache)"
        print(f"  Chaîne rechargée     : {reloaded_str}")
        if snap.cboe_age_stats:
            excl_zero = snap.cboe_age_stats.get("excluded_zero_quotes", 0)
            n_active = snap.cboe_age_stats.get("count", 0)
            c_med = snap.cboe_age_stats.get("median_delay_minutes")
            c_min = snap.cboe_age_stats.get("min_delay_minutes")
            c_max = snap.cboe_age_stats.get("max_delay_minutes")

            ch_med = snap.cboe_age_stats.get("chain_median_delay_minutes")
            ch_min = snap.cboe_age_stats.get("chain_min_delay_minutes")
            ch_max = snap.cboe_age_stats.get("chain_max_delay_minutes")
            ch_cnt = snap.cboe_age_stats.get("chain_count", 0)

            cboe_med_tol = snap.cboe_age_stats.get("tolerance_median_minutes")
            cboe_med_src = snap.cboe_age_stats.get("tolerance_source")
            if cboe_med_tol is None or cboe_med_src is None:
                cboe_med_tol, cboe_med_src = _get_threshold_provenance(
                    "levels.cboe_max_median_delay_minutes", 30.0
                )

            if ch_med is not None and ch_min is not None and ch_max is not None:
                print(
                    f"  Retard chaîne CBOE   : min {ch_min:.1f} min | "
                    f"médiane {ch_med:.1f} min | max {ch_max:.1f} min "
                    f"(N={ch_cnt} contrats)"
                )
            if c_med is not None and c_min is not None and c_max is not None:
                med_flag = " [OK]" if c_med <= cboe_med_tol else " [DÉGRADÉ]"
                print(
                    f"  Retard options ±3%   : min {c_min:.1f} min | "
                    f"médiane {c_med:.1f} min | max {c_max:.1f} min "
                    f"(N={n_active} cotés)"
                )
                print(
                    f"  Tolérance médiane    : {cboe_med_tol:.1f} min "
                    f"[source: {cboe_med_src}]{med_flag}"
                )
            print(f"  Options actives (±3%): {n_active} contrats (bid>0, ask>0)")
            print(f"  Options exclues      : {excl_zero} contrats sans cotation (bid=0 ou ask=0)")
        print(f"  Statut source CBOE   : {snap.status.value}")

        # --- SPOT NQ & NDX (Tâche 1 : ÂGE RÉEL DU SPOT NQ & TÂCHE 2 : SPOT NDX) ---
        print("-" * 70)
        ndx_ts_live_str = ""
        if snap.live_basis_ndx_time_utc:
            ndx_l_et = snap.live_basis_ndx_time_utc.astimezone(et_tz).strftime(
                "%Y-%m-%d %H:%M:%S ET"
            )
            ndx_l_alg = snap.live_basis_ndx_time_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            ndx_ts_live_str = f" ({ndx_l_et} | {ndx_l_alg})"
        print(f"  Spot NDX             : {snap.spot_ndx:,.2f} pts{ndx_ts_live_str}")
        nq_stale_flag = " [SPOT NQ PÉRIMÉ - DÉGRADÉ]" if snap.spot_nq_is_stale else " [OK]"
        nq_age_s = (
            f"{snap.spot_nq_age_minutes:.1f} min"
            if snap.spot_nq_age_minutes is not None
            else "inconnu"
        )
        spot_max_age_val, spot_max_age_src = _get_threshold_provenance(
            "levels.spot_max_age_minutes", 20.0
        )
        print(
            f"  Spot NQ (observé)    : {snap.spot_nq:,.2f} pts "
            f"(âge réel : {nq_age_s}){nq_stale_flag}"
        )
        print(
            f"    Tolérance âge spot : {spot_max_age_val:.1f} min [source: {spot_max_age_src}]"
        )
        if snap.spot_nq_time_utc:
            nq_bar_et = snap.spot_nq_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
            nq_bar_alg = snap.spot_nq_time_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            print(f"    Horodatage spot NQ : {nq_bar_et} | {nq_bar_alg}")

        # --- BLOC BASE (TÂCHE 2 : SÉANCE PRÉCÉDENTE / PARITÉ / LIVE) ---
        print("-" * 70)
        print("  BLOC BASE (SÉANCE PRÉCÉDENTE / PARITÉ / LIVE)")
        # 1. Base séance précédente
        if snap.basis_status == DataStatus.BLOCKED:
            print(
                f"  1. Base séance précédente : INDISPONIBLE ({snap.basis_label}) "
                f"[{snap.basis_status.value}]"
            )
            if snap.basis_delay_compensation_note:
                print(f"       Origine données      : {snap.basis_delay_compensation_note}")
        elif snap.basis_nq_time_utc and snap.basis_ndx_time_utc:
            b_nq_et = snap.basis_nq_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
            b_nq_alg = snap.basis_nq_time_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            b_ndx_et = snap.basis_ndx_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
            b_ndx_alg = snap.basis_ndx_time_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            print(
                f"  1. Base séance précédente : {snap.basis:+,.2f} pts "
                f"[{snap.basis_status.value}]"
            )
            print(
                f"       Barre NQ close       : {snap.basis_nq_close:,.2f} pts à "
                f"{b_nq_et} | {b_nq_alg}"
            )
            print(
                f"       Spot NDX cotation    : {snap.basis_ndx_spot:,.2f} pts à "
                f"{b_ndx_et} | {b_ndx_alg}"
            )
            if snap.basis_delta_t_minutes is not None:
                align_s = "OK" if snap.basis_is_aligned else "NON ALIGNÉE"
                target_tol_val, target_tol_src = _get_threshold_provenance(
                    "levels.target_tolerance_minutes", 15.0
                )
                print(
                    f"       Delta-t NQ/NDX       : {snap.basis_delta_t_minutes:.2f} min "
                    f"(tol. {snap.basis_tolerance_minutes:.1f} min) [{align_s}]"
                )
                if snap.basis_dist_to_target_minutes is not None:
                    dist_flag = (
                        "OK"
                        if snap.basis_dist_to_target_minutes <= target_tol_val
                        else "DÉGRADÉ"
                    )
                    print(
                        f"       Distance cible 16h   : "
                        f"{snap.basis_dist_to_target_minutes:.1f} min "
                        f"(seuil {target_tol_val:.1f} min [source: {target_tol_src}]) [{dist_flag}]"
                    )
                else:
                    print(
                        f"       Tolérance cible 16h  : "
                        f"{target_tol_val:.1f} min [source: {target_tol_src}]"
                    )
            if snap.basis_delay_compensation_note:
                print(f"       Origine données      : {snap.basis_delay_compensation_note}")
        else:
            print(
                f"  1. Base séance précédente : {snap.basis:+,.2f} pts "
                f"[{snap.basis_status.value}]"
            )

        # 2. Base parité synthétique
        synth_s = (
            f"{snap.synthetic_basis:+,.2f} pts"
            if snap.synthetic_basis is not None
            else "INDISPONIBLE"
        )
        print(f"  2. Base parité synthétique: {synth_s}")

        # 3. Base live
        if snap.live_basis_available and snap.live_basis_value is not None:
            l_nq_et = (
                snap.live_basis_nq_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
                if snap.live_basis_nq_time_utc
                else "N/A"
            )
            l_nq_alg = (
                snap.live_basis_nq_time_utc.astimezone(alg_tz).strftime(
                    "%Y-%m-%d %H:%M:%S (Alger)"
                )
                if snap.live_basis_nq_time_utc
                else "N/A"
            )
            l_ndx_et = (
                snap.live_basis_ndx_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
                if snap.live_basis_ndx_time_utc
                else "N/A"
            )
            l_ndx_alg = (
                snap.live_basis_ndx_time_utc.astimezone(alg_tz).strftime(
                    "%Y-%m-%d %H:%M:%S (Alger)"
                )
                if snap.live_basis_ndx_time_utc
                else "N/A"
            )
            dt_s = (
                f"{snap.live_basis_delta_t_minutes:.2f} min"
                if snap.live_basis_delta_t_minutes is not None
                else "N/A"
            )
            print(
                f"  3. Base live              : {snap.live_basis_value:+,.2f} pts "
                f"[{snap.live_basis_status.value}]"
            )
            print(f"       Barre NQ live        : {l_nq_et} | {l_nq_alg}")
            print(f"       Spot NDX live        : {l_ndx_et} | {l_ndx_alg}")
            print(f"       Delta-t live         : {dt_s} (tol. 1.0 min) [OK]")
        else:
            reason = snap.live_basis_unavailable_reason or "Données insuffisantes"
            print(
                f"  3. Base live              : INDISPONIBLE ({reason}) "
                f"[{snap.live_basis_status.value}]"
            )

        # Comparatif des bases et écarts croisés
        print("  Comparatif des 3 bases :")
        if snap.spread_live_vs_prev_basis is not None:
            print(
                f"    - Écart Live vs Séance précédente   : "
                f"{snap.spread_live_vs_prev_basis:+,.2f} pts"
            )
        else:
            print("    - Écart Live vs Séance précédente   : N/A (base live indisponible)")
        if snap.spread_live_vs_parity_basis is not None:
            print(
                f"    - Écart Live vs Parité              : "
                f"{snap.spread_live_vs_parity_basis:+,.2f} pts"
            )
        else:
            print("    - Écart Live vs Parité              : N/A (live ou parité indisponible)")
        if snap.spread_prev_vs_parity_basis is not None:
            print(
                f"    - Écart Séance précédente vs Parité : "
                f"{snap.spread_prev_vs_parity_basis:+,.2f} pts"
            )
        else:
            print("    - Écart Séance précédente vs Parité : N/A")

        # --- NIVEAUX & MURS UTILES (Tâche 4 : WALLS UTILES ±3%) ---
        print("-" * 70)
        gex_line = (
            f"  Net GEX Total        : {snap.net_gex / 1e6:+,.2f} M$/1% (Modèle, {snap.oi_flag})"
        )
        print(gex_line)
        print(f"  Régime Volatilité    : {snap.regime}")
        print("-" * 70)
        flip_ndx = (
            f"{snap.gamma_flip_ndx:,.2f}" if snap.gamma_flip_ndx else "ABSENT (très stable)"
        )
        flip_nq = f"{snap.gamma_flip_nq:,.2f}" if snap.gamma_flip_nq else "ABSENT"
        print(f"  Gamma Flip (Zéro)    : NDX {flip_ndx} | NQ {flip_nq}")

        # Murs utiles (dans fenêtre ±wall_window_pct, ex. ±3 %)
        win_str = f"±{snap.wall_window_pct * 100:.0f}%"
        cw_u_ndx = f"{snap.call_wall_useful_ndx:,.2f}" if snap.call_wall_useful_ndx else "N/A"
        cw_u_nq = f"{snap.call_wall_useful_nq:,.2f}" if snap.call_wall_useful_nq else "N/A"
        cw_dist = ""
        if (
            snap.call_wall_useful_dist_pts is not None
            and snap.call_wall_useful_dist_pct is not None
        ):
            cw_dist = (
                f" (dist: {snap.call_wall_useful_dist_pts:+,.2f} pts / "
                f"{snap.call_wall_useful_dist_pct:+.2f}%)"
            )
        print(f"  Call Wall utile ({win_str}) : NDX {cw_u_ndx} | NQ {cw_u_nq}{cw_dist}")

        if snap.call_wall_is_outside_window and snap.call_wall_global_ndx:
            cw_g_ndx = f"{snap.call_wall_global_ndx:,.2f}"
            cw_g_nq = f"{snap.call_wall_global_nq:,.2f}" if snap.call_wall_global_nq else "N/A"
            cw_g_dist = ""
            if (
                snap.call_wall_global_dist_pts is not None
                and snap.call_wall_global_dist_pct is not None
            ):
                cw_g_dist = (
                    f" (dist: {snap.call_wall_global_dist_pts:+,.2f} pts / "
                    f"{snap.call_wall_global_dist_pct:+.2f}%)"
                )
            print(
                f"    -> Mur Call global (hors fenêtre) : "
                f"NDX {cw_g_ndx} | NQ {cw_g_nq}{cw_g_dist}"
            )

        pw_u_ndx = f"{snap.put_wall_useful_ndx:,.2f}" if snap.put_wall_useful_ndx else "N/A"
        pw_u_nq = f"{snap.put_wall_useful_nq:,.2f}" if snap.put_wall_useful_nq else "N/A"
        pw_dist = ""
        if (
            snap.put_wall_useful_dist_pts is not None
            and snap.put_wall_useful_dist_pct is not None
        ):
            pw_dist = (
                f" (dist: {snap.put_wall_useful_dist_pts:+,.2f} pts / "
                f"{snap.put_wall_useful_dist_pct:+.2f}%)"
            )
        if snap.put_wall_useful_ndx is None:
            print(f"  Put Wall utile ({win_str})  : INDISPONIBLE [DÉGRADÉ]")
        else:
            print(f"  Put Wall utile ({win_str})  : NDX {pw_u_ndx} | NQ {pw_u_nq}{pw_dist}")

        if snap.put_wall_is_outside_window and snap.put_wall_global_ndx:
            pw_g_ndx = f"{snap.put_wall_global_ndx:,.2f}"
            pw_g_nq = f"{snap.put_wall_global_nq:,.2f}" if snap.put_wall_global_nq else "N/A"
            pw_g_dist = ""
            if (
                snap.put_wall_global_dist_pts is not None
                and snap.put_wall_global_dist_pct is not None
            ):
                pw_g_dist = (
                    f" (dist: {snap.put_wall_global_dist_pts:+,.2f} pts / "
                    f"{snap.put_wall_global_dist_pct:+.2f}%)"
                )
            print(
                f"    -> Mur Put global (hors fenêtre)  : "
                f"NDX {pw_g_ndx} | NQ {pw_g_nq}{pw_g_dist}"
            )
        elif snap.put_wall_global_ndx is None and snap.put_wall_useful_ndx is None:
            print("    -> Mur Put global                 : INDISPONIBLE [DÉGRADÉ]")

        if snap.zero_dte_call_wall_nq or snap.zero_dte_put_wall_nq:
            z_cw = f"{snap.zero_dte_call_wall_nq:,.2f}" if snap.zero_dte_call_wall_nq else "N/A"
            z_pw = f"{snap.zero_dte_put_wall_nq:,.2f}" if snap.zero_dte_put_wall_nq else "N/A"
            z_gex = f"{snap.zero_dte_net_gex / 1e6:+,.2f} M$" if snap.zero_dte_net_gex else "N/A"
            print(f"  0DTE Call/Put Wall   : NQ {z_cw} / {z_pw} (Net GEX : {z_gex})")

        # --- EXPECTED MOVE (TÂCHE 1 : DIAGNOSTIC DU STRADDLE DÉTAILLÉ) ---
        if snap.expected_move:
            em = snap.expected_move
            print("-" * 70)
            exp_str = em.expiry.strftime("%Y-%m-%d (%A)") if em.expiry else "N/A"
            em_age_val = em.data_age_minutes
            em_age_str = f"{em_age_val:.1f} min" if em_age_val is not None else "N/A"

            print(
                f"  EXPECTED MOVE — échéance : {exp_str} | "
                f"âge chaîne CBOE : {em_age_str}"
            )
            print(f"  IV ATM               : {em.iv_atm * 100:.2f}%")
            t_str = (
                f"{em.time_to_expiry_hours:.2f} h "
                f"({em.days_to_expiry:.2f} j calendaires, base ACT/365)"
                if em.time_to_expiry_hours is not None
                else f"{em.days_to_expiry:.2f} j (bourse)"
            )
            print(f"  Durée (T)            : {t_str}")

            # Méthode IV
            iv_pts = em.iv_move_nq if em.iv_move_nq is not None else em.formula_move
            iv_lo = em.iv_lower_nq if em.iv_lower_nq is not None else (snap.spot_nq - iv_pts)
            iv_hi = em.iv_upper_nq if em.iv_upper_nq is not None else (snap.spot_nq + iv_pts)
            print(f"  Méthode IV           : +/- {iv_pts:.1f} pts NQ")
            print(f"    Bornes IV          : [{iv_lo:,.2f} .. {iv_hi:,.2f}]")

            # Décomposition des spots
            print("    Décomposition des spots :")
            print(f"      - Spot NDX formule             : {em.spot_ndx_used:,.2f} pts")
            print(f"      - Spot NQ observé (centrage)   : {em.spot_nq_observed:,.2f} pts")
            print(
                f"      - NDX converti (NDX + base)    : {em.spot_nq_converted:,.2f} pts "
                f"(base {snap.basis:+,.2f} pts)"
            )
            spread_sign = f"{em.spread_nq_vs_converted:+,.2f}"
            print(f"      - Écart NQ observé vs converti : {spread_sign} pts")
            print("    Formule            : spot_ndx x IV x sqrt(T/365) -> [spot_nq +/- move]")

            # Méthode Straddle
            if em.straddle_move_nq is not None:
                s_lo = em.straddle_lower_nq if em.straddle_lower_nq is not None else "N/A"
                s_hi = em.straddle_upper_nq if em.straddle_upper_nq is not None else "N/A"
                s_lo_s = f"{s_lo:,.2f}" if isinstance(s_lo, float) else s_lo
                s_hi_s = f"{s_hi:,.2f}" if isinstance(s_hi, float) else s_hi
                print(f"  Méthode Straddle     : +/- {em.straddle_move_nq:.1f} pts NQ (≈ 0,8σ)")
                print(f"    Bornes Straddle    : [{s_lo_s} .. {s_hi_s}]")
                print("    Formule            : (C_ATM_mid + P_ATM_mid) via base")
            else:
                print("  Méthode Straddle     : N/A (bid/ask ATM manquants)")
            if em.discrepancy_pct is not None:
                disc_tol_val, disc_tol_src = _get_threshold_provenance(
                    "levels.straddle_max_discrepancy_pct", 25.0
                )
                coh_flag = "OK" if em.is_coherent else f"DÉGRADÉ (>{disc_tol_val:.0f}%)"
                print(
                    f"  Écart IV vs Straddle : {em.discrepancy_pct:.1f}% [{coh_flag}] "
                    f"(tolérance {disc_tol_val:.1f}% [source: {disc_tol_src}], "
                    "comparaison à unités égales 0,8σ)"
                )
            if em.status_explanation:
                print(f"  [!] {em.status_explanation}")

            # Sous-bloc DIAGNOSTIC STRADDLE DÉTAILLÉ (Tâche 1)
            sd = em.straddle_diagnostic
            if sd:
                print("    --- STRADDLE DIAGNOSTIC ---")
                print(f"      Spot NDX utilisé pour strike ATM : {sd.spot_ndx_used:,.2f} pts")
                print(f"      Strike ATM retenu               : {sd.atm_strike:,.2f}")
                r_match_s = (
                    "IDENTIQUES (OK)"
                    if sd.roots_match
                    else f"DIVERGENTES ({sd.call_leg.root} vs {sd.put_leg.root}) [DÉGRADÉ]"
                )
                exp_match_s = (
                    "IDENTIQUES (OK)"
                    if sd.expiries_match
                    else f"DIVERGENTES ({sd.call_leg.expiry} vs {sd.put_leg.expiry}) [DÉGRADÉ]"
                )
                print(
                    f"      Racines C/P                     : Call={sd.call_leg.root}, "
                    f"Put={sd.put_leg.root} [{r_match_s}]"
                )
                print(
                    f"      Expirations C/P                 : Call={sd.call_leg.expiry}, "
                    f"Put={sd.put_leg.expiry} [{exp_match_s}]"
                )
                spr_tol_val, spr_tol_src = _get_threshold_provenance(
                    "levels.straddle_max_spread_pct", 0.20
                )
                c_spr_warn = " [LARGE - DÉGRADÉ]" if sd.call_leg.is_spread_wide else " [OK]"
                print(
                    f"      Jambe Call ({sd.call_leg.root:4s})             : "
                    f"bid={sd.call_leg.bid:.2f}, ask={sd.call_leg.ask:.2f}, "
                    f"mid={sd.call_leg.mid:.2f} | IV={sd.call_leg.iv * 100:.2f}%, "
                    f"vol={sd.call_leg.volume:.0f}"
                )
                print(
                    f"        Largeur relative Call         : "
                    f"{sd.call_leg.spread_rel_pct:.1f}% "
                    f"(tol. {spr_tol_val * 100:.1f}% [source: {spr_tol_src}]){c_spr_warn}"
                )
                print(
                    f"        Horodatage cotation Call      : "
                    f"{sd.call_leg.quote_time_et or 'N/A'} | "
                    f"{sd.call_leg.quote_time_algiers or 'N/A'}"
                )
                has_c_time = (
                    sd.call_leg.age_minutes is not None
                    or sd.call_leg.delta_t_vs_spot_nq_minutes is not None
                )
                if has_c_time:
                    c_age = sd.call_leg.age_minutes
                    c_age_s = f"{c_age:.1f} min" if c_age is not None else "N/A"
                    c_dt_val = sd.call_leg.delta_t_vs_spot_nq_minutes
                    c_dt_s = f"{c_dt_val:+.2f} min" if c_dt_val is not None else "N/A"
                    print(
                        f"        Âge patte Call / vs spot NQ   : "
                        f"âge={c_age_s} | delta-t vs spot NQ={c_dt_s}"
                    )
                p_spr_warn = " [LARGE - DÉGRADÉ]" if sd.put_leg.is_spread_wide else " [OK]"
                print(
                    f"      Jambe Put ({sd.put_leg.root:4s})              : "
                    f"bid={sd.put_leg.bid:.2f}, ask={sd.put_leg.ask:.2f}, "
                    f"mid={sd.put_leg.mid:.2f} | IV={sd.put_leg.iv * 100:.2f}%, "
                    f"vol={sd.put_leg.volume:.0f}"
                )
                print(
                    f"        Largeur relative Put          : "
                    f"{sd.put_leg.spread_rel_pct:.1f}% "
                    f"(tol. {spr_tol_val * 100:.1f}% [source: {spr_tol_src}]){p_spr_warn}"
                )
                print(
                    f"        Horodatage cotation Put       : "
                    f"{sd.put_leg.quote_time_et or 'N/A'} | "
                    f"{sd.put_leg.quote_time_algiers or 'N/A'}"
                )
                has_p_time = (
                    sd.put_leg.age_minutes is not None
                    or sd.put_leg.delta_t_vs_spot_nq_minutes is not None
                )
                if has_p_time:
                    p_age = sd.put_leg.age_minutes
                    p_age_s = f"{p_age:.1f} min" if p_age is not None else "N/A"
                    p_dt_val = sd.put_leg.delta_t_vs_spot_nq_minutes
                    p_dt_s = f"{p_dt_val:+.2f} min" if p_dt_val is not None else "N/A"
                    print(
                        f"        Âge patte Put / vs spot NQ    : "
                        f"âge={p_age_s} | delta-t vs spot NQ={p_dt_s}"
                    )
                print(
                    f"      Temps restant à expiration (T)  : "
                    f"{sd.time_to_expiry_hours:.2f} h "
                    f"({sd.time_to_expiry_years:.4f} an, base ACT/365)"
                )
                print(
                    f"      Prix Straddle pur (C+P)         : "
                    f"{sd.straddle_points:.2f} pts NDX (≈ 0,8σ)"
                )
                print(
                    f"      Équivalent 1σ du Straddle       : "
                    f"{sd.straddle_move_1sigma_equiv:.2f} pts NDX"
                )
                print(
                    f"      Formule analytique 1σ (IV)      : "
                    f"{sd.formula_move_1sigma:.2f} pts NDX "
                    f"(Straddle théo 0,8σ = {sd.straddle_theo_from_iv:.2f} pts)"
                )
                print(
                    f"      IV implicite du Straddle        : "
                    f"{sd.implied_iv_straddle * 100:.2f}% "
                    f"(vs IV ATM CBOE : {sd.iv_atm_used * 100:.2f}%)"
                )
                print(
                    f"      Écart relatif à unités égales   : {sd.spread_pct_vs_iv:.1f}%"
                )
                if sd.neighbors:
                    print("      Strikes ATM voisins :")
                    for n in sd.neighbors:
                        is_atm_str = " (ATM)" if n.strike == sd.atm_strike else ""
                        print(
                            f"        Strike {n.strike:,.0f}{is_atm_str:6s} : "
                            f"Call mid={n.call_mid:.2f}, Put mid={n.put_mid:.2f} -> "
                            f"Straddle={n.straddle_mid:.2f} pts"
                        )
                diag_status_s = "DÉGRADÉ" if sd.is_degraded else "OK"
                print(f"      Statut diagnostic Straddle      : [{diag_status_s}]")
                if sd.calculated_cause:
                    print(f"      Cause calculée                  : {sd.calculated_cause}")
                elif sd.degraded_reason:
                    print(f"      Cause identifiée                : {sd.degraded_reason}")

        if snap.max_pain_nq:
            print(
                f"  Max Pain             : NDX {snap.max_pain_ndx:,.2f} "
                f"| NQ {snap.max_pain_nq:,.2f}"
            )

        # --- DIAGNOSTIC 1c (Tâche 3) ---
        d = snap.diagnostic_1c
        if d:
            print("-" * 70)
            print(f"  DIAGNOSTIC 1c — Séance {d.session_date.isoformat()}")
            print("  1. Cible             : 16:00 clôture actions")
            print(f"       ET              : {d.target_time_et}")
            print(f"       Alger           : {d.target_time_algiers}")
            print("  2. Étapes de recherche :")
            if d.search_steps_summary:
                for step_txt in d.search_steps_summary:
                    print(f"       - {step_txt}")
            res_str = (
                "PAIRE TROUVÉE"
                if (d.nq_candidate_found and d.ndx_candidate_found)
                else "PAIRE NON TROUVÉE"
            )
            print(f"  3. Résultat paire    : {res_str}")
            if d.nq_candidate_found:
                orig_nq = f", origine: {d.nq_origin}" if d.nq_origin else ""
                print(f"       Barre NQ        : {d.nq_candidate_time_et} |")
                print(f"                         {d.nq_candidate_time_algiers}")
                print(f"                         [close {d.nq_candidate_close:,.2f} pts{orig_nq}]")
            else:
                print("       Barre NQ        : NON TROUVÉE après mémoire et SQLite")
            if d.ndx_candidate_found:
                orig_ndx = f", origine: {d.ndx_origin}" if d.ndx_origin else ""
                print(f"       Cotation NDX    : {d.ndx_candidate_time_et} |")
                print(f"                         {d.ndx_candidate_time_algiers}")
                print(f"                         [spot {d.ndx_candidate_spot:,.2f} pts{orig_ndx}]")
            else:
                print("       Cotation NDX    : NON TROUVÉE après mémoire et SQLite")
            if d.delta_t_minutes is not None:
                align_flag = (
                    "OK"
                    if (d.delta_t_minutes <= d.tolerance_minutes)
                    else "HORS TOLÉRANCE"
                )
                print(
                    f"  4. Delta-t          : {d.delta_t_minutes:.2f} min "
                    f"(tol. {d.tolerance_minutes:.1f} min) [{align_flag}]"
                )
            else:
                print("  4. Delta-t          : N/A (paire incomplète)")
            print(f"  5. CAUSE            : {d.cause_code}")
            print(f"       Détail          : {d.cause_detail}")
            print(f"  6. Action prise     : {d.action_taken}")


        if snap.anomalies:
            print("-" * 70)
            print("  Alertes & Dégradations :")
            for a in snap.anomalies:
                print(f"    [!] {a}")
        print("=" * 70 + "\n")
        return 0
    elif args.subcommand == "brief":
        print("[nqcockpit] Commande 'brief' invoquée (génération briefing).")
        return 0
    elif args.subcommand == "ui":
        print("[nqcockpit] Commande 'ui' invoquée (interface utilisateur).")
        return _handle_ui(args)
    elif args.subcommand == "data":
        from nqcockpit.data.archiver import BarArchiver
        from nqcockpit.data.db import apply_migrations, get_db_connection
        from nqcockpit.data.roll import detect_nq_roll

        if args.data_action == "migrate":
            conn = get_db_connection()
            count = apply_migrations(conn)
            conn.close()
            print(f"[nqcockpit] {count} migration(s) appliquée(s) sur data/nqcockpit.db.")
            return 0
        elif args.data_action == "roll":
            info = detect_nq_roll()
            print(f"[nqcockpit] Roll NQ : {info.status}")
            print(f"  Contrat actif  : {info.active_contract}")
            print(f"  Contrat suivant: {info.next_contract}")
            print(f"  Expiration     : {info.expiry_date} ({info.days_to_expiry} jours restants)")
            print(f"  Début fenêtre  : {info.roll_window_start}")
            print(f"  Message        : {info.message}")
            return 0
        elif args.data_action == "archive":
            print("[nqcockpit] Début de l'archivage des barres dans SQLite (data/nqcockpit.db)...")
            archiver = BarArchiver()
            res = archiver.archive_symbols()
            msg = (
                f"[nqcockpit] Archivage terminé : {res.total_bars_inserted} barres insérées. "
                f"Statut : {res.status.value}"
            )
            print(msg)
            return 0
        elif args.data_action == "status":
            conn = get_db_connection()
            apply_migrations(conn)
            sql = (
                "SELECT symbol, interval, COUNT(*) as c, MIN(timestamp_utc) as min_t, "
                "MAX(timestamp_utc) as max_t FROM bars GROUP BY symbol, interval"
            )
            cur = conn.execute(sql)
            rows = cur.fetchall()
            print("[nqcockpit] Statistiques de la base data/nqcockpit.db :")
            if not rows:
                print("  Aucune barre enregistrée pour le moment.")
            else:
                for r in rows:
                    line = (
                        f"  - {r['symbol']} ({r['interval']}) : {r['c']} barres "
                        f"(du {r['min_t']} au {r['max_t']})"
                    )
                    print(line)
            conn.close()
            return 0
        elif args.data_action == "fred":
            from nqcockpit.data.fetcher import DataFetcher

            print("[nqcockpit] Récupération des taux FRED (DGS2, DGS10)...")
            fetcher = DataFetcher()
            dgs2 = fetcher.fetch_fred_series("DGS2", max_cache_age_seconds=0)
            dgs10 = fetcher.fetch_fred_series("DGS10", max_cache_age_seconds=0)
            print(
                f"  DGS2  : {dgs2.value:.2f}% "
                f"(date d'observation : {dgs2.observation_date}) [{dgs2.status.value}]"
            )
            print(
                f"  DGS10 : {dgs10.value:.2f}% "
                f"(date d'observation : {dgs10.observation_date}) [{dgs10.status.value}]"
            )
            return 0
        else:
            parser.parse_args(["data", "--help"])
            return 0
    elif args.subcommand == "events":
        from nqcockpit.config import load_config
        from nqcockpit.events.radar import fetch_event_radar, render_console

        print("[nqcockpit] Radar d'événements en cours d'analyse...")
        cfg = load_config(args.config)
        report = fetch_event_radar(config=cfg, horizon_days=args.horizon)
        print("\n" + render_console(report) + "\n")
        return 0
    elif args.subcommand == "playbook":
        return _handle_playbook(args)
    elif args.subcommand == "macro":
        return _handle_macro(args)
    elif args.subcommand == "amplitude":
        return _handle_amplitude(args)
    elif args.subcommand == "profile":
        return _handle_profile(args)
    elif args.subcommand == "journal":
        return _handle_journal(args)
    elif args.subcommand == "discipline":
        return _handle_discipline(args)

    return 0


def _render_card_console(card: object) -> str:
    """Affichage console d'une EventPlaybookCard."""

    from nqcockpit.playbook.card import card_to_dict

    d = card_to_dict(card)  # type: ignore[arg-type]
    lines: list[str] = []
    sep = "=" * 70

    lines.append(sep)
    lines.append(f"  FICHE PLAYBOOK — {d['event_name']} (Tier {d['tier']})")
    lines.append(sep)
    lines.append(f"  Génération         : {d['generation_trigger']}")
    lines.append(f"  Généré le          : {d['generated_at_utc']}")
    lines.append(f"  Publication        : {d['scheduled_et']} | {d['scheduled_algiers']}")
    lines.append(f"  Compte à rebours   : {d['countdown']}")
    lines.append(f"  Origine de la date : {d['date_origin']}")
    lines.append(f"  Provenance heure   : {d['time_provenance']}")
    lines.append(f"  Statut             : {d['status']}")
    if d.get("status_detail"):
        lines.append(f"  Détail             : {d['status_detail']}")

    lines.append("-" * 70)
    lines.append("  CONSENSUS & PRÉCÉDENT")
    consensus_src = d["consensus_source"] or "N/A"
    cons_str = d["consensus"] if d["consensus"] is not None else f"None [{d['consensus_status']}]"
    lines.append(f"  Consensus : {cons_str} (source: {consensus_src})")
    prev_str = d["previous"] if d["previous"] is not None else f"None [{d['previous_status']}]"
    lines.append(f"  Précédent : {prev_str}")

    lines.append("-" * 70)
    lines.append("  POSITIONNEMENT")
    pos = d.get("positioning", {})
    lines.append(f"  Statut             : {pos.get('status', 'N/A')}")
    if pos.get("status_detail"):
        lines.append(f"  Détail             : {pos.get('status_detail')}")
    lines.append(f"  Spot NQ            : {pos.get('spot_nq', 'N/A')}")
    lines.append(f"  Expected move      : {pos.get('expected_move_pts', 'N/A')} pts")
    lines.append(f"  Régime gamma       : {pos.get('regime_gamma', 'N/A')}")
    lines.append(f"  Call wall (dist)   : +{pos.get('dist_call_wall_pts', 'N/A')} pts")
    lines.append(f"  Put support (dist) : -{pos.get('dist_put_wall_pts', 'N/A')} pts")
    lines.append(f"  VXN                : {pos.get('vxn_spot', 'N/A')}")
    lines.append(f"  VIX                : {pos.get('vix_spot', 'N/A')}")
    lines.append(f"  Âge données        : {pos.get('data_age_minutes', 'N/A')} min")

    lines.append("-" * 70)
    lines.append("  HISTORIQUE DE RÉACTION NQ")
    for h in ["+1m", "+5m", "+15m", "+60m"]:
        rs = d.get("reaction_stats", {}).get(h, {})
        if rs.get("is_sufficient"):
            lines.append(
                f"  {h:5s} n={rs['n']:3d} | "
                f"médiane={rs['median_pts']:+.1f} pts | "
                f"Q25={rs['q25_pts']:+.1f} | Q75={rs['q75_pts']:+.1f} | "
                f"retournements={rs.get('reversal_pct', 'N/A')}%"
            )
        else:
            note = rs.get("note", "échantillon insuffisant")
            lines.append(f"  {h:5s} — {note} (n={rs.get('n', 0)})")

    lines.append("-" * 70)
    lines.append("  SCÉNARIOS CONDITIONNELS (ce qu'on observe — aucun biais directionnel)")
    for sc in d.get("scenarios", []):
        seuil = f" (seuil: {sc['surprise_threshold']})" if sc.get("surprise_threshold") else ""
        lines.append(f"\n  [{sc['label'].upper()}{seuil}]")
        lines.append(f"  {sc['description']}")
        for lvl in sc.get("levels_to_watch", []):
            lines.append(f"    • {lvl}")
        lines.append(f"  Protocole : {sc.get('protocol', '')}")

    lines.append("-" * 70)
    lines.append("  PROTOCOLE D'ACTION (config)")
    lines.append(f"  Stand aside avant  : {d['stand_aside_before_minutes']} min")
    lines.append(f"  Attendre après     : {d['wait_after_minutes']} min")
    lines.append(f"  Buffer post-event  : {d['post_event_buffer_minutes']} min")
    lines.append(sep)
    return "\n".join(lines)


def _handle_playbook(args: object) -> int:
    """Gestionnaire des sous-commandes 'playbook'."""
    import json as _json
    from datetime import datetime, timezone

    from nqcockpit.config import load_config
    from nqcockpit.data.db import apply_migrations, get_bars, get_db_connection
    from nqcockpit.events.radar import fetch_event_radar

    cfg = load_config(getattr(args, "config", None))
    playbook_action = getattr(args, "playbook_action", None)

    if playbook_action == "card":
        from nqcockpit.playbook.card import card_to_dict, generate_card

        now_utc = datetime.now(timezone.utc)
        event_filter = getattr(args, "event", None)
        as_json = getattr(args, "json", False)

        # Récupérer le radar d'événements
        report = fetch_event_radar(config=cfg, horizon_days=cfg.events.horizon_days)
        events = report.events_14d

        # Filtrer sur le nom demandé ou prendre le prochain Tier 1
        target = None
        tier1_names_lower = [t.lower() for t in cfg.events.tier1]
        for ev in sorted(events, key=lambda e: e.scheduled_utc):
            if ev.scheduled_utc <= now_utc:
                continue
            if event_filter:
                if event_filter.lower() in ev.name.lower():
                    target = ev
                    break
            else:
                if ev.name.lower() in tier1_names_lower:
                    target = ev
                    break

        if target is None:
            print("[playbook] Aucun événement Tier 1 trouvé dans l'horizon.", file=sys.stderr)
            return 1

        # Connexion DB
        conn = get_db_connection(cfg.data.db_path)
        apply_migrations(conn)
        bars_nq = get_bars(conn, "NQ=F", "1m", limit=500)

        source_health_map = {
            sh.source: (sh.error_msg or sh.status.value)
            for sh in report.source_health
        }

        card = generate_card(
            event=target,
            levels_snapshot=None,  # pas de snapshot live disponible en CLI stateless
            bars_nq_1m=bars_nq,
            db_conn=conn,
            min_event_samples=cfg.validation.min_event_samples,
            stand_aside_before_minutes=cfg.events.stand_aside_before_minutes,
            wait_after_minutes=cfg.events.wait_after_minutes,
            post_event_buffer_minutes=cfg.events.post_event_buffer_minutes,
            source_health_map=source_health_map,
            now_utc=now_utc,
        )
        conn.close()

        if as_json:
            print(_json.dumps(card_to_dict(card), ensure_ascii=False, indent=2))
        else:
            print(_render_card_console(card))
        return 0

    elif playbook_action == "fed-diff":
        from zoneinfo import ZoneInfo

        from nqcockpit.playbook.fed_intelligence import diff_statements

        ET_TZ = ZoneInfo("America/New_York")
        ALG_TZ = ZoneInfo("Africa/Algiers")

        # URLs des deux derniers communiqués FOMC (federalreserve.gov)
        # Source statique 2026 — vérifiée manuellement
        FOMC_STATEMENTS_2026 = [
            (
                "2026-07-29",
                "https://www.federalreserve.gov/newsevents/pressreleases/"
                "monetary20260729a.htm",
            ),
            (
                "2026-09-16",
                "https://www.federalreserve.gov/newsevents/pressreleases/"
                "monetary20260916a.htm",
            ),
        ]

        prev_url = getattr(args, "prev_url", "") or FOMC_STATEMENTS_2026[-2][1]
        curr_url = getattr(args, "curr_url", "") or FOMC_STATEMENTS_2026[-1][1]

        print(f"[playbook fed-diff] Précédent : {prev_url}")
        print(f"[playbook fed-diff] Courant   : {curr_url}")
        print("[playbook fed-diff] Téléchargement et diff en cours...")

        fomc_diff = diff_statements(prev_url=prev_url, curr_url=curr_url)
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
        now_alg = now_utc.astimezone(ALG_TZ).strftime("%Y-%m-%d %H:%M Alger")

        print("\n" + "=" * 70)
        print("  DIFF FOMC — LECTURE DE TON")
        print(f"  Horodatage : {now_et} | {now_alg}")
        print(f"  Statut     : {fomc_diff.status}")
        if fomc_diff.status_detail:
            print(f"  Détail     : {fomc_diff.status_detail}")
        print(f"  Ton        : {fomc_diff.tone_label or 'indéterminé'}")
        print(f"  NOTE       : {fomc_diff.tone_note}")
        print("-" * 70)
        print(f"  Phrases ajoutées ({len(fomc_diff.added_sentences)}) :")
        for s in fomc_diff.added_sentences:
            print(f"    [+] {s}")
        print(f"  Phrases retirées ({len(fomc_diff.removed_sentences)}) :")
        for s in fomc_diff.removed_sentences:
            print(f"    [-] {s}")
        if fomc_diff.tone_extracts:
            print("-" * 70)
            print("  Extraits clés :")
            for e in fomc_diff.tone_extracts:
                print(f"    {e}")
        print("=" * 70)
        return 0

    elif playbook_action == "minutes-watch":
        from zoneinfo import ZoneInfo

        from nqcockpit.events.radar import fetch_event_radar
        from nqcockpit.playbook.fed_intelligence import generate_minutes_watch

        ET_TZ = ZoneInfo("America/New_York")
        ALG_TZ = ZoneInfo("Africa/Algiers")

        now_utc = datetime.now(timezone.utc)
        report = fetch_event_radar(config=cfg, horizon_days=cfg.events.horizon_days)

        minutes_event = None
        for ev in sorted(report.events_14d, key=lambda e: e.scheduled_utc):
            if ev.name == "FOMC Minutes" and ev.scheduled_utc > now_utc:
                minutes_event = ev
                break

        if minutes_event is None:
            print("[playbook minutes-watch] Aucunes minutes FOMC dans l'horizon.", file=sys.stderr)
            return 1

        prev_url = (
            "https://www.federalreserve.gov/newsevents/pressreleases/"
            "monetary20260916a.htm"
        )
        watch = generate_minutes_watch(
            fomc_minutes_event=minutes_event,
            prev_statement_url=prev_url,
        )

        sched_et = minutes_event.scheduled_utc.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
        sched_alg = minutes_event.scheduled_utc.astimezone(ALG_TZ).strftime("%Y-%m-%d %H:%M Alger")
        now_et = now_utc.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
        now_alg = now_utc.astimezone(ALG_TZ).strftime("%Y-%m-%d %H:%M Alger")

        print("\n" + "=" * 70)
        print("  FICHE 'À SURVEILLER' — MINUTES FOMC")
        print(f"  Horodatage     : {now_et} | {now_alg}")
        print(f"  Publication    : {sched_et} | {sched_alg}")
        print(f"  Statut         : {watch.status}")
        if watch.status_detail:
            print(f"  Détail         : {watch.status_detail}")
        print("-" * 70)
        dgs2_disp = f"{watch.dgs2_rate:.2f}%" if watch.dgs2_rate is not None else "N/A"
        print(
            f"  DGS2 (proxy taux) : {dgs2_disp} "
            f"(date: {watch.dgs2_date or 'N/A'}) [{watch.dgs2_status}]"
        )
        print("-" * 70)
        print("  Thèmes du dernier communiqué :")
        if watch.themes:
            for t in watch.themes:
                print(f"    • {t[:150]}")
        else:
            print("    Aucun thème extrait (source DÉGRADÉE ou URL manquante)")
        print("-" * 70)
        print("  NOTE : aide de lecture, pas un signal")
        print("=" * 70)
        return 0

    else:
        parser = create_parser()
        parser.parse_args(["playbook", "--help"])
        return 0


def _handle_macro(args: object) -> int:
    """Gestionnaire de la commande 'macro' (P07)."""
    import json as _json
    from zoneinfo import ZoneInfo

    from nqcockpit.config import load_config
    from nqcockpit.data.db import get_bars, get_db_connection
    from nqcockpit.macro.engine import compute_macro_snapshot

    cfg = load_config(getattr(args, "config", None))
    conn = get_db_connection(cfg.data.db_path)
    bars_nq = get_bars(conn, "NQ=F", "1m", limit=600)
    conn.close()

    snap = compute_macro_snapshot(config=cfg, bars_nq=bars_nq)

    as_json = getattr(args, "json", False)
    if as_json:
        d = {
            "as_of_utc": snap.as_of_utc.isoformat(),
            "status": snap.status,
            "status_detail": snap.status_detail,
            "metrics": {
                k: {
                    "name": m.name,
                    "symbol": m.symbol,
                    "current_value": m.current_value,
                    "observation_date": m.observation_date,
                    "percentile_1y": m.percentile_1y,
                    "delta_5d": m.delta_5d,
                    "delta_5d_pct": m.delta_5d_pct,
                    "source": m.source,
                    "status": m.status,
                    "provenance": m.provenance,
                }
                for k, m in snap.metrics.items()
            },
            "overnight": {
                "session_date": snap.overnight.session_date,
                "high_price": snap.overnight.high_price,
                "low_price": snap.overnight.low_price,
                "open_price": snap.overnight.open_price,
                "last_price": snap.overnight.last_price,
                "prior_close_price": snap.overnight.prior_close_price,
                "range_pts": snap.overnight.range_pts,
                "gap_pts": snap.overnight.gap_pts,
                "status": snap.overnight.status,
                "source": snap.overnight.source,
            },
            "cot": {
                "report_date": snap.cot.report_date,
                "contract_name": snap.cot.contract_name,
                "non_commercial_net": snap.cot.non_commercial_net,
                "non_commercial_long": snap.cot.non_commercial_long,
                "non_commercial_short": snap.cot.non_commercial_short,
                "change_net_1w": snap.cot.change_net_1w,
                "percentile_1y": snap.cot.percentile_1y,
                "status": snap.cot.status,
                "source": snap.cot.source,
                "note": snap.cot.note,
            },
        }
        print(_json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    ET_TZ = ZoneInfo("America/New_York")
    ALG_TZ = ZoneInfo("Africa/Algiers")
    as_et = snap.as_of_utc.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
    as_alg = snap.as_of_utc.astimezone(ALG_TZ).strftime("%Y-%m-%d %H:%M Alger")

    sep = "=" * 75
    subsep = "-" * 75
    print("\n" + sep)
    print("  NQ COCKPIT — CONTEXTE MACROÉCONOMIQUE & CROSS-ASSET (P07)")
    print(f"  Horodatage : {as_et} | {as_alg}")
    print(f"  Statut     : {snap.status}")
    if snap.status_detail:
        print(f"  Détail     : {snap.status_detail}")
    print(sep)
    print("  TAUX & VOLATILITÉ (percentiles 1 an = 252 séances, variation 5 jours)")
    print(subsep)
    hdr = (
        f"  {'Métrique':<10} {'Niveau':<12} {'Percentile 1 an':<18} "
        f"{'Var. 5j':<15} {'Source / Statut'}"
    )
    print(hdr)
    print(f"  {'-'*8} {'-'*10} {'-'*16} {'-'*13} {'-'*20}")
    for k in ["us10y", "us2y", "dxy", "vix", "vxn"]:
        m = snap.metrics.get(k)
        if not m:
            continue
        val_str = f"{m.current_value:.2f}" if m.current_value is not None else "N/A"
        if k in ("us10y", "us2y"):
            val_str += " %"
        pct_str = f"{m.percentile_1y:.1f} %" if m.percentile_1y is not None else "N/A"
        if m.delta_5d is not None and m.delta_5d_pct is not None:
            d5_str = f"{m.delta_5d:+.2f} ({m.delta_5d_pct:+.1f}%)"
        elif m.delta_5d is not None:
            d5_str = f"{m.delta_5d:+.2f}"
        else:
            d5_str = "N/A"
        src_st = f"[{m.status}] {m.source}"
        print(f"  {m.name:<10} {val_str:<12} {pct_str:<18} {d5_str:<15} {src_st}")

    print(subsep)
    print("  OVERNIGHT NQ (session CME 18:00 - 09:30 ET)")
    ov = snap.overnight
    rng_str = f"{ov.range_pts:.1f} pts" if ov.range_pts is not None else "N/A"
    gap_str = f"{ov.gap_pts:+.1f} pts" if ov.gap_pts is not None else "N/A"
    h_str = f"H: {ov.high_price or 'N/A'}"
    l_str = f"L: {ov.low_price or 'N/A'}"
    print(f"  Range de la nuit : {rng_str} ({h_str} | {l_str})")
    print(
        f"  Gap vs veille    : {gap_str} "
        f"(Clôture veille: {ov.prior_close_price or 'N/A'} | Dernier: {ov.last_price or 'N/A'})"
    )
    print(f"  Statut overnight : [{ov.status}] {ov.source}")

    print(subsep)
    print("  POSITIONNEMENT COT (CFTC — CONTEXTE SEULEMENT, AUCUN SIGNAL)")
    cot = snap.cot
    net_str = f"{cot.non_commercial_net:,d}" if cot.non_commercial_net is not None else "N/A"
    chg_str = f"{cot.change_net_1w:+,d}" if cot.change_net_1w is not None else "N/A"
    cot_pct = f"{cot.percentile_1y:.1f} %" if cot.percentile_1y is not None else "N/A"
    print(f"  Contrat          : {cot.contract_name}")
    print(f"  Date du relevé   : {cot.report_date} (mardi de relevé)")
    print(f"  Position nette   : {net_str} contrats (Spéculateurs non-commerciaux)")
    print(f"  Variation 1 sem. : {chg_str} contrats | Percentile 1 an : {cot_pct}")
    print(f"  Statut COT       : [{cot.status}] {cot.source}")
    print(f"  NOTE             : {cot.note}")
    print(sep)
    return 0


def _handle_amplitude(args: object) -> int:
    """Gestionnaire de la commande 'amplitude' (P07)."""
    import json as _json
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from nqcockpit.config import load_config
    from nqcockpit.data.db import apply_migrations, get_bars, get_db_connection
    from nqcockpit.forecast.engine import (
        build_calibration_report,
        compute_amplitude_forecast,
        record_daily_forecast,
    )

    cfg = load_config(getattr(args, "config", None))
    conn = get_db_connection(cfg.data.db_path)
    apply_migrations(conn)

    ET_TZ = ZoneInfo("America/New_York")
    ALG_TZ = ZoneInfo("Africa/Algiers")
    now_utc = datetime.now(timezone.utc)
    target_date = getattr(args, "date", None) or now_utc.astimezone(ET_TZ).strftime("%Y-%m-%d")

    cur_snap = conn.execute(
        "SELECT spot, expected_move FROM snapshots ORDER BY timestamp_utc DESC LIMIT 1"
    ).fetchone()
    spot_nq = cur_snap[0] if cur_snap else None
    base_em = cur_snap[1] if cur_snap else None

    if spot_nq is None or base_em is None:
        nq_bars = get_bars(conn, "NQ=F", "1m", limit=100)
        if nq_bars:
            spot_nq = nq_bars[-1].close
            base_em = round(spot_nq * 0.011, 2)
        else:
            try:
                from nqcockpit.macro.fetcher import fetch_yahoo_history
                hist = fetch_yahoo_history("NQ=F", period="5d", interval="1m")
                if not hist.empty:
                    spot_nq = float(hist["Close"].iloc[-1])
                    base_em = round(spot_nq * 0.011, 2)
            except Exception:
                pass

    if spot_nq is None:
        spot_nq = 20000.0
    if base_em is None:
        base_em = round(spot_nq * 0.011, 2)

    cur_days = conn.execute(
        """
        SELECT SUBSTR(b.timestamp_utc, 1, 10) as day,
               MIN(b.low) as low, MAX(b.high) as high,
               (SELECT b2.open FROM bars b2 WHERE b2.symbol='NQ=F' AND b2.interval='1m'
                AND SUBSTR(b2.timestamp_utc,1,10)=SUBSTR(b.timestamp_utc,1,10)
                ORDER BY b2.timestamp_utc ASC LIMIT 1) as open,
               (SELECT b3.close FROM bars b3 WHERE b3.symbol='NQ=F' AND b3.interval='1m'
                AND SUBSTR(b3.timestamp_utc,1,10)=SUBSTR(b.timestamp_utc,1,10)
                ORDER BY b3.timestamp_utc DESC LIMIT 1) as close
        FROM bars b
        WHERE b.symbol = 'NQ=F' AND b.interval = '1m'
        GROUP BY SUBSTR(b.timestamp_utc, 1, 10)
        ORDER BY day ASC
        """
    )
    hist_sessions = [dict(r) for r in cur_days.fetchall()]

    forecast = compute_amplitude_forecast(
        spot_nq=spot_nq,
        base_expected_move_pts=base_em,
        target_date=target_date,
        historical_sessions=hist_sessions,
        config=cfg,
        now_utc=now_utc,
    )

    record_daily_forecast(forecast, conn)
    cal_rep = build_calibration_report(conn, config=cfg, now_utc=now_utc)
    conn.close()

    as_json = getattr(args, "json", False)
    if as_json:
        d = {
            "as_of_utc": forecast.as_of_utc.isoformat(),
            "target_date": forecast.target_date,
            "spot_nq": forecast.spot_nq,
            "base_expected_move_pts": forecast.base_expected_move_pts,
            "base_source": forecast.base_source,
            "empirical_adjustment_factor": forecast.empirical_adjustment_factor,
            "is_calibrated": forecast.is_calibrated,
            "calibration_status": forecast.calibration_status,
            "calibration_reason": forecast.calibration_reason,
            "projected_amplitude_pts": forecast.projected_amplitude_pts,
            "range_low": forecast.range_low,
            "range_high": forecast.range_high,
            "day_type_probabilities": [
                {
                    "day_type": p.day_type,
                    "count": p.count,
                    "total_sessions": p.total_sessions,
                    "probability_pct": p.probability_pct,
                    "wilson_ci_low_pct": p.wilson_ci_low_pct,
                    "wilson_ci_high_pct": p.wilson_ci_high_pct,
                    "is_sufficient": p.is_sufficient,
                    "definition": p.definition,
                    "note": p.note,
                }
                for p in forecast.day_type_probabilities
            ],
            "status": forecast.status,
            "status_detail": forecast.status_detail,
        }
        print(_json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    now_et = now_utc.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
    now_alg = now_utc.astimezone(ALG_TZ).strftime("%Y-%m-%d %H:%M Alger")

    sep = "=" * 75
    subsep = "-" * 75
    print("\n" + sep)
    print("  NQ COCKPIT — PRÉVISIONS D'AMPLITUDE & CALIBRATION (P07)")
    print(f"  Horodatage       : {now_et} | {now_alg}")
    print(f"  Séance cible     : {forecast.target_date}")
    print(f"  Statut           : {forecast.status}")
    print(sep)

    print("  PRÉVISION D'AMPLITUDE DU JOUR")
    print(subsep)
    print(f"  Spot NQ                  : {forecast.spot_nq or 'N/A'}")
    print(f"  Expected Move de base    : {forecast.base_expected_move_pts or 'N/A'} pts")
    print(f"  Source de base           : {forecast.base_source}")
    if forecast.empirical_adjustment_factor is not None:
        adj_str = f"{forecast.empirical_adjustment_factor:.2f}"
    else:
        adj_str = "aucun (non prouvé — échantillon insuffisant)"
    print(f"  Ajustement empirique     : {adj_str}")
    print(f"  Amplitude projetée (EM)  : {forecast.projected_amplitude_pts or 'N/A'} pts")
    rng_str = f"[{forecast.range_low or 'N/A'}  —  {forecast.range_high or 'N/A'}]"
    print(f"  Bornes projetées (±EM/2) : {rng_str}")
    print(subsep)

    # AFFICHAGE SÉPARÉ DE L'ÉTAT DE CALIBRATION (CRITÈRE D'ACCEPTATION)
    print("  ÉTAT DE CALIBRATION (séparé de l'amplitude)")
    print(subsep)
    print(f"  État de calibration      : [{forecast.calibration_status.upper()}]")
    print(f"  Justification            : {forecast.calibration_reason}")
    print(
        f"  Règle stricte            : Aucun ajustement empirique sous "
        f"{cfg.forecast.min_calibration_sessions} séances complètes."
    )
    print(subsep)

    print("  PROBABILITÉS EMPIRIQUES DU TYPE DE JOURNÉE (Intervalles de Wilson à 95 %)")
    print(subsep)
    hdr_p = f"  {'Type':<10} {'Observé':<10} {'IC Wilson 95 %':<20} {'Définition figée (config)'}"
    print(hdr_p)
    print(f"  {'-'*8} {'-'*8} {'-'*18} {'-'*35}")
    for p in forecast.day_type_probabilities:
        prob_str = f"{p.probability_pct:.1f} %"
        ci_str = f"[{p.wilson_ci_low_pct:.1f}% - {p.wilson_ci_high_pct:.1f}%]"
        note_str = f" ({p.note})" if p.note else ""
        print(f"  {p.day_type:<10} {prob_str:<10} {ci_str:<20} {p.definition}{note_str}")

    print(subsep)
    print("  SUIVI DE CALIBRATION 1-SIGMA (historique forecasts)")
    m1 = cal_rep.metrics_1sigma
    print(f"  Séances archivées        : {m1.total_forecasts} (couvertes : {m1.covered_count})")
    cov_str = (
        f"{m1.observed_coverage_pct:.1f} % (attendu théorique : {m1.target_coverage_pct:.1f} %)"
    )
    print(f"  Couverture observée      : {cov_str}")
    print(f"  Écart à la cible         : {m1.coverage_gap_pct:+.1f} %")
    bs_str = f"{m1.brier_score:.4f}" if m1.brier_score is not None else "N/A"
    print(f"  Brier score              : {bs_str}")
    print("  Rapport généré           : reports/calibration.md")
    print(sep)

    return 0


def _handle_profile(args: Any) -> int:
    """Affiche le profil de séance, la carte de scénarios et les drapeaux NO-TRADE (P08)."""
    import json
    from datetime import datetime, timezone

    from nqcockpit.config import load_config
    from nqcockpit.data.db import apply_migrations, get_db_connection
    from nqcockpit.profile.engine import build_day_profile, export_levels_to_csv

    cfg = load_config(getattr(args, "config", None))
    now_utc = datetime.now(timezone.utc)

    # Connexion DB
    try:
        conn = get_db_connection()
        apply_migrations(conn)
    except Exception:
        conn = None

    profile = build_day_profile(conn=conn, config=cfg, now_utc=now_utc)
    if conn:
        conn.close()

    # Export CSV optionnel
    csv_path = getattr(args, "export_csv", None)
    if csv_path and profile.key_levels:
        export_levels_to_csv(profile.key_levels, filepath=csv_path, now_utc=now_utc)
        print(f"[nqcockpit] Niveaux exportés → {csv_path}")

    # Sortie JSON
    if getattr(args, "json", False):
        print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
        return 0

    # Sortie console structurée
    sep = "=" * 75
    sub = "-" * 75
    print()
    print(sep)
    print("  NQ COCKPIT — PROFIL DE SÉANCE, SCÉNARIOS & DRAPEAUX NO-TRADE (P08)")
    print(f"  Horodatage : {profile.as_of_et} | {profile.as_of_algiers}")
    print(f"  Séance     : {profile.target_date}  |  Spot NQ : {profile.spot_nq:.2f} pts")
    print(f"  Statut     : {profile.status}")
    if profile.status_detail:
        print(f"  Détail     : {profile.status_detail}")
    print(sep)

    # --- STATUT NO-TRADE ---
    nt = profile.no_trade
    if nt.is_trading_allowed:
        print("  🟢 TRADING AUTORISÉ (sous conditions de setup et Kill Zones)")
    else:
        print(f"  🔴 NO-TRADE ACTIF — {nt.active_flags_count} drapeau(x) bloquant(s)")
    print(sub)

    print("  DRAPEAUX NO-TRADE (un par catégorie, cause explicite)")
    print(sub)
    for flag in nt.all_flags:
        if flag.triggered:
            icon = "🔴 ACTIF    "
        elif "DÉGRADÉ" in flag.status:
            icon = "🟡 DÉGRADÉ  "
        else:
            icon = "🟢 INACTIF  "
        print(f"  {icon} [{flag.code.value}] {flag.title}")
        print(f"           Cause   : {flag.reason}")
        print(f"           Module  : {flag.source_module} | Sévérité : {flag.severity}")
    print(sub)

    # --- SANTÉ DES COMPOSANTS ---
    print("  SANTÉ DES COMPOSANTS (statut individuel — aucun masquage)")
    print(sub)
    for _c_key, c_val in profile.component_statuses.items():
        icon = "🟢" if "DÉGRADÉ" not in c_val.status else "🔴"
        print(f"  {icon} {c_val.name}")
        print(f"     Statut  : {c_val.status}")
        if c_val.detail:
            print(f"     Détail  : {c_val.detail}")
    print(sub)

    # --- PROFIL CONTEXTUEL ---
    print("  PROFIL CONTEXTUEL DE LA SÉANCE")
    print(sub)
    print(f"  Risque événementiel : {profile.event_risk_level} — {profile.event_risk_reason}")
    if profile.next_tier1_event:
        cd_str = profile.next_tier1_countdown or "imminent"
        print(f"  Prochain Tier 1     : {profile.next_tier1_event} (dans {cd_str})")
    print(f"  Régime de Volatilité: {profile.volatility_regime}"
          f" (VIX={profile.vix_level}, VXN={profile.vxn_level})")
    print(f"  Régime Gamma (P04)  : {profile.gamma_regime}"
          f" | Distance au Flip : {profile.distance_to_flip_pts}")
    if profile.em_consumption_pct is not None:
        em_cons_str = f"{profile.em_consumption_pct:.1f} %"
    else:
        em_cons_str = "N/A"
    print(f"  Expected Move base  : {profile.base_expected_move_pts:.1f} pts"
          f" | Consommé overnight : {em_cons_str}")
    if profile.overnight_range_pts is not None:
        on_range = f"{profile.overnight_range_pts:.1f} pts"
    else:
        on_range = "N/A"
    print(f"  Range overnight     : {on_range}")
    print(f"  Type de séance      : {profile.probable_day_type}")
    for reason in profile.day_type_reasons:
        print(f"    → {reason}")
    print(sub)

    # --- NIVEAUX CLÉS ---
    print("  NIVEAUX CLÉS EN POINTS NQ")
    print(sub)
    hdr = f"  {'Niveau':<30} {'Prix':>10} {'Dist.(pts)':>12} {'Écart %':>9}  Source"
    print(hdr)
    print(f"  {'-'*28} {'-'*10} {'-'*12} {'-'*9}  {'-'*18}")
    for lvl in profile.key_levels:
        print(
            f"  {lvl.name:<30} {lvl.price:>10.2f} {lvl.distance_pts:>+12.1f}"
            f" {lvl.distance_pct:>+9.2f}%  {lvl.source}"
        )
    print(sub)

    # --- CARTE DE SCÉNARIOS ---
    print("  CARTE DE SCÉNARIOS « SI… ALORS… » (ZÉRO PRÉDICTION DIRECTIONNELLE)")
    print(sub)
    for i, sc in enumerate(profile.scenarios, 1):
        print(f"  [{i}] {sc.level_name} ({sc.level_price:.1f} pts) — {sc.level_type}")
        print(f"      Condition : {sc.if_condition}")
        print(f"      Plan      : {sc.then_plan}")
        if sc.context_notes:
            print(f"      Contexte  : {sc.context_notes}")
    print(sep)

    return 0


def _handle_journal(args: Any) -> int:
    """Sous-commande journal (P09) — stats, daily, coaching, ui."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from nqcockpit.config import load_config
    from nqcockpit.journal.engine import (
        compute_daily_stats,
        compute_performance_stats,
        generate_coaching_report,
    )
    from nqcockpit.journal.store import init_journal_db, load_trades

    config = load_config()
    tz_ny = ZoneInfo(config.timezones.market)
    action = getattr(args, "journal_action", None)

    if action == "ui":
        import subprocess  # noqa: S603
        import sys
        from pathlib import Path
        port = getattr(args, "port", 8501)
        page_path = Path(__file__).parent / "ui" / "app.py"
        print(f"[nqcockpit] Terminal Multipage Streamlit sur http://localhost:{port}")
        try:
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "streamlit", "run", str(page_path),
                 "--server.port", str(port),
                 "--server.headless", "true",
                 "--theme.base", "dark"],
                check=True,
            )
        except KeyboardInterrupt:
            print("\n[nqcockpit] Interface arrêtée.")
        return 0

    if action == "coaching-ui":
        import subprocess  # noqa: S603
        import sys
        from pathlib import Path

        port = getattr(args, "port", 8501)
        page_path = Path(__file__).parent / "ui" / "app.py"
        print(f"[nqcockpit] Terminal Multipage Streamlit sur http://localhost:{port}")
        try:
            subprocess.run(  # noqa: S603
                [
                    sys.executable, "-m", "streamlit", "run", str(page_path),
                    "--server.port", str(port),
                    "--server.headless", "true",
                    "--theme.base", "dark",
                ],
                check=True,
            )
        except KeyboardInterrupt:
            print("\n[nqcockpit] Interface arrêtée.")
        return 0

    if action == "backup":
        from nqcockpit.journal.backup import create_journal_backup

        backup_dir = getattr(args, "dir", None)
        retention = getattr(args, "retention_days", None)

        res = create_journal_backup(
            backup_dir=backup_dir,
            retention_days=retention,
            config=config,
        )

        sep = "=" * 65
        print(f"\n{sep}")
        print("  SAUVEGARDE DU JOURNAL SQLITE")
        print(sep)
        if res.is_success:
            print("  Statut          : ✅ OK (Sauvegarde réussie)")
            print(f"  Fichier         : {res.backup_path}")
            size_kb = res.file_size_bytes / 1024.0
            print(f"  Taille          : {size_kb:.1f} KB ({res.file_size_bytes} octets)")
            print(f"  Intégrité       : {res.integrity_result} (PRAGMA integrity_check validé)")
            mode_desc = (
                "Remplacement idempotent de la sauvegarde du jour"
                if res.is_idempotent_overwrite
                else "Nouvelle sauvegarde créée"
            )
            print(f"  Mode            : {mode_desc}")
            eff_retention = (
                retention if retention is not None else config.data.backup_retention_days
            )
            print(f"  Rétention       : {eff_retention} jours")
            print(
                f"  Purge ancienne  : {len(res.deleted_old_backups)} sauvegarde(s) supprimée(s)"
            )
            for old in res.deleted_old_backups:
                print(f"    - {old.name}")
            print(sep + "\n")
            return 0
        else:
            print("  Statut          : ⚠️ DÉGRADÉ (Échec de la sauvegarde)")
            print(f"  Fichier cible   : {res.backup_path}")
            print(f"  Intégrité       : {res.integrity_result}")
            if res.error_message:
                print(f"  Erreur          : {res.error_message}")
            print("  Rétention       : Aucune purge effectuée en état dégradé")
            print(sep + "\n")
            return 1

    conn = init_journal_db(config.data.db_path)

    if action == "daily":
        target = getattr(args, "date", None) or str(datetime.now(tz_ny).date())
        trades = load_trades(conn, session_date=target)
        stats = compute_daily_stats(target, trades, config)
        sep = "=" * 65
        print(f"\n{sep}")
        print(f"  JOURNAL DU JOUR — {target}")
        print(sep)
        print(f"  Trades : {stats.n_trades}  |  Wins {stats.n_wins} / Pertes {stats.n_losses}")
        print(f"  R total : {stats.r_total:+.3f}R  |  Conformité : {stats.compliance_rate:.0%}")
        if stats.limit_hit:
            print(f"  *** LIMITE JOURNALIÈRE ATTEINTE ({stats.r_total:+.3f}R) ***")

        if trades:
            days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            print("\n  DÉTAIL DES TRADES ENREGISTRÉS :")
            for i, t in enumerate(trades, 1):
                day_name = days[t.day_of_week] if 0 <= t.day_of_week <= 6 else "Inconnu"
                w_str = t.window_name or "sans fenêtre"
                print(
                    f"  [{i}] ID: {t.trade_id[:8]} | "
                    f"{t.instrument} {t.direction.value} ({w_str})"
                )
                print(
                    f"      Prix: Entrée {t.entry_price:.2f} | "
                    f"Stop {t.stop_price:.2f} | Sortie {t.exit_price:.2f}"
                )
                setup_str = t.setup_tag or "N/A"
                print(
                    f"      Résultat: {t.r_realized:+.3f}R ({t.outcome.value}) | "
                    f"Setup: {setup_str}"
                )
                print(
                    f"      Contexte auto-taggé: Gamma={t.gamma_regime.value} | "
                    f"Vol={t.vol_regime.value} | Jour={day_name}"
                )
                print(f"      Événement: {t.event_risk_label or 'Aucun événement'}")

        if stats.violations:
            print(f"\n  VIOLATIONS DÉTECTÉES ({len(stats.violations)}) :")
            for v in stats.violations:
                print(f"    [{v.violation.value}] {v.detail}")
        if stats.tilt_alerts:
            print(f"\n  ALERTES TILT ({len(stats.tilt_alerts)}) :")
            for a in stats.tilt_alerts:
                print(f"    {a.reason}")
        print(sep + "\n")
        return 0

    if action == "stats" or action is None:
        all_trades = load_trades(conn)
        stats = compute_performance_stats(
            all_trades, min_trades=config.validation.min_sessions
        )
        now_str = (
            stats.computed_at.strftime("%Y-%m-%d %H:%M UTC")
            if stats.computed_at else "—"
        )
        sep = "=" * 65
        print(f"\n{sep}")
        print(f"  PERFORMANCE GLOBALE — {stats.n_trades} trades — calculé {now_str}")
        print(sep)
        if not stats.sample_sufficient:
            print(
                f"  ⚠ Échantillon insuffisant : {stats.n_trades}/{stats.min_trades_required} trades"
            )
            print("    Espérance, drawdown, profit factor : non calculés.")
        wr_str = f"{stats.win_rate:.1%}" if stats.win_rate is not None else "—"
        print(f"  Win rate : {wr_str}")
        if stats.win_rate_ci_low is not None:
            print(
                f"    IC 95% Wilson : [{stats.win_rate_ci_low:.1%}, {stats.win_rate_ci_high:.1%}]"
            )
        if stats.sample_sufficient:
            print(f"  Espérance  : {stats.expectancy_r:+.4f}R")
            if stats.expectancy_ci_low is not None:
                print(
                    f"    IC 95%  : [{stats.expectancy_ci_low:+.4f}, "
                    f"{stats.expectancy_ci_high:+.4f}]"
                )
            pf_str = f"{stats.profit_factor:.2f}" if stats.profit_factor else "N/A"
            print(f"  Profit factor : {pf_str}")
            print(f"  Max drawdown (R) : -{stats.max_drawdown_r:.3f}R")
            print(f"  Max série pertes : {stats.max_loss_streak}")
        comp_str = f"{stats.compliance_rate:.0%}" if stats.compliance_rate else "—"
        print(f"  Conformité : {comp_str}")
        if stats.expectancy_r_compliant is not None:
            print(f"  Espérance conformes     : {stats.expectancy_r_compliant:+.4f}R")
        if stats.expectancy_r_noncompliant is not None:
            print(f"  Espérance non-conformes : {stats.expectancy_r_noncompliant:+.4f}R")
        print(sep + "\n")
        return 0

    if action == "coaching":
        all_trades = load_trades(conn)
        period = getattr(args, "period", "hebdo")
        label = getattr(args, "label", "") or "manuel"
        report = generate_coaching_report(all_trades, period=period,
                                          period_label=label, config=config)
        sep = "=" * 65
        print(f"\n{sep}")
        print(f"  COACHING {period.upper()} — {label}")
        print(f"  Généré : {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
        print(sep)
        if report.insufficient_data:
            n_done = report.stats.n_trades if report.stats else 0
            n_req = config.validation.min_sessions
            print(f"  ⚠ Données insuffisantes : {n_done}/{n_req} trades")
        print("\n  TOP 3 FUITES :")
        for i, leak in enumerate(report.top_leaks, 1):
            print(f"    {i}. {leak}")
        print(f"\n  RÈGLE À RENFORCER : {report.rule_to_reinforce}")
        print(f"\n  FORCE À CONSERVER : {report.strength_to_keep}")
        print("\n  OBJECTIFS :")
        for goal in report.measurable_goals:
            print(f"    - {goal}")
        print(sep + "\n")
        return 0

    if action == "import-csv":
        from nqcockpit.journal.importer import import_trades_from_csv

        csv_path = getattr(args, "csv_path", "")
        summary = import_trades_from_csv(csv_path, conn, config)
        sep = "=" * 65
        print(f"\n{sep}")
        print(f"  RÉSUMÉ D'IMPORT CSV — {csv_path}")
        print(sep)
        print(f"  Lignes lues      : {summary.total_rows}")
        print(f"  Lignes importées : {summary.imported}")
        print(f"  Doublons ignorés : {summary.duplicates}")
        print(f"  Lignes rejetées  : {summary.rejected}")
        if summary.missing_optional_columns:
            print("\n  Colonnes optionnelles absentes (valeurs par défaut appliquées) :")
            for col in summary.missing_optional_columns:
                print(f"    - {col}")
        if summary.errors:
            print("\n  Erreurs / Alertes :")
            for err in summary.errors:
                print(f"    - {err}")
        print(sep + "\n")
        return 0 if summary.is_success else 1

    if action == "attach-screenshot":
        from pathlib import Path

        from nqcockpit.journal.store import get_trade, update_trade_screenshot

        trade_id = getattr(args, "trade_id", "")
        img_path = getattr(args, "image_path", "")

        p = Path(img_path)
        if not p.is_file():
            print(f"[ERREUR] Le fichier image est introuvable : {img_path}")
            return 1

        trade = get_trade(conn, trade_id)
        if not trade:
            print(f"[ERREUR] Aucun trade trouvé avec l'identifiant : {trade_id}")
            return 1

        resolved_path = str(p.resolve())
        updated = update_trade_screenshot(conn, trade_id, resolved_path)
        if updated:
            print(f"[SUCCÈS] Capture attachée au trade {trade_id} : {resolved_path}")
            return 0
        print(f"[ERREUR] Échec de mise à jour du trade {trade_id}")
        return 1

    if action == "report":
        from nqcockpit.journal.reports import run_period_report_cli

        period = getattr(args, "period", "week")
        date_str = getattr(args, "date", None)
        out_dir = getattr(args, "output_dir", "reports/journal")

        try:
            res = run_period_report_cli(
                conn, period=period, date_str=date_str, output_dir=out_dir, config=config
            )
        except ValueError as exc:
            print(f"[ERREUR] Paramètre invalide : {exc}")
            return 1

        sep = "=" * 65
        print(f"\n{sep}")
        period_name = "HEBDOMADAIRE" if res.period == "week" else "MENSUEL"
        print(f"  RAPPORT DE PERFORMANCE {period_name} — {res.period_label}")
        print(sep)
        print(f"  Période observée : du {res.start_date} au {res.end_date}")
        print(f"  Fichier généré   : {res.report_path}")
        print(f"  Trades analysés  : {res.n_trades}")
        print(f"  R cumulé         : {res.r_total:+.4f}R")
        status_sig = (
            "✅ Échantillon représentatif"
            if res.sample_sufficient
            else "⚠️ Échantillon insuffisant (descriptif uniquement)"
        )
        print(f"  Significativité  : {status_sig}")
        status_prev = (
            "Données comparées avec succès"
            if res.has_prev_data
            else "Non disponible (signalée explicitement)"
        )
        print(f"  Période précéd.  : {status_prev}")
        print(sep + "\n")
        return 0

    print(
        f"[nqcockpit journal] Action inconnue : {action!r}. "
        "Essayez : stats, daily, coaching, ui, coaching-ui, import-csv, "
        "attach-screenshot, backup, report."
    )
    return 1


def _handle_discipline(args: Any) -> int:
    """Porte de discipline live et gestionnaire de risque (P09 réel)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from nqcockpit.config import load_config
    from nqcockpit.discipline.engine import evaluate_checklist, evaluate_session_state
    from nqcockpit.discipline.models import PreTradeChecklist
    from nqcockpit.discipline.risk import compute_position_size
    from nqcockpit.journal.store import init_journal_db, load_trades

    config = load_config()
    action = getattr(args, "discipline_action", None)

    if action == "ui":
        import subprocess  # noqa: S603
        import sys
        from pathlib import Path

        port = getattr(args, "port", 8501)
        page_path = Path(__file__).parent / "ui" / "app.py"
        print(f"[nqcockpit] Terminal Multipage Streamlit sur http://localhost:{port}")
        try:
            subprocess.run(  # noqa: S603
                [
                    sys.executable, "-m", "streamlit", "run", str(page_path),
                    "--server.port", str(port),
                    "--server.headless", "true",
                    "--theme.base", "dark",
                ],
                check=True,
            )
        except KeyboardInterrupt:
            print("\n[nqcockpit] Interface arrêtée.")
        return 0

    conn = init_journal_db(config.data.db_path)
    trades = load_trades(conn)
    now_utc = datetime.now(timezone.utc)
    state = evaluate_session_state(trades, now_utc, config)
    sep = "=" * 65

    if action == "status" or action is None:
        tz_algiers = ZoneInfo(config.timezones.display)
        time_alg = now_utc.astimezone(tz_algiers).strftime("%H:%M:%S")
        print(f"\n{sep}")
        print(f"  ÉTAT VIVANT DE LA SÉANCE — {time_alg} (Alger)")
        print(sep)
        stat_color = "PRÊT (GO)" if state.can_trade else f"BLOQUÉ ({state.status.value})"
        print(f"  Statut global    : {stat_color}")
        print(f"  Fenêtre active   : {state.current_window_name or 'Aucune'}")
        print(f"  Trades restants  : {state.trades_remaining} / {state.max_trades_allowed}")
        print(f"  R réalisé jour   : {state.r_realized_today:+.2f}R")
        if state.cooldown_remaining_seconds > 0:
            print(f"  Compte à rebours : {state.cooldown_countdown_str} restantes")
        if state.lock_reasons:
            print("\n  Motifs de blocage actifs :")
            for r in state.lock_reasons:
                print(f"    - {r}")
        print(sep + "\n")
        return 0

    if action == "sizing":
        acc = getattr(args, "account", 50000.0)
        risk_pct = getattr(args, "risk_pct", 0.5)
        stop_pts = getattr(args, "stop_pts", 30.0)
        inst = getattr(args, "instrument", "MNQ")
        prop_loss = getattr(args, "prop_max_loss", None)
        prop_dd = getattr(args, "prop_trailing_dd", None)

        res = compute_position_size(
            account_size=acc,
            risk_pct=risk_pct,
            stop_points=stop_pts,
            instrument=inst,
            config=config,
            prop_max_daily_loss=prop_loss,
            prop_trailing_dd=prop_dd,
        )
        print(f"\n{sep}")
        print(f"  DIMENSIONNEMENT DE POSITION — {inst}")
        print(sep)
        print(f"  Capital compte   : {res.account_size:.2f} $ | Risque max : {res.risk_pct:.2f}%")
        print(
            f"  Stop loss        : {res.stop_points:.2f} pts | "
            f"Valeur pt : {res.point_value:.1f} $/pt"
        )
        print(f"  Budget alloué    : {res.risk_budget_dollars:.2f} $")
        print(f"  Risque / contrat : {res.risk_per_contract_dollars:.2f} $")
        print(f"  --> CONTRATS     : {res.contracts} contrat(s) (arrondi inférieur)")
        print(f"  --> Risque réel  : {res.actual_risk_dollars:.2f} $ ({res.actual_risk_pct:.2f}%)")
        if res.warning:
            print(f"  ⚠ Avertissement  : {res.warning}")
        if res.prop_firm_warning:
            print(f"  🛑 Prop Firm     : {res.prop_firm_warning}")
        print(sep + "\n")
        return 0

    if action == "check":
        plan = getattr(args, "plan", "").strip()
        p08 = bool(getattr(args, "p08_reviewed", False))
        acc = getattr(args, "account", None) or (config.risk.account_size or 50000.0)
        risk_pct = getattr(args, "risk_pct", None) or config.risk.risk_per_trade_pct
        stop_pts = getattr(args, "stop_pts", 30.0)
        inst = getattr(args, "instrument", "MNQ")

        sizing_res = compute_position_size(
            account_size=acc,
            risk_pct=risk_pct,
            stop_points=stop_pts,
            instrument=inst,
            config=config,
        )

        chk_data = PreTradeChecklist(
            p08_reviewed=p08,
            trading_plan=plan,
            sizing_result=sizing_res,
            event_risk_tier1_red=False,
        )
        res = evaluate_checklist(chk_data, state, config)

        print(f"\n{sep}")
        print("  CHECKLIST PRÉ-TRADE INTERACTIVE")
        print(sep)
        for item, ok in res.items_status.items():
            mark = "✅ OK" if ok else "❌ ÉCHEC"
            print(f"  [{mark}] {item}")
        print(sep)
        if res.passed:
            print("  🟢 VERDICT FINAL : GO — TRADING AUTORISÉ")
            act_risk = sizing_res.actual_risk_dollars
            print(f"     Sizing : {sizing_res.contracts}x {inst} ({act_risk:.2f} $)")
        else:
            print("  🔴 VERDICT FINAL : STOP — TRADING STRICTEMENT INTERDIT")
            print("  Motifs de blocage :")
            for b in res.blocking_reasons:
                print(f"    - {b}")
        print(sep + "\n")
        return 0

    print(
        f"[nqcockpit discipline] Action inconnue : {action!r}. "
        "Essayez : status, check, sizing, ui."
    )
    return 1


def _handle_run(args: Any) -> int:
    """Démarre le planificateur de tâches de fond et l'UI Streamlit unifiée (P13)."""
    import time

    from nqcockpit.levels.scheduler import LevelsScheduler

    print("[nqcockpit] Commande 'run' invoquée (planificateur / exploitation).")
    if getattr(args, "dry_run", False):
        print(
            "[nqcockpit] Commande 'run --dry-run' : validation de la configuration et des tâches."
        )
        sched = LevelsScheduler()
        print("[nqcockpit] Planificateur instancié sans erreur (dry-run validé).")
        return 0

    print("[nqcockpit] Démarrage du planificateur de niveaux NQ...")
    sched = LevelsScheduler()
    sched.start()
    print("[nqcockpit] Planificateur actif (cron en America/New_York).")

    if getattr(args, "no_ui", False):
        print("[nqcockpit] Mode sans interface (--no-ui). En écoute (Ctrl+C pour arrêter)...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[nqcockpit] Arrêt demandé.")
        finally:
            sched.stop()
            print("[nqcockpit] Planificateur arrêté.")
        return 0

    try:
        return _handle_ui(args)
    finally:
        print("[nqcockpit] Arrêt du planificateur de niveaux...")
        sched.stop()
        print("[nqcockpit] Planificateur arrêté.")


def _handle_ui(args: Any) -> int:
    """Lance l'interface Streamlit consolidée multipage (P13)."""
    import subprocess  # noqa: S603
    import sys
    from pathlib import Path

    port = getattr(args, "port", 8501)
    page_path = Path(__file__).parent / "ui" / "app.py"

    print(f"[nqcockpit] Lancement du terminal multipage Streamlit sur http://localhost:{port}")
    print(f"[nqcockpit] Application : {page_path}")
    print("[nqcockpit] Ctrl+C pour arrêter.")

    try:
        subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(page_path),
                "--server.port",
                str(port),
                "--server.headless",
                "true",
                "--theme.base",
                "dark",
            ],
            check=True,
        )
    except KeyboardInterrupt:
        print("\n[nqcockpit] Interface arrêtée.")
    return 0


def _handle_briefing(args: Any) -> int:
    """Génère le briefing pré-séance et le diffuse optionnellement (P12)."""
    from nqcockpit.briefing.engine import generate_briefing

    action = getattr(args, "briefing_action", None)
    if action == "generate" or action is None:
        dry_run = getattr(args, "dry_run", False)
        no_gemini = getattr(args, "no_gemini", False)
        no_telegram = getattr(args, "no_telegram", False)
        out_dir = getattr(args, "output_dir", "reports/briefings")

        briefing = generate_briefing(
            use_gemini=not no_gemini,
            use_telegram=not no_telegram,
            dry_run=dry_run,
            output_dir=out_dir,
        )

        sep = "=" * 75
        print("\n" + sep)
        print(f"  NQ COCKPIT — BRIEFING PRÉ-SÉANCE ({briefing.session_date_ny})")
        print(f"  Horodatage (Alger) : {briefing.timestamp_algiers_str}")
        print(f"  Statut Intégrité   : {briefing.status}")
        if briefing.status_warnings:
            print("  Avertissements :")
            for w in briefing.status_warnings:
                print(f"    - {w}")
        if briefing.output_path:
            print(f"  Fichier généré     : {briefing.output_path}")
        print(sep + "\n")
        print(briefing.markdown_briefing)
        print("\n" + sep + "\n")
        return 0

    print(
        f"[nqcockpit briefing] Action inconnue : {action!r}. "
        "Essayez : generate."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
