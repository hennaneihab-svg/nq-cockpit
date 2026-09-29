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
        print("[nqcockpit] Commande 'snapshot' invoquée (snapshot niveaux / GEX).")
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
        else:
            parser.parse_args(["data", "--help"])
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
