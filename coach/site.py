"""Génération du site statique (dossier site/) : page globale + une page par session."""
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import ROLES, ai, explorer, indicators, insights, stats, store

OUT = Path("site")
TEMPLATES = Path(__file__).parent / "templates"
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def fr_date(iso):
    d = date.fromisoformat(iso)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def num(v, nd=1):
    """Nombre lisible : 12.0 -> 12, 3.45 -> 3.5 (sans couper les zéros d'un entier)."""
    if v is None:
        return "—"
    if isinstance(v, float):
        txt = f"{v:.{nd}f}"
        return txt.rstrip("0").rstrip(".") if "." in txt else txt
    return str(v)


def signed(v):
    """+1 200 / −56 ; petites valeurs avec une décimale (+0.4)."""
    if v is None:
        return "—"
    if isinstance(v, float) and abs(v) < 10 and round(v) != v:
        return f"{v:+.1f}"
    return f"{round(v):+,}".replace(",", " ")


def ai_flags():
    errs = ai.STATUS["errors"]
    on = ai.STATUS["enabled"] or bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    return {"ai_on": on, "ai_error": errs[-1][:200] if errs else ""}


def plan_ai(sessions, ia_sessions):
    """Quelles soirées reçoivent un débrief IA lors de ce passage.

    nouvelles : seulement la dernière soirée, si elle n'a pas encore de débrief (défaut)
    derniere  : refaire le débrief de la dernière soirée (même s'il existe)
    toutes    : toutes les soirées sans débrief (rattrapage, dans la limite du plafond)
    aucune    : aucun appel IA pour les sessions
    """
    dates = [s["date"] for s in sessions]
    if not dates or ia_sessions == "aucune":
        return set()
    if ia_sessions == "derniere":
        return {dates[-1]}
    if ia_sessions == "toutes":
        return {d for d in reversed(dates) if not ai.load("session", d)}
    return {dates[-1]} if not ai.load("session", dates[-1]) else set()


def build(games, cfg, champs, warning=None, ia_sessions="nouvelles", ia_global=False):
    if not games:
        print("Aucune partie : rien à générer.")
        return
    tz, cutoff = cfg.get("timezone", "Europe/Paris"), cfg.get("session_cutoff_hour", 6)
    items, n_ind = indicators.attach(games, champs)
    ai.ITEM_NAMES.update({k: v["name"] for k, v in items.data.items()})
    print(f"Indicateurs avancés : {n_ind} partie(s) avec données détaillées.")
    sessions = stats.split_sessions(games, tz, cutoff)
    grep = stats.global_report(games, sessions, cfg)
    name = champs.name

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape())
    env.globals.update(name=name, icon=champs.icon, ROLES=ROLES, fr_date=fr_date, item_name=items.name,
                       team=cfg.get("team_name", "Équipe"), min_champ=cfg.get("stats", {}).get("min_games_champion", 4))
    env.filters["wrclass"] = lambda wr: "good" if wr >= 60 else "bad" if wr <= 40 else "mid"
    env.filters["signed"] = signed
    env.filters["signclass"] = lambda v: "" if v is None else "good-t" if v > 0 else "bad-t" if v < 0 else ""
    env.filters["num"] = num
    env.filters["tojs"] = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    env.filters["md"] = lambda text: markdown.markdown(text or "", extensions=["tables"])
    env.filters["localtime"] = lambda iso: stats.local_dt({"start_utc": iso}, tz).strftime("%H:%M")

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "sessions").mkdir(parents=True)
    shutil.copy(TEMPLATES / "style.css", OUT / "style.css")

    # Icônes : téléchargées une fois dans data/icons/, puis copiées avec le site
    used = {p["champion"] for g in games for side in ("our", "enemy") for p in g[side]}
    used |= {c for g in games for c in g.get("our_bans", []) + g.get("enemy_bans", [])}
    ok = champs.fetch_icons(used)
    (OUT / "img").mkdir()
    for f in ok:
        shutil.copy(f, OUT / "img" / f.name)
    print(f"Icônes : {len(ok)}/{len(used)} disponibles.")
    shutil.copy(TEMPLATES / "map.js", OUT / "map.js")
    map_img = store.fetch_map(champs.version)
    if map_img:
        shutil.copy(map_img, OUT / "img" / "map11.png")
    env.globals["map_img"] = "img/map11.png" if map_img else ""

    g_ai = ai.load("global")
    if ia_global or (cfg.get("ai", {}).get("global_auto") and not g_ai):
        print("Analyse IA globale…")
        text = ai.global_analysis(grep, cfg, name)
        if text:
            g_ai = ai.save("global", text, games=len(games))
    todo = plan_ai(sessions, ia_sessions)
    # La plus récente d'abord, pour qu'elle passe avant le plafond d'appels
    for s in sorted(sessions, key=lambda x: x["date"], reverse=True):
        if s["date"] in todo:
            limit = int(cfg.get("ai", {}).get("max_calls_per_run", 3))
            if ai.STATUS["calls"] >= limit:
                print(f"[info] Plafond de {limit} appel(s) IA atteint : les autres soirées "
                      "seront faites au prochain lancement « toutes ».")
                break
            print(f"Débrief IA de la session du {s['date']}…")
            text = ai.session_analysis(stats.session_report(s, games, cfg), grep, cfg, name)
            if text:
                ai.save("session", text, s["date"], games=len(s["games"]))
    print(f"Appels IA effectués lors de ce passage : {ai.STATUS['calls']}")
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")

    session_pages = []
    for i, s in enumerate(sessions):
        srep = stats.session_report(s, games, cfg)
        s_ai = ai.load("session", s["date"])
        prev_s = sessions[i - 1]["date"] if i > 0 else None
        next_s = sessions[i + 1]["date"] if i + 1 < len(sessions) else None
        html = env.get_template("session.html").render(
            r=srep, ai_text=s_ai, notes=insights.session_insights(srep, name),
            prev=prev_s, next=next_s, generated=generated, root="../", **ai_flags())
        (OUT / "sessions" / f"{s['date']}.html").write_text(html, encoding="utf-8")
        session_pages.append({**grep["sessions"][i]})

    # Explorateur : toutes les stats par joueur et par partie
    session_of = {g["match_id"]: s["date"] for s in sessions for g in s["games"]}
    data = explorer.build_dataset(games, session_of, name)
    html = env.get_template("explorer.html").render(
        data_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
        n_rows=len(data["rows"]), n_games=n_ind, generated=generated, root="")
    (OUT / "explorer.html").write_text(html, encoding="utf-8")

    html = env.get_template("index.html").render(
        r=grep, ai_text=g_ai, ins=insights.global_insights(grep, name),
        sessions=list(reversed(session_pages)), last=session_pages[-1],
        generated=generated, warning=warning, root="", **ai_flags())
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"Site généré dans {OUT}/ ({len(sessions)} sessions, {len(games)} parties).")
