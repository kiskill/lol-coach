"""Indicateurs avancés, calculés à partir des fichiers bruts conservés :
data/raw/<partie>.json (détail Riot) et data/timeline/<partie>.json (extrait de timeline).

Chaque partie API reçoit g["ind"] = {"players": {rôle: {...}}, "team": {...}, "map": {...}}.
Les parties importées du CSV n'ont pas ces données et sont simplement ignorées ici.
"""
from collections import Counter, defaultdict

from . import ROLES, store

ISOLATED_GAP = 15  # s : une mort sans autre kill dans cet intervalle est une mort isolée
EPIC_MONSTERS = {"DRAGON", "HORDE", "RIFTHERALD", "BARON_NASHOR"}  # dragon ancestral inclus (DRAGON)

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
            # propres à un rôle (page Joueurs)
            "turret_dmg_min": round(p.get("damageDealtToTurrets", 0) / minutes),
            "dead_pct": round(100 * p.get("totalTimeSpentDead", 0) / (60 * minutes)),
            "dmg_pct": round(100 * ch["teamDamagePercentage"]) if "teamDamagePercentage" in ch else None,
            "roam_kills": ch.get("killsOnOtherLanesEarlyJungleAsLaner"),
            "jg_cs10": ch.get("jungleCsBefore10Minutes"),
            "enemy_jg": ch.get("enemyJungleMonsterKills"),
            "scuttles": ch.get("scuttleCrabKills"),
            "epic": sum(ch.get(k, 0) for k in ("dragonTakedowns", "riftHeraldTakedowns", "baronTakedowns")),
            "control_wards": ch.get("controlWardsPlaced", 0),
            "ward_kills": ch.get("wardTakedowns", p.get("wardsKilled", 0)),
            "immobilize": ch.get("enemyChampionImmobilizations"),
            "vision_adv": round(100 * ch["visionScoreAdvantageLaneOpponent"]) if "visionScoreAdvantageLaneOpponent" in ch else None,
            "deaths15": 0, "cs10": None, "cs10_diff": None,
            "tf": 0, "tf_first_death": 0, "tf_dmg": 0,
            "first_item": None, "first_item_min": None, "second_item_min": None,
            "items": [i for i in final if i and items.legendary(i)],
            # ordre d'achat des objets légendaires [[objet, minute], ...] (stuff final si pas de timeline)
            "build": [[i, None] for i in final if i and items.legendary(i)],
            "boots": next((i for i in final if i and items.boots(i)), None),
            "gold_min": round(p["goldEarned"] / minutes),
            "dmg_gold": round(p["totalDamageDealtToChampions"] / p["goldEarned"], 2) if p["goldEarned"] else None,
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
        "tf": None, "tf_won": None, "tf_lost": None, "tf_outnumbered": None, "tf_outnumbered_won": None,
        "tf_first_dead": {}, "killers_dmg": {},
        "isolated_deaths": None, "obj_share": None,
    }
    spatial = {"deaths": [], "kills": [], "objectives": [], "jungle": []}

    if tl:
        events = tl["events"]
        frames = tl["frames"]
        # --- morts, kills, positions
        deaths15 = 0
        for e in (e for e in events if e[0] == "K"):
            t, killer, victim, x, y = e[1], e[2], e[3], e[4], e[5]
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
        # --- contrôle des objectifs neutres (dragons, larves, Héraut, Nashor)
        epic = [o for o in objectives if o["type"] in EPIC_MONSTERS]
        if epic:
            team["obj_share"] = round(100 * sum(o["ours"] for o in epic) / len(epic))

        # --- combats : kills rapprochés dans le temps (moins de FIGHT_GAP s d'écart)
        kills = sorted((e for e in events if e[0] == "K"), key=lambda e: e[1])
        # morts isolées (pick-offs) : aucun autre kill, d'un côté ou de l'autre, à ±ISOLATED_GAP s
        team["isolated_deaths"] = sum(
            1 for i, e in enumerate(kills) if e[3] in our_pid
            and not any(abs(o[1] - e[1]) <= ISOLATED_GAP for j, o in enumerate(kills) if j != i))
        fights, cur = [], None
        for e in kills:
            t, killer, victim = e[1], e[2], e[3]
            assists = e[6] if len(e) > 6 else []
            dmg = e[7] if len(e) > 7 else {}
            if not (cur and t - cur["end"] <= FIGHT_GAP):
                cur = {"start": t, "end": t, "us": 0, "them": 0, "ours": set(), "theirs": set(),
                       "first": None, "dmg": defaultdict(int)}
                fights.append(cur)
            cur["end"] = t
            for pid in [killer, victim, *assists]:
                if pid in our_pid:
                    cur["ours"].add(pid)
                elif pid in their_pid:
                    cur["theirs"].add(pid)
            if cur["first"] is None:
                cur["first"] = ("ours", our_pid[victim]) if victim in our_pid else ("theirs", None)
            if killer in our_pid or victim in their_pid:
                cur["us"] += 1
                # dégâts de chacun de nos joueurs sur l'adversaire tué
                for pid, d in dmg.items():
                    if int(pid) in our_pid:
                        cur["dmg"][our_pid[int(pid)]] += d
            elif victim in our_pid:
                cur["them"] += 1
                # qui nous a infligé les dégâts avant cette mort
                for pid, d in dmg.items():
                    if int(pid) in their_pid:
                        champ = theirs[their_pid[int(pid)]]["championName"]
                        team["killers_dmg"][champ] = team["killers_dmg"].get(champ, 0) + d

        won = [f for f in fights if f["us"] > f["them"]]
        conv = sum(1 for f in won if any(o["ours"] and f["end"] <= o["t"] <= f["end"] + CONVERT_WINDOW
                                          for o in objectives))
        team["fights_won"], team["converted"] = len(won), conv

        # Teamfights : au moins 2 morts et 5 champions impliqués (hors simples picks)
        tfs = [f for f in fights if f["us"] + f["them"] >= 2 and len(f["ours"]) + len(f["theirs"]) >= 5]
        lost = [f for f in tfs if f["them"] > f["us"]]
        outn = [f for f in tfs if len(f["ours"]) < len(f["theirs"])]
        team.update({
            "tf": len(tfs), "tf_won": sum(f["us"] > f["them"] for f in tfs), "tf_lost": len(lost),
            "tf_outnumbered": len(outn), "tf_outnumbered_won": sum(f["us"] > f["them"] for f in outn),
        })
        for f in lost:
            if f["first"][0] == "ours":
                role = f["first"][1]
                team["tf_first_dead"][role] = team["tf_first_dead"].get(role, 0) + 1
                players[role]["tf_first_death"] += 1
        for f in tfs:
            for pid in f["ours"]:
                players[our_pid[pid]]["tf"] += 1
            for role, d in f["dmg"].items():
                players[role]["tf_dmg"] += d

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

        # --- objets légendaires dans l'ordre d'achat (et leur minute)
        bought = defaultdict(list)
        for e in events:
            if e[0] == "I" and e[2] in our_pid and items.legendary(e[3]):
                b = bought[our_pid[e[2]]]
                if all(i != e[3] for i, _ in b):
                    b.append([e[3], round(e[1] / 60, 1)])
        for role, b in bought.items():
            pl = players[role]
            pl["build"] = b
            pl["first_item"], pl["first_item_min"] = b[0]
            pl["second_item_min"] = b[1][1] if len(b) > 1 else None

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
