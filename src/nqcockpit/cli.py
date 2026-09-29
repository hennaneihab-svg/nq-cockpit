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
        from nqcockpit.data.db import get_bars, get_db_connection
        from nqcockpit.data.fetcher import DataFetcher
        from nqcockpit.levels.engine import LevelsEngine

        print("[nqcockpit] Commande 'snapshot' invoquée (niveaux gamma)...")
        chain = fetch_cboe_options_chain()

        conn = get_db_connection()
        nq_bars = get_bars(conn, "NQ=F", "1m", limit=100)
        ndx_bars = get_bars(conn, "^NDX", "1m", limit=100)
        conn.close()

        # Si la base ne contient pas de barres, récupération à la volée
        if not nq_bars or not ndx_bars:
            fetcher = DataFetcher()
            if not nq_bars:
                nq_bars = fetcher.fetch_yahoo_bars("NQ=F", interval="1m", period="1d").bars
            if not ndx_bars:
                ndx_bars = fetcher.fetch_yahoo_bars("^NDX", interval="1m", period="1d").bars

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
        print(f"  Spot NDX             : {snap.spot_ndx:,.2f} pts")
        print(f"  Spot NQ              : {snap.spot_nq:,.2f} pts")

        # --- BLOC BASE (Tâche 1) ---
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
            print(f"  Compensation retard  : {snap.basis_delay_compensation_note}")
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

        # --- NIVEAUX ---
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
        cw_ndx = f"{snap.call_wall_ndx:,.2f}" if snap.call_wall_ndx else "N/A"
        cw_nq = f"{snap.call_wall_nq:,.2f}" if snap.call_wall_nq else "N/A"
        print(f"  Call Wall (Résist.)  : NDX {cw_ndx} | NQ {cw_nq}")
        pw_ndx = f"{snap.put_wall_ndx:,.2f}" if snap.put_wall_ndx else "N/A"
        pw_nq = f"{snap.put_wall_nq:,.2f}" if snap.put_wall_nq else "N/A"
        print(f"  Put Wall (Support)   : NDX {pw_ndx} | NQ {pw_nq}")
        if snap.zero_dte_call_wall_nq or snap.zero_dte_put_wall_nq:
            z_cw = f"{snap.zero_dte_call_wall_nq:,.2f}" if snap.zero_dte_call_wall_nq else "N/A"
            z_pw = f"{snap.zero_dte_put_wall_nq:,.2f}" if snap.zero_dte_put_wall_nq else "N/A"
            z_gex = f"{snap.zero_dte_net_gex / 1e6:+,.2f} M$" if snap.zero_dte_net_gex else "N/A"
            print(f"  0DTE Call/Put Wall   : NQ {z_cw} / {z_pw} (Net GEX : {z_gex})")

        # --- EXPECTED MOVE (Tâche 3) ---
        if snap.expected_move:
            em = snap.expected_move
            print("-" * 70)
            exp_str = em.expiry.strftime("%Y-%m-%d (%A)") if em.expiry else "N/A"
            em_age = f"{em.data_age_minutes:.1f} min" if em.data_age_minutes is not None else "N/A"
            print(f"  EXPECTED MOVE — échéance : {exp_str} | age données : {em_age}")
            print(f"  IV ATM               : {em.iv_atm * 100:.2f}%")
            print(f"  Durée                : {em.days_to_expiry:.2f} j (bourse)")
            # Méthode IV
            iv_pts = em.iv_move_nq if em.iv_move_nq is not None else em.formula_move
            iv_lo = em.iv_lower_nq if em.iv_lower_nq is not None else (snap.spot_nq - iv_pts)
            iv_hi = em.iv_upper_nq if em.iv_upper_nq is not None else (snap.spot_nq + iv_pts)
            print(f"  Méthode IV           : +/- {iv_pts:.1f} pts NQ")
            print(f"    Bornes IV          : [{iv_lo:,.2f} .. {iv_hi:,.2f}]")
            print("    Formule            : spot x IV x sqrt(jours/252)")
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
                coh_flag = "OK" if em.is_coherent else "DEGRADE (>25%)"
                print(
                    f"  Ecart IV vs Straddle : {em.discrepancy_pct:.1f}% [{coh_flag}]"
                )
            if em.status_explanation:
                print(f"  [!] {em.status_explanation}")

        if snap.max_pain_nq:
            print(
                f"  Max Pain             : NDX {snap.max_pain_ndx:,.2f} "
                f"| NQ {snap.max_pain_nq:,.2f}"
            )

        # --- DIAGNOSTIC 1c (Tâche 2) ---
        d = snap.diagnostic_1c
        if d:
            print("-" * 70)
            print(f"  DIAGNOSTIC 1c — Séance {d.session_date.isoformat()}")
            print("  1. Cible             : 16:00 clôture actions")
            print(f"       ET              : {d.target_time_et}")
            print(f"       Alger           : {d.target_time_algiers}")
            print(f"  2. Barre NQ         : {'TROUVEE' if d.nq_candidate_found else 'ABSENTE'}")
            if d.nq_candidate_found:
                print(f"       Close           : {d.nq_candidate_close:,.2f} pts")
                print(f"       Horodatage ET   : {d.nq_candidate_time_et}")
                print(f"       Horodatage Alger: {d.nq_candidate_time_algiers}")
            print(f"       Nb barres du jour: {d.nq_bars_count_day}")
            if d.nq_first_bar_time:
                print(f"       Première barre  : {d.nq_first_bar_time}")
                print(f"       Dernière barre  : {d.nq_last_bar_time}")
            print(f"  3. Cotation NDX     : {'TROUVEE' if d.ndx_candidate_found else 'ABSENTE'}")
            if d.ndx_candidate_found:
                print(f"       Spot            : {d.ndx_candidate_spot:,.2f} pts")
                print(f"       Horodatage ET   : {d.ndx_candidate_time_et}")
                print(f"       Horodatage Alger: {d.ndx_candidate_time_algiers}")
            if d.delta_t_minutes is not None:
                print(
                    f"  4. Delta-t          : {d.delta_t_minutes:.2f} min "
                    f"(tol. {d.tolerance_minutes:.1f} min)"
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
