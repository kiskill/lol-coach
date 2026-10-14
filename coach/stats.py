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
        team_kills = sum(p.get("kills", 0) for p in g["our"])
        lanes15 = g.get("early", {}).get("15", {}).get("lanes", {})
        for p in g["our"]:
            if "player" not in p or p.get("sub"):  # le remplaçant n'a pas de ligne joueur
                continue
            a = acc.setdefault(p["player"], {"player": p["player"], "role": p["role"],
                                             "games": 0, "wins": 0, "k": 0, "d": 0, "a": 0,
                                             "cs": 0, "minutes": 0, "damage": 0, "vision": 0,
                                             "dmg_share": [], "gold_share": [], "lane15": [], "kp": [],
                                             "champions": Counter()})
            a["dmg_share"].append(p["damage"] / team_dmg)
            a["gold_share"].append(p["gold"] / team_gold)
            if team_kills:
                a["kp"].append(100 * (p["kills"] + p["assists"]) / team_kills)
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
            "kp": _avg(a["kp"]),
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
        "key": key_indicators(games),
        "key_rows": indicator_rows(key_indicators(games)),
        "teamfights": teamfight_stats(games),
        "trend": indicator_trend(sessions),
        "player_details": player_details(games),
        "composition": composition_stats(games),
        "tilt": tilt_stats(sessions),
        "zones": zone_stats(games),
        "map": map_data(games),
        "form": form_stats(sessions),
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
        "key": key_indicators(games),
        "key_rows": indicator_rows(key_indicators(games), key_indicators(all_games)),
        "teamfights": teamfight_stats(games),
        "teamfights_global": teamfight_stats(all_games),
        "player_details": player_details(games),
        "player_details_global": {p["player"]: p for p in player_details(all_games)},
        "zones": zone_stats(games),
        "map": map_data(games, with_jungle=True),
        "lines": [game_line(g) for g in games],
        "bans": ban_stats(games),
    }


# =================================================================== indicateurs avancés
# (clé, libellé, unité, sens : "high" = plus c'est haut mieux c'est)
KEY_INDICATORS = [
    ("deaths15", "Morts avant 15 min", "/ partie", "low"),
    ("tf_wr", "Teamfights gagnés", "%", "high"),
    ("tf_outnumbered", "Teamfights en infériorité numérique", "%", "low"),
    ("conversion", "Combats gagnés convertis en objectif", "%", "high"),
    ("cs10_diff", "Écart de CS à 10 min (lanes)", "", "high"),
    ("wards", "Wards posées (équipe)", "/ partie", "high"),
    ("pinks", "Pinks achetées (équipe)", "/ partie", "high"),
    ("antiheal", "Anti-heal acheté quand nécessaire", "%", "high"),
    ("first_death", "Première mort", "min", "high"),
]
LANES = ("Top", "Mid", "ADC")


def _ind_games(games):
    return [g for g in games if g.get("ind")]


def key_indicators(games):
    gs = _ind_games(games)
    if not gs:
        return None
    tl = [g for g in gs if g["ind"]["team"]["deaths15"] is not None]
    won = sum(g["ind"]["team"]["fights_won"] or 0 for g in tl)
    conv = sum(g["ind"]["team"]["converted"] or 0 for g in tl)
    cs = [g["ind"]["players"][r]["cs10_diff"] for g in tl for r in LANES
          if r in g["ind"]["players"] and g["ind"]["players"][r]["cs10_diff"] is not None]
    need = [g for g in gs if g["ind"]["team"]["antiheal_needed"]]
    fd = [g["ind"]["team"]["first_death"] for g in tl if g["ind"]["team"]["first_death"] is not None]
    tf = sum(g["ind"]["team"].get("tf") or 0 for g in tl)
    tf_won = sum(g["ind"]["team"].get("tf_won") or 0 for g in tl)
    tf_out = sum(g["ind"]["team"].get("tf_outnumbered") or 0 for g in tl)
    vals = {
        "tf_wr": round(100 * tf_won / tf) if tf else None,
        "tf_outnumbered": round(100 * tf_out / tf) if tf else None,
        "deaths15": _avg([g["ind"]["team"]["deaths15"] for g in tl], 1),
        "conversion": round(100 * conv / won) if won else None,
        "cs10_diff": _avg(cs, 1),
        "wards": _avg([g["ind"]["team"]["wards"] for g in gs], 1),
        "pinks": _avg([g["ind"]["team"]["pinks"] for g in gs], 1),
        "antiheal": round(100 * sum(g["ind"]["team"]["antiheal_bought"] for g in need) / len(need)) if need else None,
        "first_death": _avg(fd, 1),
    }
    extra = {"games": len(gs), "fights_won": won, "converted": conv,
             "antiheal_needed": len(need), "antiheal_bought": sum(g["ind"]["team"]["antiheal_bought"] for g in need)}
    return {"values": vals, **extra}


