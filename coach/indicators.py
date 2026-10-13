"""Indicateurs avancés, calculés à partir des fichiers bruts conservés :
data/raw/<partie>.json (détail Riot) et data/timeline/<partie>.json (extrait de timeline).

Chaque partie API reçoit g["ind"] = {"players": {rôle: {...}}, "team": {...}, "map": {...}}.
Les parties importées du CSV n'ont pas ces données et sont simplement ignorées ici.
"""
from collections import Counter, defaultdict

from . import ROLES, store

# Champions dont le kit repose fortement sur les soins (=> anti-heal utile en face)
HEALERS = {c.lower() for c in [
    "Soraka", "Yuumi", "Sona", "Nami", "Seraphine", "Milio", "Taric", "Aatrox", "DrMundo",
    "Vladimir", "Sylas", "Swain", "Warwick", "Fiddlesticks", "Briar", "Illaoi", "Maokai",
    "Olaf", "Senna", "Zac", "Gwen", "Volibear", "Trundle",
]}

FIGHT_GAP = 20      # secondes sans kill => nouveau combat
CONVERT_WINDOW = 90  # secondes après un combat gagné pour prendre un objectif
JUNGLE_MINUTES = range(1, 9)

ZONES = ["Base", "Top lane", "Mid lane", "Bot lane", "Rivière", "Notre jungle", "Jungle adverse"]


def zone(x, y, blue_side):
    """Zone approximative de la Faille à partir des coordonnées Riot (0 → ~15 000)."""
    if (x < 3200 and y < 3200) or (x > 11700 and y > 11700):
        return "Base"
    if (x < 2400 and y > 3200) or (y > 12600 and x < 11700):
        return "Top lane"
    if (y < 2400 and x > 3200) or (x > 12600 and y < 11700):
        return "Bot lane"
    if abs(x - y) < 1300:
        return "Mid lane"
    if abs(x + y - 14800) < 1400:
        return "Rivière"
    on_blue_half = x + y < 14800
    return "Notre jungle" if on_blue_half == blue_side else "Jungle adverse"


def _participant_map(raw, game):
    """rôle -> participant Riot, pour nos joueurs et les adversaires."""
    by_champ = {p["championName"]: p for p in raw["info"]["participants"]}
    ours = {p["role"]: by_champ.get(p["champion"]) for p in game["our"]}
    theirs = {p["role"]: by_champ.get(p["champion"]) for p in game["enemy"]}
    return {r: p for r, p in ours.items() if p}, {r: p for r, p in theirs.items() if p}


