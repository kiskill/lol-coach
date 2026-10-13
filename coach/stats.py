"""Calcul des statistiques globales et par session."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import ROLES

DUOS = [("ADC", "Support", "Duo bot"), ("Jungle", "Mid", "Jungle + Mid"),
        ("Jungle", "Support", "Jungle + Support"), ("Top", "Jungle", "Top + Jungle")]
DURATION_BUCKETS = [(0, 25, "< 25 min"), (25, 30, "25-30 min"),
                    (30, 35, "30-35 min"), (35, 999, "35 min et +")]


def rec(n, w):
    return {"games": n, "wins": w, "losses": n - w, "wr": round(100 * w / n) if n else 0}


def by_role(g, role, side="our"):
    return next((p for p in g[side] if p["role"] == role), None)


# ------------------------------------------------------------------ sessions
def local_dt(g, tz):
    return datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00")).astimezone(ZoneInfo(tz))


def split_sessions(games, tz="Europe/Paris", cutoff=6):
    """Une session = toutes les parties d'une même soirée (avant `cutoff` h = veille)."""
    groups = defaultdict(list)
    for g in games:
        d = local_dt(g, tz)
        day = (d - timedelta(days=1)).date() if d.hour < cutoff else d.date()
        groups[day.isoformat()].append(g)
    sessions = []
    for day in sorted(groups):
        gs = sorted(groups[day], key=lambda g: g["start_utc"])
        sessions.append({**rec(len(gs), sum(g["win"] for g in gs)),
                         "date": day, "games": gs})
    return sessions


# ------------------------------------------------------------------ blocs de stats
def summary(games):
    n = len(games)
    out = rec(n, sum(g["win"] for g in games))
    out["avg_duration"] = round(sum(g["duration_min"] for g in games) / n, 1) if n else 0
    return out


def champion_stats(games):
    acc = {r: defaultdict(lambda: [0, 0]) for r in ROLES}
    for g in games:
        for p in g["our"]:
            a = acc[p["role"]][p["champion"]]
            a[0] += 1
            a[1] += g["win"]
    return {r: sorted(({"champion": c, **rec(n, w)} for c, (n, w) in d.items()),
                      key=lambda x: (-x["games"], -x["wr"]))
            for r, d in acc.items()}


def duo_stats(games):
    out = []
    for r1, r2, label in DUOS:
        acc = defaultdict(lambda: [0, 0])
        for g in games:
            a, b = by_role(g, r1), by_role(g, r2)
            if a and b:
                k = acc[(a["champion"], b["champion"])]
                k[0] += 1
                k[1] += g["win"]
        rows = sorted(({"pair": list(k), **rec(n, w)} for k, (n, w) in acc.items()),
                      key=lambda x: (-x["games"], -x["wr"]))
        out.append({"label": label, "roles": [r1, r2], "rows": rows})
    return out


def enemy_stats(games, min_games=2):
    acc = defaultdict(lambda: [0, 0])
    for g in games:
        for p in g["enemy"]:
            a = acc[p["champion"]]
            a[0] += 1
            a[1] += g["win"]
    rows = [{"champion": c, **rec(n, w)} for c, (n, w) in acc.items() if n >= min_games]
    return {"hardest": sorted(rows, key=lambda x: (x["wr"], -x["games"]))[:12],
            "easiest": sorted(rows, key=lambda x: (-x["wr"], -x["games"]))[:12]}


def ban_stats(games):
    with_bans = [g for g in games if g.get("our_bans") or g.get("enemy_bans")]
    ours, theirs = Counter(), Counter()
    for g in with_bans:
        ours.update(g.get("our_bans", []))
        theirs.update(g.get("enemy_bans", []))
    return {"games_with_bans": len(with_bans),
            "our_bans": ours.most_common(10),
            "enemy_bans": theirs.most_common(10)}


def duration_stats(games):
    out = []
    for lo, hi, label in DURATION_BUCKETS:
        gs = [g for g in games if lo <= g["duration_min"] < hi]
        out.append({"label": label, **rec(len(gs), sum(g["win"] for g in gs))})
    return out


def game_index_stats(sessions):
    acc = defaultdict(lambda: [0, 0])
    for s in sessions:
        for i, g in enumerate(s["games"], 1):
            k = acc[min(i, 6)]
            k[0] += 1
            k[1] += g["win"]
    return [{"label": f"Partie {i}" if i < 6 else "Partie 6+", **rec(*acc[i])}
            for i in sorted(acc)]


