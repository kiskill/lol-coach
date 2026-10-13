"""Collecte des parties via l'API Riot Games (Account-V1 + Match-V5)."""
import time
import urllib.parse
from datetime import datetime, timezone

import requests

from . import ROLES, store

POSITIONS = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid",
             "BOTTOM": "ADC", "UTILITY": "Support"}


class RiotError(Exception):
    pass


class RiotClient:
    # Clé dev/personnelle : 100 requêtes / 2 minutes -> ~1,25 s entre deux appels
    MIN_INTERVAL = 1.25

    def __init__(self, api_key, regional="europe"):
        if not api_key:
            raise RiotError("Aucune clé Riot : définis la variable RIOT_API_KEY.")
        self.base = f"https://{regional}.api.riotgames.com"
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = api_key
        self._last = 0.0

    def _get(self, path, params=None):
        for attempt in range(6):
            wait = self.MIN_INTERVAL - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            r = self.session.get(self.base + path, params=params, timeout=30)
            if r.status_code == 429:  # limite atteinte : on attend ce que Riot demande
                time.sleep(int(r.headers.get("Retry-After", "10")) + 1)
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                raise RiotError(
                    "Clé Riot refusée (401/403). Une clé de développement expire "
                    "toutes les 24 h : régénère-la sur developer.riotgames.com et "
                    "mets à jour le secret RIOT_API_KEY."
                )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        raise RiotError(f"Échec répété sur {path}")

    def puuid(self, riot_id):
        name, tag = riot_id.rsplit("#", 1)
        data = self._get(
            "/riot/account/v1/accounts/by-riot-id/"
            f"{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}"
        )
        if not data:
            raise RiotError(f"Joueur introuvable : {riot_id} (vérifie le Riot ID dans config.yaml)")
        return data["puuid"]

    def match_ids(self, puuid, queue, start_time):
        ids, start = [], 0
        while True:
            batch = self._get(
                f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                {"queue": queue, "startTime": start_time, "start": start, "count": 100},
            ) or []
            ids += batch
            if len(batch) < 100:
                return ids
            start += 100

    def match(self, match_id):
        return self._get(f"/lol/match/v5/matches/{match_id}")


