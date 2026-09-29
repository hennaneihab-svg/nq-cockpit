"""Command Line Interface for NQ Cockpit."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence


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
    subparsers.add_parser(
        "ui",
        help="Lance l'interface utilisateur Streamlit",
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "run":
        print("[nqcockpit] Commande 'run' invoquée (planificateur / exploitation).")
        return 0
    elif args.subcommand == "check-sources":
        from nqcockpit.sources.health import run_all_checks

        print("[nqcockpit] Commande 'check-sources' invoquée (santé des sources)...")
        report = run_all_checks()
        print("\n" + report.render_console_table() + "\n")
        report_path = report.save_json("reports/source_check.json")
        print(f"[nqcockpit] Rapport complet enregistré dans {report_path}")
        return 0
    elif args.subcommand == "snapshot":

        from nqcockpit.data.cboe import fetch_cboe_options_chain
        from nqcockpit.data.db import get_bars, get_db_connection, insert_bars
        from nqcockpit.data.fetcher import DataFetcher
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
        age_val = snap.data_age_minutes
        age_str = f"{age_val:.1f} min" if age_val is not None else "inconnu"

        print("\n" + "=" * 70)
        print("  NQ COCKPIT — SNAPSHOT DE NIVEAUX & RÉGIME GAMMA")
        print(f"  Horodatage : {snap_ny} | {snap_alg}")
        print(f"  Age données : {age_str} | Statut : {snap.status.value}")
        print("=" * 70)

        # --- BLOC CBOE (Tâche 2 : RECHARGEMENT PROUVÉ) ---
        print("-" * 70)
        print("  SOURCE CBOE (RECHARGEMENT PROUVÉ)")
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
        reloaded_str = "OUI (téléchargement direct forcé)" if snap.cboe_reloaded else "NON (cache)"
        print(f"  Chaîne rechargée     : {reloaded_str}")
        if snap.cboe_age_stats:
            excl_zero = snap.cboe_age_stats.get("excluded_zero_quotes", 0)
            n_active = snap.cboe_age_stats.get("count", 0)
            print(f"  Options actives (±3%): {n_active} contrats (bid>0, ask>0)")
            print(f"  Options exclues      : {excl_zero} contrats sans cotation (bid=0 ou ask=0)")
        print(f"  Statut source CBOE   : {snap.status.value}")

        # --- SPOT NQ & NDX (Tâche 1 : ÂGE RÉEL DU SPOT NQ) ---
        print("-" * 70)
        print(f"  Spot NDX             : {snap.spot_ndx:,.2f} pts")
        nq_stale_flag = " [SPOT NQ PÉRIMÉ - DÉGRADÉ]" if snap.spot_nq_is_stale else " [OK]"
        nq_age_s = (
            f"{snap.spot_nq_age_minutes:.1f} min"
            if snap.spot_nq_age_minutes is not None
            else "inconnu"
        )
        print(
            f"  Spot NQ (observé)    : {snap.spot_nq:,.2f} pts "
            f"(âge réel : {nq_age_s}){nq_stale_flag}"
        )
        if snap.spot_nq_time_utc:
            nq_bar_et = snap.spot_nq_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
            nq_bar_alg = snap.spot_nq_time_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            print(f"    Horodatage spot NQ : {nq_bar_et} | {nq_bar_alg}")

        # --- BLOC BASE ---
        print("-" * 70)
        print("  BLOC BASE")
        # NQ timestamp
        if snap.basis_nq_time_utc:
            nq_ts_et = snap.basis_nq_time_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S ET")
            nq_ts_alg = snap.basis_nq_time_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            print(f"  NQ barre utilisée    : close={snap.basis_nq_close:,.2f} pts")
            print(f"    Horodatage NQ      : {nq_ts_et} | {nq_ts_alg}")
        else:
            print("  NQ barre utilisée    : N/A")
        # NDX/CBOE timestamp
        if snap.basis_ndx_time_utc:
            ndx_ts_et = snap.basis_ndx_time_utc.astimezone(et_tz).strftime(
                "%Y-%m-%d %H:%M:%S ET"
            )
            ndx_ts_alg = snap.basis_ndx_time_utc.astimezone(alg_tz).strftime(
                "%Y-%m-%d %H:%M:%S (Alger)"
            )
            print(f"  NDX/CBOE utilisé     : spot={snap.basis_ndx_spot:,.2f} pts")
            print(f"    Horodatage NDX     : {ndx_ts_et} | {ndx_ts_alg}")
        else:
            print("  NDX/CBOE utilisé     : N/A")
        # Delta-t et tolérance
        if snap.basis_delta_t_minutes is not None:
            aligned_flag = "OK" if snap.basis_is_aligned else "NON ALIGNEE [DEGRADE]"
            print(
                f"  Delta-t NQ/NDX       : {snap.basis_delta_t_minutes:.2f} min "
                f"(tol. {snap.basis_tolerance_minutes:.1f} min) [{aligned_flag}]"
            )
        print(f"  Formule base         : {snap.basis_formula}")
        print(f"  Méthode retenue      : {snap.basis_method}")
        if snap.basis_delay_compensation_note:
            print(f"  Origine données      : {snap.basis_delay_compensation_note}")
        # Valeur de la base et parité
        if snap.synthetic_basis is not None:
            p_diff = abs(snap.basis - snap.synthetic_basis)
            print(
                f"  Base empirique       : {snap.basis:+,.2f} pts [{snap.basis_status.value}]"
            )
            print(
                f"  Base parité          : {snap.synthetic_basis:+,.2f} pts "
                f"(écart : {p_diff:,.2f} pts)"
            )
        else:
            print(f"  Base future-spot     : {snap.basis:+,.2f} pts [{snap.basis_status.value}]")

        # --- NIVEAUX & MURS UTILES (Tâche 3) ---
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

        # Murs utiles (dans fenêtre ±wall_window_pct, e.g. ±10 %)
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

        if snap.zero_dte_call_wall_nq or snap.zero_dte_put_wall_nq:
            z_cw = f"{snap.zero_dte_call_wall_nq:,.2f}" if snap.zero_dte_call_wall_nq else "N/A"
            z_pw = f"{snap.zero_dte_put_wall_nq:,.2f}" if snap.zero_dte_put_wall_nq else "N/A"
            z_gex = f"{snap.zero_dte_net_gex / 1e6:+,.2f} M$" if snap.zero_dte_net_gex else "N/A"
            print(f"  0DTE Call/Put Wall   : NQ {z_cw} / {z_pw} (Net GEX : {z_gex})")

        # --- EXPECTED MOVE (Tâche 4 : DÉCOMPOSITION EXPLICITE DES SPOTS) ---
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
            print(f"  Durée                : {em.days_to_expiry:.2f} j (bourse)")

            # Méthode IV
            iv_pts = em.iv_move_nq if em.iv_move_nq is not None else em.formula_move
            iv_lo = em.iv_lower_nq if em.iv_lower_nq is not None else (snap.spot_nq - iv_pts)
            iv_hi = em.iv_upper_nq if em.iv_upper_nq is not None else (snap.spot_nq + iv_pts)
            print(f"  Méthode IV           : +/- {iv_pts:.1f} pts NQ")
            print(f"    Bornes IV          : [{iv_lo:,.2f} .. {iv_hi:,.2f}]")

            # Tâche 4 : Décomposition explicite des spots de référence
            print("    Décomposition des spots :")
            print(f"      - Spot NDX formule             : {em.spot_ndx_used:,.2f} pts")
            print(f"      - Spot NQ observé (centrage)   : {em.spot_nq_observed:,.2f} pts")
            print(
                f"      - NDX converti (NDX + base)    : {em.spot_nq_converted:,.2f} pts "
                f"(base {snap.basis:+,.2f} pts)"
            )
            spread_sign = f"{em.spread_nq_vs_converted:+,.2f}"
            print(f"      - Écart NQ observé vs converti : {spread_sign} pts")
            print("    Formule            : spot_ndx x IV x sqrt(j/252) -> [spot_nq +/- move]")

            # Méthode Straddle
            if em.straddle_move_nq is not None:
                s_lo = em.straddle_lower_nq if em.straddle_lower_nq is not None else "N/A"
                s_hi = em.straddle_upper_nq if em.straddle_upper_nq is not None else "N/A"
                s_lo_s = f"{s_lo:,.2f}" if isinstance(s_lo, float) else s_lo
                s_hi_s = f"{s_hi:,.2f}" if isinstance(s_hi, float) else s_hi
                print(f"  Méthode Straddle     : +/- {em.straddle_move_nq:.1f} pts NQ")
                print(f"    Bornes Straddle    : [{s_lo_s} .. {s_hi_s}]")
                print("    Formule            : (C_ATM_mid + P_ATM_mid) via base")
            else:
                print("  Méthode Straddle     : N/A (bid/ask ATM manquants)")
            if em.discrepancy_pct is not None:
                coh_flag = "OK" if em.is_coherent else "DÉGRADÉ (>25%)"
                print(
                    f"  Écart IV vs Straddle : {em.discrepancy_pct:.1f}% [{coh_flag}]"
                )
            if em.status_explanation:
                print(f"  [!] {em.status_explanation}")

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
        return 0
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