def objective_stats(games):
    out = []
    for key, label in [("first_blood", "First blood"), ("first_tower", "Première tour"),
                       ("first_dragon", "Premier dragon")]:
        gs = [g for g in games if key in g.get("objectives", {})]
        if not gs:
            continue
        yes = [g for g in gs if g["objectives"][key]]
        no = [g for g in gs if not g["objectives"][key]]
        out.append({"label": label, "rate": round(100 * len(yes) / len(gs)),
                    "with": rec(len(yes), sum(g["win"] for g in yes)),
                    "without": rec(len(no), sum(g["win"] for g in no))})
    return out


GOLD_STATES = [(1500, 10**6, "Avance > 1 500 or"), (0, 1500, "Légère avance"),
               (-1500, 0, "Léger retard"), (-10**6, -1500, "Retard > 1 500 or")]


def _avg(xs, nd=0):
    if not xs:
        return None
    v = sum(xs) / len(xs)
    return round(v) if nd == 0 else round(v, nd)


def early_game_stats(games):
    """Exploitation de la timeline : où se gagnent / se perdent les parties."""
    g10 = [g for g in games if g.get("early", {}).get("10")]
    g15 = [g for g in games if g.get("early", {}).get("15")]
    if not g10:
        return None
    gold15 = lambda g: g["early"]["15"]["gold"]
    out = {
        "games": len(g15),
        "gold10": _avg([g["early"]["10"]["gold"] for g in g10]),
        "gold15": _avg([gold15(g) for g in g15]),
        "cs15": _avg([g["early"]["15"]["cs"] for g in g15]),
        "xp15": _avg([g["early"]["15"]["xp"] for g in g15]),
        "states": [],
        "throws": [{"match_id": g["match_id"], "start_utc": g["start_utc"], "gold15": gold15(g)}
                   for g in g15 if gold15(g) >= 1500 and not g["win"]],
        "comebacks": [{"match_id": g["match_id"], "start_utc": g["start_utc"], "gold15": gold15(g)}
                      for g in g15 if gold15(g) <= -1500 and g["win"]],
    }
    for lo, hi, label in GOLD_STATES:
        gs = [g for g in g15 if lo <= gold15(g) < hi]
        out["states"].append({"label": label, **rec(len(gs), sum(g["win"] for g in gs))})

    # Phase de lane par rôle : écart moyen face au vis-à-vis + % de lanes "gagnées" à 15 min
    lanes = []
    for r in ROLES:
        l10 = [g["early"]["10"]["lanes"][r] for g in g10 if r in g["early"]["10"]["lanes"]]
        l15 = [g["early"]["15"]["lanes"][r] for g in g15 if r in g["early"]["15"]["lanes"]]
        if not l15 and not l10:
            continue
        lanes.append({"role": r, "games": len(l15),
                      "gold10": _avg([x["gold"] for x in l10]),
                      "gold15": _avg([x["gold"] for x in l15]),
                      "cs15": _avg([x["cs"] for x in l15], 1),
                      "xp15": _avg([x["xp"] for x in l15]),
                      "won_pct": round(100 * sum(x["gold"] > 0 for x in l15) / len(l15)) if l15 else None})
    out["lanes"] = lanes

    # Phase de lane par champion (quels picks gagnent leur lane)
    acc = defaultdict(list)
    for g in g15:
        for p in g["our"]:
            lane = g["early"]["15"]["lanes"].get(p["role"])
            if lane:
                acc[(p["role"], p["champion"])].append((lane["gold"], g["win"]))
    out["champions"] = sorted(
        ({"role": r, "champion": c, "gold15": _avg([x[0] for x in v]),
          **rec(len(v), sum(x[1] for x in v))} for (r, c), v in acc.items() if len(v) >= 2),
        key=lambda x: -x["gold15"])
    return out


def objective_totals(games):
    """Moyennes d'objectifs par partie et winrate selon qui contrôle les dragons / Nashor."""
    gs = [g for g in games if g.get("objectives", {}).get("dragons")]
    if not gs:
        return None
    o = lambda g, k, i: g["objectives"][k][i]
    out = {"games": len(gs), "avg": {}, "splits": []}
    for k, label in [("dragons", "Dragons"), ("barons", "Nashors"), ("towers", "Tours")]:
        out["avg"][label] = [_avg([o(g, k, 0) for g in gs], 1), _avg([o(g, k, 1) for g in gs], 1)]
    for k, label in [("dragons", "Plus de dragons"), ("barons", "Au moins autant de Nashors")]:
        cmp = (lambda a, b: a > b) if k == "dragons" else (lambda a, b: a >= b and a > 0)
        yes = [g for g in gs if cmp(o(g, k, 0), o(g, k, 1))]
        out["splits"].append({"label": label, **rec(len(yes), sum(g["win"] for g in yes))})
    return out


