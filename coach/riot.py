"""Collecte des parties via l'API Riot Games (Account-V1 + Match-V5)."""
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone

import requests

from . import ROLES, store

POSITIONS = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid",
             "BOTTOM": "ADC", "UTILITY": "Support"}
QUEUES = {420: "Solo/Duo", 440: "Flex", 400: "Normale draft", 430: "Normale blind"}
STATE_VERSION = 2  # 2 = les parties écartées alimentent aussi data/outside.json


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

    def timeline(self, match_id):
        return self._get(f"/lol/match/v5/matches/{match_id}/timeline")


# ------------------------------------------------------------------ timeline
TIMELINE_VERSION = 2  # 2 = kills avec dégâts reçus par la victime


def extract_timeline(timeline):
    """Version compacte de la timeline Riot (quelques Ko au lieu de ~1 Mo), conservée
    dans data/timeline/ pour tous les calculs : écarts, morts, carte, achats d'items.

    frames[minute][participantId] = [or_total, xp, cs, x, y]
    events : ["K", t, tueur, victime, x, y, [assistants]]   kill de champion
             ["M", t, équipe, type, sous_type, x, y]        dragon / Nashor / Héraut / larves
             ["B", t, équipe_qui_perd, type, couloir, x, y] tour / inhibiteur détruit
             ["I", t, participant, item]                     achat d'item
    (t en secondes)
    """
    frames = []
    for fr in timeline["info"]["frames"]:
        frames.append({pid: [f.get("totalGold", 0), f.get("xp", 0),
                             f.get("minionsKilled", 0) + f.get("jungleMinionsKilled", 0),
                             f.get("position", {}).get("x", 0), f.get("position", {}).get("y", 0)]
                       for pid, f in fr["participantFrames"].items()})
    events = []
    for fr in timeline["info"]["frames"]:
        for e in fr.get("events", []):
            t = round(e.get("timestamp", 0) / 1000)
            pos = e.get("position", {})
            x, y = pos.get("x", 0), pos.get("y", 0)
            typ = e.get("type")
            if typ == "CHAMPION_KILL":
                # dégâts reçus par la victime juste avant sa mort, par participant
                dmg = {}
                for d in e.get("victimDamageReceived", []) or []:
                    pid = d.get("participantId", 0)
                    if pid:
                        dmg[str(pid)] = dmg.get(str(pid), 0) + d.get("physicalDamage", 0) \
                            + d.get("magicDamage", 0) + d.get("trueDamage", 0)
                events.append(["K", t, e.get("killerId", 0), e.get("victimId", 0), x, y,
                               e.get("assistingParticipantIds", []), dmg])
            elif typ == "ELITE_MONSTER_KILL":
                events.append(["M", t, e.get("killerTeamId", 0), e.get("monsterType", ""),
                               e.get("monsterSubType", ""), x, y])
            elif typ == "BUILDING_KILL":
                events.append(["B", t, e.get("teamId", 0), e.get("buildingType", ""),
                               e.get("laneType", ""), x, y])
            elif typ == "ITEM_PURCHASED":
                events.append(["I", t, e.get("participantId", 0), e.get("itemId", 0)])
    return {"v": TIMELINE_VERSION, "frames": frames, "events": events}


def early_stats(match, ext, game, minutes=(10, 15)):
    """Écarts (nous - eux) d'or, d'XP et de CS à 10 et 15 min, pour l'équipe et par couloir.
    Un champion n'apparaît qu'une fois par partie : on s'en sert pour relier timeline et rôles."""
    by_champ = {p["championName"]: p for p in match["info"]["participants"]}
    frames = ext["frames"]
    enemy_by_role = {p["role"]: p["champion"] for p in game["enemy"]}
    idx = {"totalGold": 0, "xp": 1, "cs": 2}
    out = {}
    for minute in minutes:
        if len(frames) <= minute:
            continue
        pf = frames[minute]

        def val(champ, key):
            p = by_champ.get(champ)
            f = pf.get(str(p["participantId"])) if p else None
            return f[idx[key]] if f else 0

        def team_diff(key):
            return (sum(val(p["champion"], key) for p in game["our"])
                    - sum(val(p["champion"], key) for p in game["enemy"]))

        lanes = {}
        for p in game["our"]:
            opp = enemy_by_role.get(p["role"])
            if opp:
                lanes[p["role"]] = {
                    "gold": val(p["champion"], "totalGold") - val(opp, "totalGold"),
                    "xp": val(p["champion"], "xp") - val(opp, "xp"),
                    "cs": val(p["champion"], "cs") - val(opp, "cs"),
                }
        out[str(minute)] = {"gold": team_diff("totalGold"), "xp": team_diff("xp"),
                            "cs": team_diff("cs"), "lanes": lanes}
    return out


def enrich_timelines(client):
    """Télécharge la timeline des parties API qui n'en ont pas encore d'extrait."""
    games = store.load_games()
    todo = [g for g in games if g.get("source") == "api"
            and store.timeline_version(g["match_id"]) < TIMELINE_VERSION]
    if not todo:
        return 0
    print(f"Timeline : {len(todo)} partie(s) à compléter…")
    for i, g in enumerate(todo, 1):
        match = store.load_raw(g["match_id"]) or client.match(g["match_id"])
        tl = client.timeline(g["match_id"])
        if match and tl:
            ext = extract_timeline(tl)
            store.save_timeline(g["match_id"], ext)
            g["early"] = early_stats(match, ext, g)
        if i % 10 == 0:
            print(f"  {i}/{len(todo)}…")
            store.save_games(games)  # sauvegarde régulière si la clé expire en route
    store.save_games(games)
    return len(todo)