def indicator_rows(cur, ref=None, defs=KEY_INDICATORS):
    """Lignes prêtes à afficher : valeur, référence, et si c'est mieux / moins bien."""
    if not cur:
        return []
    rows = []
    for key, label, unit, better in defs:
        v = cur["values"].get(key)
        r = ref["values"].get(key) if ref else None
        status = ""
        if v is not None and r is not None and v != r:
            status = "good" if (v > r) == (better == "high") else "bad"
        rows.append({"key": key, "label": label, "unit": unit, "value": v, "ref": r,
                     "status": status, "better": better})
    return rows


def indicator_trend(sessions):
    """Valeur de chaque indicateur clé, soirée par soirée (pour les mini-graphiques)."""
    out = {k: [] for k, *_ in KEY_INDICATORS}
    for s in sessions:
        ki = key_indicators(s["games"])
        for k in out:
            out[k].append({"date": s["date"], "value": ki["values"][k] if ki else None})
    return out


def teamfight_stats(games):
    """Teamfights : bilan, infériorité numérique, qui meurt en premier, menaces adverses."""
    gs = [g for g in _ind_games(games) if g["ind"]["team"].get("tf") is not None]
    if not gs:
        return None
    t = lambda k: sum(g["ind"]["team"].get(k) or 0 for g in gs)
    total, won, lost = t("tf"), t("tf_won"), t("tf_lost")
    first_dead, threats = Counter(), Counter()
    per_player = defaultdict(lambda: {"tf": 0, "first": 0, "dmg": 0})
    team_dmg = 0
    for g in gs:
        names = {p["role"]: p.get("player") or p["role"] for p in g["our"]}
        subs = {p["role"] for p in g["our"] if p.get("sub")}
        for role, n in g["ind"]["team"]["tf_first_dead"].items():
            first_dead[(names.get(role, role), role)] += n
        threats.update(g["ind"]["team"].get("killers_dmg", {}))
        for role, pl in g["ind"]["players"].items():
            team_dmg += pl.get("tf_dmg", 0)
            if role in subs:
                continue
            pp = per_player[(names.get(role, role), role)]
            pp["tf"] += pl.get("tf", 0)
            pp["first"] += pl.get("tf_first_death", 0)
            pp["dmg"] += pl.get("tf_dmg", 0)
    order = {r: i for i, r in enumerate(ROLES)}
    players = [{"player": who, "role": role,
                "presence": round(100 * v["tf"] / total) if total else None,
                "first_death": v["first"],
                "first_death_pct": round(100 * v["first"] / lost) if lost else None,
                "dmg_share": round(100 * v["dmg"] / team_dmg) if team_dmg else None}
               for (who, role), v in per_player.items()]
    return {
        "games": len(gs), "total": total, "per_game": round(total / len(gs), 1),
        "summary": rec(won + lost, won),
        "outnumbered": {**rec(t("tf_outnumbered"), t("tf_outnumbered_won")),
                        "pct": round(100 * t("tf_outnumbered") / total) if total else None},
        "players": sorted(players, key=lambda p: order.get(p["role"], 9)),
        "first_dead_total": sum(first_dead.values()),
        "threats": [{"champion": c, "damage": d} for c, d in threats.most_common(8)],
    }


def player_details(games):
    acc = defaultdict(lambda: defaultdict(list))
    roles = {}
    for g in _ind_games(games):
        names = {p["role"]: p.get("player") for p in g["our"]}
        subs = {p["role"] for p in g["our"] if p.get("sub")}
        for role, pl in g["ind"]["players"].items():
            if role in subs:
                continue
            who = names.get(role) or role
            roles[who] = role
            for k, v in pl.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None:
                    acc[who][k].append(v)
            acc[who]["games"].append(1)
    order = {r: i for i, r in enumerate(ROLES)}
    rows = []
    for who, d in acc.items():
        row = {"player": who, "role": roles[who], "games": len(d["games"])}
        for k in ("wards", "wards_killed", "pinks", "kp", "tank_min", "cc", "solo_kills", "plates",
                  "deaths15", "cs10", "cs10_diff", "first_item_min"):
            row[k] = _avg(d[k], 1)
        rows.append(row)
    return sorted(rows, key=lambda r: order.get(r["role"], 9))


