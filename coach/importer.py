"""Import d'un historique CSV (format de l'export initial) pour démarrer sans API."""
import csv

from . import ROLES, store


def import_csv(path):
    games = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ours = [c.strip() for c in row["our_composition"].split("/")]
            enemy = [c.strip() for c in row["enemy_composition"].split("/")]
            games.append({
                "match_id": row["match_id"],
                "source": "csv",
                "start_utc": row["game_date_utc"],
                "duration_min": float(row["duration_minutes"]),
                "win": row["result"].strip().lower().startswith("v"),
                "patch": ".".join(row.get("game_version", "").split(".")[:2]),
                "our": [{"role": r, "champion": c} for r, c in zip(ROLES, ours)],
                "enemy": [{"role": r, "champion": c} for r, c in zip(ROLES, enemy)],
                "our_bans": [],
                "enemy_bans": [],
                "objectives": {},
            })
    total = store.upsert_games(games)
    print(f"{len(games)} partie(s) importée(s) depuis {path} ({total} au total).")
