"""Point d'entrée.

  python main.py import-csv data/historique_initial.csv   # importer un historique CSV
  python main.py collect                                   # récupérer les nouvelles parties (API Riot)
  python main.py build                                     # générer le site dans site/
  python main.py update                                    # collect + build (utilisé chaque semaine)
"""
import argparse
import os
import sys

import yaml

from coach import importer, site, store
from coach.riot import RiotError, collect


def main():
    parser = argparse.ArgumentParser(description="Outil de coaching LoL")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import-csv", help="importer un historique CSV")
    p_imp.add_argument("path")
    sub.add_parser("collect", help="récupérer les nouvelles parties via l'API Riot")
    sub.add_parser("build", help="générer le site")
    sub.add_parser("update", help="collect puis build")
    parser.add_argument("--config", default="config.yaml")
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
        site.build(store.load_games(), cfg, champs, warning)


if __name__ == "__main__":
    main()