def player_stats(games):
    acc = {}
    for g in games:
        team_dmg = sum(p.get("damage", 0) for p in g["our"]) or 1
        team_gold = sum(p.get("gold", 0) for p in g["our"]) or 1
        lanes15 = g.get("early", {}).get("15", {}).get("lanes", {})
        for p in g["our"]:
            if "player" not in p:
                continue
            a = acc.setdefault(p["player"], {"player": p["player"], "role": p["role"],
                                             "games": 0, "wins": 0, "k": 0, "d": 0, "a": 0,
                                             "cs": 0, "minutes": 0, "damage": 0, "vision": 0,
                                             "dmg_share": [], "gold_share": [], "lane15": [],
                                             "champions": Counter()})
            a["dmg_share"].append(p["damage"] / team_dmg)
            a["gold_share"].append(p["gold"] / team_gold)
            if p["role"] in lanes15:
                a["lane15"].append(lanes15[p["role"]]["gold"])
            a["games"] += 1
            a["wins"] += g["win"]
            a["k"] += p["kills"]
            a["d"] += p["deaths"]
            a["a"] += p["assists"]
            a["cs"] += p["cs"]
            a["minutes"] += g["duration_min"]
            a["damage"] += p["damage"]
            a["vision"] += p["vision"]
            a["champions"][p["champion"]] += 1
    out = []
    for a in acc.values():
        n = a["games"]
        out.append({
            "player": a["player"], "role": a["role"], **rec(n, a["wins"]),
            "kda": round((a["k"] + a["a"]) / max(a["d"], 1), 2),
            "kills": round(a["k"] / n, 1), "deaths": round(a["d"] / n, 1),
            "assists": round(a["a"] / n, 1),
            "cs_min": round(a["cs"] / a["minutes"], 1) if a["minutes"] else 0,
            "damage_min": round(a["damage"] / a["minutes"]) if a["minutes"] else 0,
            "vision_min": round(a["vision"] / a["minutes"], 2) if a["minutes"] else 0,
            "dmg_share": round(100 * sum(a["dmg_share"]) / n),
            "gold_share": round(100 * sum(a["gold_share"]) / n),
            "lane15": _avg(a["lane15"]),
            "champions": a["champions"].most_common(5),
        })
    order = {r: i for i, r in enumerate(ROLES)}
    return sorted(out, key=lambda x: order.get(x["role"], 9))


def global_report(games, sessions, cfg):
    st = cfg.get("stats", {})
    return {
        "summary": summary(games),
        "champions": champion_stats(games),
        "duos": duo_stats(games),
        "enemies": enemy_stats(games, st.get("min_games_enemy", 2)),
        "bans": ban_stats(games),
        "durations": duration_stats(games),
        "game_index": game_index_stats(sessions),
        "objectives": objective_stats(games),
        "objective_totals": objective_totals(games),
        "early": early_game_stats(games),
        "players": player_stats(games),
        "sessions": [{"date": s["date"], "games": len(s["games"]),
                      "wins": s["wins"], "wr": s["wr"]} for s in sessions],
        "thresholds": st,
    }


def session_report(session, all_games, cfg):
    games = session["games"]
    global_champs = champion_stats(all_games)
    lookup = {(r, c["champion"]): c for r, rows in global_champs.items() for c in rows}
    picks = []
    for r in ROLES:
        seen = Counter(by_role(g, r)["champion"] for g in games if by_role(g, r))
        for champ, n in seen.items():
            w = sum(g["win"] for g in games if by_role(g, r) and by_role(g, r)["champion"] == champ)
            picks.append({"role": r, "champion": champ, **rec(n, w),
                          "global": lookup.get((r, champ))})
    return {
        "date": session["date"],
        "summary": summary(games),
        "games": games,
        "picks": picks,
        "duos": duo_stats(games),
        "objectives": objective_stats(games),
        "early": early_game_stats(games),
        "players": player_stats(games),
        "players_global": {p["player"]: p for p in player_stats(all_games)},
        "bans": ban_stats(games),
    }
