"""Constats automatiques (sans IA) : toujours disponibles, même sans clé IA."""


def _fmt(r):
    return f"{r['wins']}/{r['games']}, {r['wr']} %"


def global_insights(rep, name):
    th = rep["thresholds"]
    mc, md = th.get("min_games_champion", 4), th.get("min_games_duo", 3)
    s = rep["summary"]
    good, bad, notes = [], [], []

    notes.append(f"Bilan : {s['wins']} victoires sur {s['games']} parties ({s['wr']} %), "
                 f"durée moyenne {s['avg_duration']} min.")

    for role, rows in rep["champions"].items():
        for c in rows:
            if c["games"] >= mc and c["wr"] >= 60:
                good.append(f"{name(c['champion'])} ({role}) : {_fmt(c)}")
            if c["games"] >= mc and c["wr"] <= 40:
                bad.append(f"{name(c['champion'])} ({role}) : {_fmt(c)}")

    for duo in rep["duos"]:
        rows = [r for r in duo["rows"] if r["games"] >= md]
        if rows:
            best = max(rows, key=lambda r: (r["wr"], r["games"]))
            worst = min(rows, key=lambda r: (r["wr"], -r["games"]))
            if best["wr"] >= 60:
                good.append(f"{duo['label']} {name(best['pair'][0])} + {name(best['pair'][1])} : {_fmt(best)}")
            if worst["wr"] <= 40 and worst is not best:
                bad.append(f"{duo['label']} {name(worst['pair'][0])} + {name(worst['pair'][1])} : {_fmt(worst)}")

    hard = [e for e in rep["enemies"]["hardest"] if e["wr"] <= 25]
    if hard:
        bad.append("Adversaires difficiles : " + ", ".join(
            f"{name(e['champion'])} ({_fmt(e)})" for e in hard[:5]))

    sess = rep["sessions"]
    if len(sess) >= 4:
        recent = sess[-3:]
        w, n = sum(x["wins"] for x in recent), sum(x["games"] for x in recent)
        wr = round(100 * w / n) if n else 0
        trend = "en hausse" if wr > s["wr"] + 5 else "en baisse" if wr < s["wr"] - 5 else "stable"
        notes.append(f"Tendance sur les 3 dernières sessions : {w}/{n} ({wr} %), {trend} "
                     f"par rapport à la moyenne.")

    early = rep.get("early")
    if early and early["games"] >= 3:
        notes.append(f"Écart d'or moyen : {early['gold10']:+} à 10 min, {early['gold15']:+} à 15 min.")
        lanes = [l for l in early["lanes"] if l["gold15"] is not None and l["games"] >= 3]
        if lanes:
            best = max(lanes, key=lambda l: l["gold15"])
            worst = min(lanes, key=lambda l: l["gold15"])
            if best["gold15"] > 300:
                good.append(f"Phase de lane {best['role']} : {best['gold15']:+} or à 15 min en moyenne "
                            f"({best['won_pct']} % de lanes gagnées)")
            if worst["gold15"] < -300:
                bad.append(f"Phase de lane {worst['role']} : {worst['gold15']:+} or à 15 min en moyenne "
                           f"({worst['won_pct']} % de lanes gagnées)")
        if early["throws"]:
            bad.append(f"{len(early['throws'])} partie(s) perdue(s) malgré +1 500 or d'avance à 15 min "
                       "(problème de conversion de l'avance)")
        if early["comebacks"]:
            good.append(f"{len(early['comebacks'])} comeback(s) après −1 500 or à 15 min")

    idx = [g for g in rep["game_index"] if g["games"] >= 4]
    if idx:
        low = min(idx, key=lambda g: g["wr"])
        if low["wr"] <= s["wr"] - 15:
            notes.append(f"Creux sur la {low['label'].lower()} de la soirée : {_fmt(low)}.")

    return {"good": good, "bad": bad, "notes": notes}


def session_insights(rep, name):
    s = rep["summary"]
    notes = [f"Soirée à {s['wins']} victoire(s) sur {s['games']} ({s['wr']} %)."]
    risky = [p for p in rep["picks"]
             if p["global"] and p["global"]["games"] >= 4 and p["global"]["wr"] <= 40]
    for p in risky:
        notes.append(f"{name(p['champion'])} ({p['role']}) joué alors que son bilan global "
                     f"est faible ({p['global']['wins']}/{p['global']['games']}).")
    players = rep["players"]
    if players:
        best = max(players, key=lambda p: p["kda"])
        notes.append(f"Meilleur KDA de la soirée : {best['player']} ({best['kda']}).")
    return notes