def build_stats(games, min_games=2):
    """Par champion : premier objet légendaire acheté -> winrate et minute moyenne."""
    acc = defaultdict(lambda: defaultdict(list))
    for g in _ind_games(games):
        for p in g["our"]:
            pl = g["ind"]["players"].get(p["role"])
            if pl and pl["first_item"]:
                acc[(p["role"], p["champion"])][pl["first_item"]].append((g["win"], pl["first_item_min"]))
    out = []
    for (role, champ), by_item in acc.items():
        total = sum(len(v) for v in by_item.values())
        if total < min_games:
            continue
        rows = sorted(({"item": it, **rec(len(v), sum(w for w, _ in v)),
                        "minute": _avg([m for _, m in v if m], 1)} for it, v in by_item.items()),
                      key=lambda x: -x["games"])
        out.append({"role": role, "champion": champ, "games": total, "items": rows[:3]})
    order = {r: i for i, r in enumerate(ROLES)}
    return sorted(out, key=lambda x: (order[x["role"]], -x["games"]))


def composition_stats(games):
    buckets = [(0, 25, "Très AD (< 25 % de dégâts magiques)"), (25, 60, "Mixte"),
               (60, 101, "Très AP (> 60 % de dégâts magiques)")]
    gs = [g for g in _ind_games(games) if g["ind"]["team"]["ap_share"] is not None]
    out = []
    for lo, hi, label in buckets:
        b = [g for g in gs if lo <= g["ind"]["team"]["ap_share"] < hi]
        out.append({"label": label, **rec(len(b), sum(g["win"] for g in b))})
    return out if gs else []


def tilt_stats(sessions):
    after = {"win": [0, 0], "loss": [0, 0]}
    for s in sessions:
        for prev, cur in zip(s["games"], s["games"][1:]):
            k = after["win" if prev["win"] else "loss"]
            k[0] += 1
            k[1] += cur["win"]
    return [{"label": "Après une victoire", **rec(*after["win"])},
            {"label": "Après une défaite", **rec(*after["loss"])}]


def zone_stats(games):
    deaths = [d for g in _ind_games(games) for d in g["ind"]["map"]["deaths"]]
    if not deaths:
        return None
    total = len(deaths)
    rows = []
    for z in ["Base", "Top lane", "Mid lane", "Bot lane", "Rivière", "Notre jungle", "Jungle adverse"]:
        early = sum(1 for d in deaths if d["zone"] == z and d["t"] < 900)
        late = sum(1 for d in deaths if d["zone"] == z and d["t"] >= 900)
        if early + late:
            rows.append({"zone": z, "count": early + late, "pct": round(100 * (early + late) / total),
                         "early": early, "late": late})
    return {"total": total, "rows": sorted(rows, key=lambda r: -r["count"])}


def map_data(games, with_jungle=False):
    """Points à dessiner sur la mini-map (coordonnées Riot, ramenées côté bleu si besoin)."""
    out = {"deaths": [], "kills": [], "objectives": [], "jungle": []}
    for i, g in enumerate(_ind_games(games), 1):
        names = {p["role"]: p.get("player") or p["role"] for p in g["our"]}
        m = g["ind"]["map"]
        for d in m["deaths"]:
            out["deaths"].append([d["x"], d["y"], d["t"], d["role"], names.get(d["role"], d["role"]), i])
        for k in m["kills"]:
            out["kills"].append([k["x"], k["y"], k["t"], k["role"], names.get(k["role"], k["role"]), i])
        if with_jungle and m["jungle"]:
            out["jungle"].append({"game": i, "win": g["win"], "blue": g["ind"]["blue"],
                                  "path": [[p["x"], p["y"], p["m"]] for p in m["jungle"]]})
    return out