# ------------------------------------------------------------------ normalisation
def is_remake(match):
    """Partie abandonnée très tôt : ignorée partout."""
    info = match["info"]
    return info.get("gameDuration", 0) < 300 or any(
        p.get("gameEndedInEarlySurrender") for p in info["participants"])


def normalize(match, player_by_puuid, player_roles, champs, min_players, team_queue=440):
    """Transforme une partie brute Riot en enregistrement simple. None si hors périmètre."""
    info = match["info"]
    parts = info["participants"]
    if is_remake(match) or info.get("queueId", team_queue) != team_queue:
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

    our, sub = [], None
    for role, p in ordered(team_players, True):
        extra = {}
        if p["puuid"] not in player_by_puuid:  # partie à 4 : le 5e est un remplaçant
            sub = p.get("riotIdGameName") or p.get("summonerName") or "Remplaçant"
            extra = {"sub": True}
        our.append({
            "role": role,
            "champion": p["championName"],
            "player": player_by_puuid.get(p["puuid"], sub),
            **extra,
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
        **({"sub": sub} if sub else {}),
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


def outside_records(match, player_by_puuid):
    """Une fiche compacte par joueur de l'équipe présent dans une partie hors soirée."""
    info = match["info"]
    parts = info["participants"]
    if is_remake(match):
        return []
    dur = info["gameDuration"] / 60
    team_kills = Counter()
    for p in parts:
        team_kills[p["teamId"]] += p["kills"]
    ours = [p for p in parts if p["puuid"] in player_by_puuid]
    out = []
    for p in ours:
        role = POSITIONS.get(p.get("teamPosition") or p.get("individualPosition"))
        opp = next((q for q in parts if q["teamId"] != p["teamId"] and role
                    and POSITIONS.get(q.get("teamPosition")) == role), None)
        ch = p.get("challenges") or {}
        mates = sorted(player_by_puuid[q["puuid"]] for q in ours
                       if q is not p and q["teamId"] == p["teamId"])
        out.append({
            "match_id": match["metadata"]["matchId"],
            "player": player_by_puuid[p["puuid"]],
            "queue": QUEUES.get(info.get("queueId"), str(info.get("queueId"))),
            "start_utc": datetime.fromtimestamp(info["gameStartTimestamp"] / 1000, tz=timezone.utc).isoformat(),
            "duration_min": round(dur, 2),
            "patch": ".".join(info.get("gameVersion", "").split(".")[:2]),
            "win": bool(p["win"]),
            "role": role,
            "champion": p["championName"],
            "opponent": opp["championName"] if opp else None,
            "mates": mates,
            "stack": len(mates) + 1,
            "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
            "cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"],
            "gold": p["goldEarned"],
            "damage": p["totalDamageDealtToChampions"],
            "vision": p["visionScore"],
            "kp": round(100 * (p["kills"] + p["assists"]) / team_kills[p["teamId"]])
                  if team_kills[p["teamId"]] else 0,
            "dmg_pct": round(100 * ch["teamDamagePercentage"]) if "teamDamagePercentage" in ch else None,
            "cs10": ch.get("laneMinionsFirst10Minutes"),
            "solo_kills": ch.get("soloKills"),
            "pinks": p.get("visionWardsBoughtInGame"),
        })
    return out


def collect(cfg, api_key, champs):
    """Récupère les nouvelles parties de l'équipe, et celles jouées hors soirée."""
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
    min_players = cfg.get("min_team_players", 5)
    team_queue = cfg.get("queue", 440)
    outside = store.load_outside()
    if state.get("v", 1) < STATE_VERSION:
        # Ancien format : les parties écartées n'ont laissé aucune trace, on les réexamine
        print(f"Migration : réexamen des {len(state['ignored'])} partie(s) écartée(s)…")
        state["ignored"], state["v"] = [], STATE_VERSION
    # Parties hors soirée devenues parties d'équipe (min_team_players abaissé) : réexaminées
    promote = {r["match_id"] for r in outside if r["queue"] == QUEUES.get(team_queue)
               and r["stack"] >= min_players}
    if promote:
        outside = [r for r in outside if r["match_id"] not in promote]
    ignored = set(state["ignored"]) - promote
    start_ts = int(datetime.fromisoformat(cfg.get("start_date", "2026-01-01"))
                   .replace(tzinfo=timezone.utc).timestamp())

    queues = [team_queue]
    if cfg.get("outside", {}).get("enabled", True):
        queues += [q for q in cfg.get("outside", {}).get("queues", [420, 440]) if q not in queues]
    candidates = set()
    for puuid in player_by_puuid:
        for q in queues:
            candidates |= set(client.match_ids(puuid, q, start_ts))
    todo = sorted(candidates - known - ignored)
    print(f"{len(todo)} nouvelle(s) partie(s) à examiner.")

    new_games, n_team, n_out = [], 0, 0

    def save():
        state["ignored"] = sorted(ignored)
        store.save_state(state)
        store.save_outside(outside)
        if new_games:
            store.upsert_games(new_games)

    # sauvegarde régulière : si la clé expire en route, le travail fait est conservé
    try:
        for i, mid in enumerate(todo, 1):
            match = client.match(mid)
            if not match:
                continue
            game = normalize(match, player_by_puuid, player_roles, champs, min_players, team_queue)
            if game:
                store.save_raw(match)
                new_games.append(game)
                n_team += 1
            else:
                recs = outside_records(match, player_by_puuid)
                outside.extend(recs)
                n_out += bool(recs)
                ignored.add(mid)
            if i % 25 == 0:
                print(f"  {i}/{len(todo)} examinées…")
                save()
                new_games = []
    finally:
        save()
    print(f"{n_team} partie(s) d'équipe ajoutée(s), {n_out} partie(s) hors soirée.")
    enrich_timelines(client)
    return n_team