def game_indicators(game, raw, tl, items):
    ours, theirs = _participant_map(raw, game)
    if not ours:
        return None
    team_id = next(iter(ours.values()))["teamId"]
    blue = team_id == 100
    minutes = max(game["duration_min"], 1)
    our_pid = {p["participantId"]: r for r, p in ours.items()}
    their_pid = {p["participantId"]: r for r, p in theirs.items()}
    team_kills = sum(p["kills"] for p in ours.values()) or 1

    players = {}
    for role, p in ours.items():
        ch = p.get("challenges", {}) or {}
        final = [p.get(f"item{i}", 0) for i in range(7)]
        players[role] = {
            "wards": p.get("wardsPlaced", 0),
            "wards_killed": p.get("wardsKilled", 0),
            "pinks": p.get("visionWardsBoughtInGame", 0),
            "vision": p.get("visionScore", 0),
            "kp": round(100 * (p["kills"] + p["assists"]) / team_kills),
            "tank_min": round((p.get("totalDamageTaken", 0) + p.get("damageSelfMitigated", 0)) / minutes),
            "cc": p.get("timeCCingOthers", 0),
            "solo_kills": ch.get("soloKills", 0),
            "plates": ch.get("turretPlatesTaken", 0),
            "deaths15": 0, "cs10": None, "cs10_diff": None,
            "first_item": None, "first_item_min": None,
            "items": [i for i in final if i and items.legendary(i)],
            "antiheal": any(i and items.antiheal(i) for i in final),
        }

    phys = sum(p.get("physicalDamageDealtToChampions", 0) for p in ours.values())
    magic = sum(p.get("magicDamageDealtToChampions", 0) for p in ours.values())
    enemy_healers = sorted(p["championName"] for p in theirs.values() if p["championName"].lower() in HEALERS)
    team = {
        "ap_share": round(100 * magic / (phys + magic)) if phys + magic else None,
        "antiheal_needed": bool(enemy_healers),
        "enemy_healers": enemy_healers,
        "antiheal_bought": any(pl["antiheal"] for pl in players.values()),
        "wards": sum(pl["wards"] for pl in players.values()),
        "pinks": sum(pl["pinks"] for pl in players.values()),
        "deaths15": None, "first_death": None, "fights_won": None, "converted": None,
    }
    spatial = {"deaths": [], "kills": [], "objectives": [], "jungle": []}

    if tl:
        events = tl["events"]
        frames = tl["frames"]
        # --- morts, kills, positions
        deaths15 = 0
        for e in (e for e in events if e[0] == "K"):
            _, t, killer, victim, x, y, _assists = e
            if victim in our_pid:
                role = our_pid[victim]
                spatial["deaths"].append({"x": x, "y": y, "t": t, "role": role, "zone": zone(x, y, blue)})
                if t < 900:
                    players[role]["deaths15"] += 1
                    deaths15 += 1
            elif killer in our_pid:
                spatial["kills"].append({"x": x, "y": y, "t": t, "role": our_pid[killer], "zone": zone(x, y, blue)})
        team["deaths15"] = deaths15
        if spatial["deaths"]:
            team["first_death"] = round(min(d["t"] for d in spatial["deaths"]) / 60, 1)

        # --- objectifs (dragons, Nashor, Héraut, larves, tours, inhibiteurs)
        objectives = []
        for e in events:
            if e[0] == "M":
                objectives.append({"t": e[1], "ours": e[2] == team_id, "type": e[3], "x": e[5], "y": e[6]})
            elif e[0] == "B":
                objectives.append({"t": e[1], "ours": e[2] != team_id, "type": e[3], "x": e[5], "y": e[6]})
        spatial["objectives"] = objectives

        # --- combats gagnés et conversion en objectif
        kills = sorted((e for e in events if e[0] == "K"), key=lambda e: e[1])
        fights, cur = [], None
        for e in kills:
            if cur and e[1] - cur["end"] <= FIGHT_GAP:
                cur["end"] = e[1]
            else:
                cur = {"start": e[1], "end": e[1], "us": 0, "them": 0}
                fights.append(cur)
            if e[2] in our_pid:
                cur["us"] += 1
            elif e[3] in our_pid:
                cur["them"] += 1
        won = [f for f in fights if f["us"] > f["them"]]
        conv = sum(1 for f in won if any(o["ours"] and f["end"] <= o["t"] <= f["end"] + CONVERT_WINDOW
                                          for o in objectives))
        team["fights_won"], team["converted"] = len(won), conv

        # --- CS à 10 min et écart avec le vis-à-vis
        if len(frames) > 10:
            f10 = frames[10]
            for role, p in ours.items():
                mine = f10.get(str(p["participantId"]))
                if mine:
                    players[role]["cs10"] = mine[2]
                    opp = theirs.get(role)
                    other = f10.get(str(opp["participantId"])) if opp else None
                    if other:
                        players[role]["cs10_diff"] = mine[2] - other[2]

        # --- premier objet légendaire acheté (et sa minute)
        for e in events:
            if e[0] == "I" and e[2] in our_pid and items.legendary(e[3]):
                pl = players[our_pid[e[2]]]
                if pl["first_item"] is None:
                    pl["first_item"], pl["first_item_min"] = e[3], round(e[1] / 60, 1)

        # --- trajet du jungler (minutes 1 à 8)
        jg = ours.get("Jungle")
        if jg:
            for m in JUNGLE_MINUTES:
                if m < len(frames):
                    pos = frames[m].get(str(jg["participantId"]))
                    if pos:
                        spatial["jungle"].append({"m": m, "x": pos[3], "y": pos[4]})

    return {"players": players, "team": team, "map": spatial, "blue": blue}


def attach(games, champs):
    """Ajoute g["ind"] à chaque partie API dont le détail brut est disponible."""
    items = store.Items(champs.version)
    n = 0
    for g in games:
        if g.get("source") != "api":
            continue
        raw = store.load_raw(g["match_id"])
        if not raw:
            continue
        g["ind"] = game_indicators(g, raw, store.load_timeline(g["match_id"]), items)
        n += g["ind"] is not None
    return items, n