def form_stats(sessions, last=6):
    """KDA et CS/min de chaque joueur sur les dernières soirées (repérer une baisse de forme)."""
    rows = defaultdict(dict)
    dates = [s["date"] for s in sessions[-last:]]
    for s in sessions[-last:]:
        for p in player_stats(s["games"]):
            rows[p["player"]][s["date"]] = {"kda": p["kda"], "cs_min": p["cs_min"], "games": p["games"]}
    return {"dates": dates, "players": dict(rows)}


def game_line(g):
    """Résumé compact d'une partie pour sa carte : quelques indicateurs clés."""
    ind = g.get("ind")
    if not ind:
        return None
    t = ind["team"]
    return {"deaths15": t["deaths15"], "wards": t["wards"], "pinks": t["pinks"],
            "fights": f"{t['converted']}/{t['fights_won']}" if t["fights_won"] is not None else None,
            "tf": f"{t['tf_won']}/{t['tf']}" if t.get("tf") else None,
            "tf_outnumbered": t.get("tf_outnumbered"),
            "antiheal": (t["antiheal_bought"] if t["antiheal_needed"] else None),
            "healers": t["enemy_healers"], "ap_share": t["ap_share"]}


# =================================================================== page Joueurs
# Indicateurs propres à chaque rôle : (clé, libellé, unité, sens)
_LANE15 = ("lane15", "Or vs vis-à-vis à 15 min", "", "high")
_CS10 = ("cs10_diff", "Écart de CS à 10 min", "", "high")
_KP = ("kp", "Participation aux kills", "%", "high")
_D15 = ("deaths15", "Morts avant 15 min", "/ partie", "low")
_DEATHS = ("deaths", "Morts", "/ partie", "low")
_SOLO = ("solo_kills", "Solo kills", "/ partie", "high")
_CSMIN = ("cs_min", "CS", "/ min", "high")
_DMGPCT = ("dmg_pct", "Part des dégâts de l'équipe", "%", "high")
_VISION = ("vision_min", "Score de vision", "/ min", "high")
_PINKS = ("control_wards", "Pinks posées", "/ partie", "high")
ROLE_METRICS = {
    "Top": [_LANE15, _CS10, _SOLO, ("plates", "Plaques de tour prises", "/ partie", "high"),
            ("tank_min", "Dégâts encaissés + atténués", "/ min", "high"),
            ("turret_dmg_min", "Dégâts aux tours", "/ min", "high"), _D15, _KP],
    "Jungle": [_KP, ("epic", "Objectifs épiques (dragon, Héraut, Nashor)", "/ partie", "high"),
               ("jg_cs10", "CS de jungle avant 10 min", "", "high"),
               ("enemy_jg", "Camps pris dans la jungle adverse", "/ partie", "high"),
               ("scuttles", "Carapateurs", "/ partie", "high"), _VISION, _PINKS, _D15],
    "Mid": [_LANE15, _CS10, _CSMIN, _DMGPCT,
            ("roam_kills", "Kills sur d'autres lanes (début de partie)", "/ partie", "high"), _SOLO, _D15, _KP],
    "ADC": [_CSMIN, _CS10, ("dmg_min", "Dégâts aux champions", "/ min", "high"), _DMGPCT, _DEATHS,
            ("dead_pct", "Temps passé mort", "%", "low"),
            ("tf_first_death", "1er mort d'un teamfight perdu", "/ partie", "low"), _LANE15],
    "Support": [_VISION, _PINKS, ("ward_kills", "Wards détruites", "/ partie", "high"),
                ("vision_adv", "Vision vs support adverse", "%", "high"),
                ("immobilize", "Immobilisations d'adversaires", "/ partie", "high"), _KP, _DEATHS, _D15],
}


