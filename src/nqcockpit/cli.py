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
        from zoneinfo import ZoneInfo

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
        et_tz = ZoneInfo("America/New_York")
        snap_ny = snap.timestamp_utc.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S EDT")
        age_val = snap.data_age_minutes
        age_str = f"{age_val:.1f} min" if age_val is not None else "inconnu"

        print("\n" + "=" * 70)
        print("  NQ COCKPIT — SNAPSHOT DE NIVEAUX & RÉGIME GAMMA")
        print(f"  Horodatage : {snap_ny} (âge : {age_str}) | Statut : {snap.status.value}")
        print("=" * 70)
        print(f"  Spot NDX             : {snap.spot_ndx:,.2f} pts")
        print(f"  Spot NQ              : {snap.spot_nq:,.2f} pts")
        if snap.synthetic_basis is not None:
            p_diff = abs(snap.basis - snap.synthetic_basis)
            p_str = (
                f" | Base parité : {snap.synthetic_basis:+,.2f} pts (écart : {p_diff:,.2f} pts)"
            )
        else:
            p_str = " | Base parité : N/A"

        basis_line = (
            f"  Base future-spot     : {snap.basis:+,.2f} pts ({snap.basis_label}) "
            f"[{snap.basis_status.value}]{p_str}"
        )
        print(basis_line)
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

        if snap.expected_move:
            em = snap.expected_move
            straddle_str = f"{em.straddle_move:.1f} pts" if em.straddle_move else "N/A"
            em_line = (
                f"  Expected Move 1-sigma: +/- {em.formula_move:.1f} pts "
                f"(Straddle ATM : {straddle_str})"
            )
            print(em_line)
            bounds_line = (
                f"  Bornes NQ attendues  : [{em.lower_bound_nq:,.2f} .. {em.upper_bound_nq:,.2f}]"
            )
            print(bounds_line)

        if snap.max_pain_nq:
            mp_line = (
                f"  Max Pain             : NDX {snap.max_pain_ndx:,.2f} "
                f"| NQ {snap.max_pain_nq:,.2f}"
            )
            print(mp_line)

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
