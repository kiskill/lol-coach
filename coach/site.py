"""Génération du site statique (dossier site/) : page globale + une page par session."""
import shutil
from datetime import date, datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import ROLES, ai, insights, stats

OUT = Path("site")
TEMPLATES = Path(__file__).parent / "templates"
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def fr_date(iso):
    d = date.fromisoformat(iso)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def build(games, cfg, champs, warning=None):
    if not games:
        print("Aucune partie : rien à générer.")
        return
    tz, cutoff = cfg.get("timezone", "Europe/Paris"), cfg.get("session_cutoff_hour", 6)
    sessions = stats.split_sessions(games, tz, cutoff)
    grep = stats.global_report(games, sessions, cfg)
    name = champs.name

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape())
    env.globals.update(name=name, icon=champs.icon, ROLES=ROLES, fr_date=fr_date,
                       team=cfg.get("team_name", "Équipe"), min_champ=cfg.get("stats", {}).get("min_games_champion", 4))
    env.filters["wrclass"] = lambda wr: "good" if wr >= 60 else "bad" if wr <= 40 else "mid"
    env.filters["md"] = lambda text: markdown.markdown(text or "", extensions=["tables"])
    env.filters["localtime"] = lambda iso: stats.local_dt({"start_utc": iso}, tz).strftime("%H:%M")

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "sessions").mkdir(parents=True)
    shutil.copy(TEMPLATES / "style.css", OUT / "style.css")

    print("Analyse IA globale…")
    g_ai = ai.global_analysis(grep, cfg, name)
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")

    session_pages = []
    for i, s in enumerate(sessions):
        srep = stats.session_report(s, games, cfg)
        print(f"Session du {s['date']}…")
        s_ai = ai.session_analysis(srep, grep, cfg, name)
        prev_s = sessions[i - 1]["date"] if i > 0 else None
        next_s = sessions[i + 1]["date"] if i + 1 < len(sessions) else None
        html = env.get_template("session.html").render(
            r=srep, ai_text=s_ai, notes=insights.session_insights(srep, name),
            prev=prev_s, next=next_s, generated=generated, root="../")
        (OUT / "sessions" / f"{s['date']}.html").write_text(html, encoding="utf-8")
        session_pages.append({**grep["sessions"][i]})

    html = env.get_template("index.html").render(
        r=grep, ai_text=g_ai, ins=insights.global_insights(grep, name),
        sessions=list(reversed(session_pages)), last=session_pages[-1],
        generated=generated, warning=warning, root="")
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"Site généré dans {OUT}/ ({len(sessions)} sessions, {len(games)} parties).")