def player_game_metrics(g, p):
    """Toutes les mesures d'un joueur sur une partie (stats de base + indicateurs avancés)."""
    if "kills" not in p:
        return {}
    dur = max(g["duration_min"], 1)
    m = {"kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
         "cs_min": round(p["cs"] / dur, 1), "dmg_min": round(p["damage"] / dur),
         "vision_min": round(p["vision"] / dur, 2)}
    team_dmg = sum(q.get("damage", 0) for q in g["our"])
    if team_dmg:
        m["dmg_pct"] = round(100 * p["damage"] / team_dmg)
    lane = g.get("early", {}).get("15", {}).get("lanes", {}).get(p["role"])
    if lane:
        m["lane15"] = lane["gold"]
    ind = (g.get("ind") or {}).get("players", {}).get(p["role"])
    for k, v in (ind or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in m:
            m[k] = round(v, 2) if isinstance(v, float) else v
    return m


def _agg(pairs):
    """Moyenne de chaque mesure sur une liste de (partie, joueur, mesures) ; KDA en ratio."""
    acc = defaultdict(list)
    for _, _, m in pairs:
        for k, v in m.items():
            if v is not None:
                acc[k].append(v)
    out = {k: _avg(v, 2 if k == "vision_min" else 1) for k, v in acc.items()}
    out = {k: round(v) if abs(v) >= 100 else v for k, v in out.items()}  # or, dégâts : à l'unité
    if acc["kills"]:
        out["kda"] = round((sum(acc["kills"]) + sum(acc["assists"])) / max(sum(acc["deaths"]), 1), 2)
    return out


def _profile(pairs):
    gs = [g for g, _, _ in pairs]
    return {**rec(len(gs), sum(g["win"] for g in gs)), **_agg([x for x in pairs if x[2]])}


def player_report(who, games, sessions, cfg):
    mine = [(g, p, player_game_metrics(g, p)) for g in games for p in g["our"] if p.get("player") == who]
    if not mine:
        return None
    role = Counter(p["role"] for _, p, _ in mine).most_common(1)[0][0]
    defs = ROLE_METRICS.get(role, [])
    last_s = sessions[-1] if sessions else None
    last_ids = {g["match_id"] for g in last_s["games"]} if last_s else set()
    last = [x for x in mine if x[0]["match_id"] in last_ids]
    detailed = [x for x in mine if x[2]]
    cur, ref = _agg(last), _agg(detailed)

    by_session = {s["date"]: {g["match_id"] for g in s["games"]} for s in sessions}
    trend = {k: [] for k, *_ in defs}
    for date, ids in by_session.items():
        vals = _agg([x for x in mine if x[0]["match_id"] in ids])
        for k in trend:
            trend[k].append({"date": date, "value": vals.get(k)})

    champs = defaultdict(list)
    opps = defaultdict(list)
    for x in mine:
        champs[x[1]["champion"]].append(x)
        opp = by_role(x[0], x[1]["role"], "enemy")
        if opp:
            opps[opp["champion"]].append(x)
    champions = sorted(({"champion": c, **_profile(v)} for c, v in champs.items()),
                       key=lambda c: (-c["games"], -c["wr"]))
    matchups = sorted(({"champion": c, **_profile(v)} for c, v in opps.items() if len(v) >= 2),
                      key=lambda c: (c["wr"], c.get("lane15") or 0))

    last_games = []
    for g, p, m in last:
        opp = by_role(g, p["role"], "enemy")
        last_games.append({"match_id": g["match_id"], "start_utc": g["start_utc"], "win": g["win"],
                           "duration_min": g["duration_min"], "champion": p["champion"],
                           "opponent": opp["champion"] if opp else None, "m": m})

    ids = {g["match_id"] for g, _, _ in mine}
    mp = map_data([g for g in games if g["match_id"] in ids])
    mp = {k: [d for d in v if d[4] == who] if k in ("deaths", "kills") else v for k, v in mp.items()}
    return {
        "player": who, "role": role, "defs": defs,
        "profile": _profile(mine), "last_profile": _profile(last) if last else None,
        "last_date": last_s["date"] if last_s else None,
        "rows": indicator_rows({"values": cur}, {"values": ref}, defs) if last else
                indicator_rows({"values": ref}, None, defs),
        "trend": trend, "champions": champions, "matchups": matchups[:6],
        "last_games": last_games, "pool": cfg.get("champion_pools", {}).get(role, []),
        "map": mp, "has_map": bool(mp["deaths"] or mp["kills"]),
    }


def player_reports(games, sessions, cfg):
    names = {p["player"] for g in games for p in g["our"] if p.get("player") and not p.get("sub")}
    reps = [r for r in (player_report(n, games, sessions, cfg) for n in names) if r]
    order = {r: i for i, r in enumerate(ROLES)}
    return sorted(reps, key=lambda r: (order.get(r["role"], 9), r["player"]))


# =================================================================== hors soirées
def _out_profile(recs):
    """Bilan d'une liste de fiches hors soirée (même format que player_stats)."""
    n = len(recs)
    if not n:
        return rec(0, 0)
    mins = sum(r["duration_min"] for r in recs) or 1
    k, d, a = (sum(r[x] for r in recs) for x in ("kills", "deaths", "assists"))
    return {**rec(n, sum(r["win"] for r in recs)),
            "kda": round((k + a) / max(d, 1), 2),
            "kills": round(k / n, 1), "deaths": round(d / n, 1), "assists": round(a / n, 1),
            "cs_min": round(sum(r["cs"] for r in recs) / mins, 1),
            "damage_min": round(sum(r["damage"] for r in recs) / mins),
            "vision_min": round(sum(r["vision"] for r in recs) / mins, 2),
            "kp": _avg([r["kp"] for r in recs]),
            "dmg_share": _avg([r["dmg_pct"] for r in recs if r.get("dmg_pct") is not None])}


def outside_report(records, games, cfg, tz="Europe/Paris", weeks=8):
    """Parties jouées sans le groupe : volume, files, rôles, champions (dans le pool ou non),
    comparaison avec les soirées, et partenaires de l'équipe."""
    pools = cfg.get("champion_pools", {})
    team = {p["player"]: p for p in player_stats(games)}
    team_champs = defaultdict(set)
    for g in games:
        for p in g["our"]:
            if p.get("player") and not p.get("sub"):
                team_champs[p["player"]].add(p["champion"].lower())
    now = datetime.now(ZoneInfo(tz)).date()
    week0 = now - timedelta(days=now.weekday())
    week_starts = [week0 - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    out = []
    for pl in cfg["players"]:
        who, role = pl["riot_id"].split("#")[0], pl["role"]
        mine = [r for r in records if r["player"] == who]
        pool = {_norm(c) for c in pools.get(role, [])}
        by = lambda key: sorted(({"key": k, **_out_profile(v)} for k, v in _group(mine, key).items()),
                                key=lambda x: -x["games"])
        champs = []
        for c, v in _group(mine, lambda r: r["champion"]).items():
            champs.append({"champion": c, **_out_profile(v),
                           "roles": Counter(r["role"] for r in v).most_common(1)[0][0],
                           "in_pool": _norm(c) in pool,
                           "in_team": c.lower() in team_champs[who]})
        champs.sort(key=lambda c: (-c["games"], -c["wr"]))
        weekly = []
        for ws in week_starts:
            wk = [r for r in mine if ws <= local_dt(r, tz).date() < ws + timedelta(days=7)]
            weekly.append({"date": ws.isoformat(), "value": len(wk), **rec(len(wk), sum(r["win"] for r in wk))})
        on_role = [r for r in mine if r["role"] == role]
        pool_games = [r for r in on_role if _norm(r["champion"]) in pool]
        mates = by(lambda r: " + ".join(r["mates"]) if r["mates"] else "Sans l'équipe")
        out.append({
            "player": who, "role": role,
            "profile": _out_profile(mine),
            "profile_role": _out_profile(on_role),
            "team": team.get(who),
            "queues": by(lambda r: r["queue"]),
            "roles": by(lambda r: r["role"] or "?"),
            "mates": mates,
            "champions": champs,
            "role_pct": round(100 * len(on_role) / len(mine)) if mine else None,
            "pool_pct": round(100 * len(pool_games) / len(on_role)) if on_role else None,
            # pistes pour le pool : champions joués sur son rôle, hors pool, avec un bon bilan
            "candidates": [c for c in champs if not c["in_pool"] and c["roles"] == role
                           and c["games"] >= 3 and c["wr"] >= 55],
            "weekly": weekly,
            "recent": [{**r, "local": local_dt(r, tz).strftime("%d/%m %H:%M")}
                       for r in sorted(mine, key=lambda r: r["start_utc"], reverse=True)[:10]],
        })
    order = {r: i for i, r in enumerate(ROLES)}
    out.sort(key=lambda r: order.get(r["role"], 9))
    total = {r["match_id"] for r in records}
    return {"players": out, "games": len(total), "records": len(records),
            "weeks": [w.isoformat() for w in week_starts]}


def _norm(champ):
    """« Dr. Mundo » (config) et « DrMundo » (Riot) -> « drmundo »."""
    return "".join(c for c in champ.lower() if c.isalnum())


def _group(recs, key):
    out = defaultdict(list)
    for r in recs:
        out[key(r)].append(r)
    return out