# ------------------------------------------------------------------ normalisation
def normalize(match, player_by_puuid, player_roles, champs, min_players):
    """Transforme une partie brute Riot en enregistrement simple. None si hors périmètre."""
    info = match["info"]
    parts = info["participants"]
    # remake (partie abandonnée très tôt) : ignorée
    if info.get("gameDuration", 0) < 300 or any(p.get("gameEndedInEarlySurrender") for p in parts):
        return None

    ours_by_team = {}
    for p in parts:
        if p["puuid"] in player_by_puuid:
            ours_by_team.setdefault(p["teamId"], []).append(p)
    if not ours_by_team:
        return None
    team_id, ours = max(ours_by_team.items(), key=lambda kv: len(kv[1]))
    if len(ours) < min_players:
        return None

    def role_of(p, fallback=None):
        return POSITIONS.get(p.get("teamPosition") or p.get("individualPosition"), fallback)

    def ordered(players, our_side):
        out, used = {}, set()
        for p in players:
            fb = player_roles.get(player_by_puuid.get(p["puuid"])) if our_side else None
            r = role_of(p, fb)
            if r and r not in used:
                out[r] = p
                used.add(r)
        free = [r for r in ROLES if r not in used]
        for p in players:
            if p not in out.values() and free:
                out[free.pop(0)] = p
        return [(r, out[r]) for r in ROLES if r in out]

    team_players = [p for p in parts if p["teamId"] == team_id]
    enemy_players = [p for p in parts if p["teamId"] != team_id]
    duration_min = info["gameDuration"] / 60

    our = []
    for role, p in ordered(team_players, True):
        our.append({
            "role": role,
            "champion": p["championName"],
            "player": player_by_puuid.get(p["puuid"], "Remplaçant"),
            "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
            "cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"],
            "gold": p["goldEarned"],
            "damage": p["totalDamageDealtToChampions"],
            "vision": p["visionScore"],
            "first_blood": bool(p.get("firstBloodKill") or p.get("firstBloodAssist")),
        })
    enemy = [{"role": r, "champion": p["championName"]} for r, p in ordered(enemy_players, False)]

    teams = {t["teamId"]: t for t in info["teams"]}
    us, them = teams[team_id], next(t for tid, t in teams.items() if tid != team_id)

    def bans(team):
        out = []
        for b in team.get("bans", []):
            cid = champs.id_from_key(b["championId"]) if b["championId"] > 0 else None
            if cid:
                out.append(cid)
        return out

    def obj(name):
        a = us["objectives"].get(name, {})
        b = them["objectives"].get(name, {})
        return {"first": bool(a.get("first")), "us": a.get("kills", 0), "them": b.get("kills", 0)}

    start = datetime.fromtimestamp(info["gameStartTimestamp"] / 1000, tz=timezone.utc)
    return {
        "match_id": match["metadata"]["matchId"],
        "source": "api",
        "start_utc": start.isoformat(),
        "duration_min": round(duration_min, 2),
        "win": bool(us["win"]),
        "patch": ".".join(info.get("gameVersion", "").split(".")[:2]),
        "our": our,
        "enemy": enemy,
        "our_bans": bans(us),
        "enemy_bans": bans(them),
        "objectives": {
            "first_blood": any(p["first_blood"] for p in our),
            "first_tower": obj("tower")["first"],
            "first_dragon": obj("dragon")["first"],
            "dragons": [obj("dragon")["us"], obj("dragon")["them"]],
            "barons": [obj("baron")["us"], obj("baron")["them"]],
            "towers": [obj("tower")["us"], obj("tower")["them"]],
            "kills": [sum(p["kills"] for p in our),
                      sum(p["kills"] for p in enemy_players)],
        },
    }


def collect(cfg, api_key, champs):
    """Récupère les nouvelles parties de l'équipe. Renvoie le nombre de parties ajoutées."""
    client = RiotClient(api_key, cfg.get("regional", "europe"))
    state = store.load_state()

    player_by_puuid, player_roles = {}, {}
    for pl in cfg["players"]:
        rid = pl["riot_id"]
        if rid not in state["puuids"]:
            print(f"Recherche du PUUID de {rid}…")
            state["puuids"][rid] = client.puuid(rid)
        player_by_puuid[state["puuids"][rid]] = rid.split("#")[0]
        player_roles[rid.split("#")[0]] = pl["role"]
    store.save_state(state)

    known = {g["match_id"] for g in store.load_games() if g.get("source") == "api"}
    ignored = set(state["ignored"])
    start_ts = int(datetime.fromisoformat(cfg.get("start_date", "2026-01-01"))
                   .replace(tzinfo=timezone.utc).timestamp())

    candidates = set()
    for puuid in player_by_puuid:
        candidates |= set(client.match_ids(puuid, cfg.get("queue", 440), start_ts))
    todo = sorted(candidates - known - ignored)
    print(f"{len(todo)} nouvelle(s) partie(s) à examiner.")

    new_games = []
    for i, mid in enumerate(todo, 1):
        match = client.match(mid)
        if not match:
            continue
        game = normalize(match, player_by_puuid, player_roles, champs,
                         cfg.get("min_team_players", 5))
        if game:
            store.save_raw(match)
            new_games.append(game)
        else:
            state["ignored"].append(mid)
        if i % 10 == 0:
            print(f"  {i}/{len(todo)} examinées…")

    store.save_state(state)
    if new_games:
        store.upsert_games(new_games)
    print(f"{len(new_games)} partie(s) d'équipe ajoutée(s).")
    return len(new_games)
