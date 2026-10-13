"""Point d'entrée.

  python main.py import-csv data/historique_initial.csv   # importer un historique CSV
  python main.py collect                                   # récupérer les nouvelles parties (API Riot)
  python main.py build                                     # générer le site dans site/
  python main.py update                                    # collect + build (utilisé chaque semaine)

Options IA (chaque texte est généré une seule fois puis conservé dans data/ai/) :
  --ia-sessions nouvelles|derniere|toutes|aucune   (défaut : nouvelles = dernière soirée si pas encore faite)
  --ia-global                                      regénère le bilan global (sinon jamais automatique)
"""
import argparse
import os
import sys

import yaml

from coach import importer, site, store
from coach.riot import RiotError, collect


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yaml")
    common.add_argument("--ia-sessions", default=os.environ.get("IA_SESSIONS") or "nouvelles",
                        choices=["nouvelles", "derniere", "toutes", "aucune"],
                        help="débriefs IA de session à générer (défaut : nouvelles)")
    common.add_argument("--ia-global", action="store_true",
                        default=os.environ.get("IA_GLOBAL", "").lower() == "true",
                        help="regénérer le bilan IA global (payant, à la demande)")
    parser = argparse.ArgumentParser(description="Outil de coaching LoL", parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import-csv", help="importer un historique CSV", parents=[common])
    p_imp.add_argument("path")
    sub.add_parser("collect", help="récupérer les nouvelles parties via l'API Riot", parents=[common])
    sub.add_parser("build", help="générer le site", parents=[common])
    sub.add_parser("update", help="collect puis build", parents=[common])
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if args.cmd == "import-csv":
        importer.import_csv(args.path)
        return

    champs = store.Champions()
    warning = None
    if args.cmd in ("collect", "update"):
        try:
            collect(cfg, os.environ.get("RIOT_API_KEY"), champs)
        except RiotError as exc:
            print(f"::warning::{exc}")
            if args.cmd == "collect":
                sys.exit(1)
            warning = f"Collecte des nouvelles parties impossible : {exc}"

    if args.cmd in ("build", "update"):
        site.build(store.load_games(), cfg, champs, warning,
                   ia_sessions=args.ia_sessions, ia_global=args.ia_global)


if __name__ == "__main__":
    main()
