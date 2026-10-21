"""Analyse texte par IA (API Claude d'Anthropic).

Chaque texte est généré UNE fois puis conservé dans data/ai/ :
  data/ai/global.json             -> bilan global (regénéré seulement sur demande)
  data/ai/sessions/AAAA-MM-JJ.json -> débrief d'une soirée (généré une fois)
  data/ai/players/AAAA-MM-JJ.json  -> analyse par joueur de cette soirée (un seul appel pour les 5)
Les relances, pushs ou redéploiements réutilisent ces fichiers sans rien payer.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

from .stats import rank_label

STORE = Path("data/ai")
API_URL = "https://api.anthropic.com/v1/messages"
PROMPT_VERSION = "v3"
# État de l'IA pour l'affichage : désactivée (pas de clé) ou en erreur
STATUS = {"enabled": False, "errors": [], "calls": 0}

SYSTEM = """Tu es le coach d'une équipe amateur de League of Legends. Tu écris en français, \
de façon directe, bienveillante (ou pas) et concrète, pour l'équipe et son coach. Règles :
- Le lecteur a DÉJÀ sous les yeux tous les chiffres (tableaux, graphiques). Ne les recopie pas : \
pas d'inventaire de statistiques, pas de listes de winrates ou de KDA. Les données te servent à \
poser un diagnostic, pas à être répétées.
- Cite un chiffre seulement s'il est indispensable pour comprendre un point, et au maximum un par paragraphe.
- Explique le POURQUOI (cause probable dans le jeu : décisions, placement, timings, communication, \
gestion des vagues, priorités d'objectifs, mental) et le COMMENT (ce qu'il faut faire différemment, \
en jeu, dès la prochaine partie).
- Chaque conseil doit être actionnable : une consigne claire, un réflexe à prendre, un exercice ou \
une routine (ex. « au retour base après le 1er objet, le jungler ping la prochaine cible »).
- Priorise : mieux vaut 3 axes de travail bien expliqués que 10 remarques.
- Signale brièvement quand un échantillon est trop petit (moins de 4 parties) pour conclure.
- N'invente aucune donnée absente. Tu peux utiliser tes connaissances du jeu (synergies, contres, \
plans de jeu, champions simples à prendre en main) en le présentant comme du conseil.
- Format : Markdown avec des titres ## et des listes courtes. Pas de tableau."""

GLOBAL_TASK = """Voici les données globales de l'équipe. Rédige un bilan de coaching \
(450 à 700 mots), centré sur ce que l'équipe doit travailler, avec ces sections :
## Notre identité de jeu (le plan de jeu qui nous réussit et comment le jouer volontairement)
## Ce qu'il faut garder (2-3 points forts et pourquoi ils marchent)
## Les 3 axes de travail prioritaires
Pour chacun : le problème en une phrase, sa cause probable dans le jeu, puis la consigne ou \
l'exercice pour le corriger (qui fait quoi, à quel moment). Appuie-toi sur toutes les données \
fournies (phase de lane, conversion d'avance, teamfights, vision, morts, objectifs, rangs adverses) \
pour choisir les axes, sans les passer en revue une par une.
## Draft (2-3 principes de draft pour cette équipe, bans prioritaires, picks qui servent notre plan de jeu)
## Élargir les champ-pools (1-2 champions par rôle, simples ou proches des pools actuels, et pourquoi)
## Mental et communication (seulement si les données le suggèrent : tilt, fin de soirée, throws)
## Plan pour les prochaines sessions (un objectif de jeu par session, formulé comme une consigne)"""

SESSION_TASK = """Voici le détail de la dernière soirée de jeu, avec le bilan global pour \
comparaison. Rédige un débrief de session (200 à 400 mots), comme un coach qui parle à son équipe \
après la soirée, avec ces sections :
## La soirée en bref (2-3 phrases : le ressenti général et le fil rouge, sans liste de résultats)
## Ce qu'on a bien fait (les décisions ou comportements à reproduire)
## Ce qui a coincé (les 2-3 causes principales des défaites, en termes de jeu : draft, lane, \
objectifs, teamfights, vision, morts évitables, mental)
## Focus pour la prochaine fois (2-3 consignes concrètes, dont une à appliquer dès la 1re partie)"""

PLAYERS_TASK = """Voici, pour chaque joueur, sa dernière soirée comparée à ses moyennes \
habituelles, avec les indicateurs propres à son rôle, ses champions et ses vis-à-vis. \
Pour CHAQUE joueur, écris une section qui commence exactement par la ligne `## <joueur>` \
(le nom tel que fourni dans le champ « joueur »), puis :
- un paragraphe de lecture de sa soirée (60 à 110 mots), du point de vue de son rôle : ce que \
ses chiffres révèlent de sa façon de jouer (pas un résumé de ses chiffres) ;
- une ligne **Pour progresser :** suivie de 2 ou 3 conseils personnalisés et concrets (liste à puces), \
formulés comme des consignes à appliquer en jeu (gestes, timings, placement, vision, gestion des vagues, \
communication avec l'équipe), adaptés à son rôle et à ses champions ;
- une ligne **Stuff :** en 1 à 2 phrases, si le champ « équipement » est fourni : un conseil \
d'itémisation concret (build, ordre, adaptation comme l'anti-heal), seulement si les données le justifient ;
- une ligne **Sur la durée :** avec un point de progression de fond tiré de son historique \
(une tendance qui se confirme ou un défaut récurrent) et l'habitude à prendre pour le corriger.
Si le joueur n'a pas joué la dernière soirée, écris une seule phrase pour le dire.
N'écris rien avant la première section ni après la dernière."""


def _compact_game(g, name):
    out = {
        "résultat": "Victoire" if g["win"] else "Défaite",
        "durée_min": g["duration_min"],
        "nous": {p["role"]: name(p["champion"]) for p in g["our"]},
        "adversaires": {p["role"]: name(p["champion"]) for p in g["enemy"]},
    }
    if g.get("our_bans") or g.get("enemy_bans"):
        out["nos_bans"] = [name(c) for c in g.get("our_bans", [])]
        out["bans_adverses"] = [name(c) for c in g.get("enemy_bans", [])]
    if g["our"] and "kills" in g["our"][0]:
        out["kda_joueurs"] = {p["role"]: f"{p['kills']}/{p['deaths']}/{p['assists']}"
                              for p in g["our"]}
    early = g.get("early") or {}
    for m in ("10", "15"):
        if m in early:
            out[f"écart_or_équipe_{m}min"] = early[m]["gold"]
    if "15" in early:
        out["écart_or_couloir_15min"] = {r: v["gold"] for r, v in early["15"]["lanes"].items()}
    if g["our"] and "damage" in g["our"][0]:
        tot = sum(p["damage"] for p in g["our"]) or 1
        out["part_dégâts_%"] = {p["role"]: round(100 * p["damage"] / tot) for p in g["our"]}
    if g.get("objectives", {}).get("dragons"):
        o = g["objectives"]
        out["objectifs"] = {"premier_dragon": o["first_dragon"], "première_tour": o["first_tower"],
                            "dragons": o["dragons"], "barons": o["barons"]}
    return out


ITEM_NAMES = {}


def _item(iid):
    return ITEM_NAMES.get(str(iid), str(iid))


def _tf_payload(tf, name, short=False):
    """Teamfights = au moins 2 morts et 5 champions impliqués. Joueurs impliqués déduits des kills/assists."""
    if not tf:
        return None
    out = {"teamfights": tf["total"], "par_partie": tf["per_game"],
           "gagnés": f"{tf['summary']['wins']}/{tf['summary']['games']}",
           "en_infériorité_numérique": f"{tf['outnumbered']['games']} ({tf['outnumbered']['pct']} %), "
                                       f"dont {tf['outnumbered']['wins']} gagnés"}
    if short:
        return out
    out["premier_mort_des_teamfights_perdus (par joueur)"] = {
        p["player"] + " (" + p["role"] + ")": p["first_death"] for p in tf["players"]}
    out["présence_en_teamfight_%"] = {p["player"]: p["presence"] for p in tf["players"]}
    out["part_des_dégâts_sur_adversaires_tués_%"] = {p["player"]: p["dmg_share"] for p in tf["players"]}
    out["champions_adverses_qui_nous_infligent_le_plus_de_dégâts_avant_nos_morts"] = [
        f"{name(t['champion'])} ({t['damage']})" for t in tf["threats"]]
    return out


def _key_payload(rows):
    if not rows:
        return None
    return [{"indicateur": r["label"], "valeur": r["value"], "unité": r["unit"],
             "référence": r["ref"], "sens": "plus haut = mieux" if r["better"] == "high" else "plus bas = mieux"}
            for r in rows]


def _early_payload(early, name):
    if not early:
        return None
    return {
        "parties_avec_timeline": early["games"],
        "écart_or_moyen_10min": early["gold10"], "écart_or_moyen_15min": early["gold15"],
        "winrate_selon_écart_or_15min": early["states"],
        "throws (perdues avec +1500 à 15 min)": len(early["throws"]),
        "comebacks (gagnées avec -1500 à 15 min)": len(early["comebacks"]),
        "phase_de_lane_par_rôle": early["lanes"],
        "phase_de_lane_par_champion": [
            f"{name(c['champion'])} ({c['role']}) {c['gold15']:+} or à 15 min, {c['wins']}/{c['games']}"
            for c in early["champions"]],
    }


def _rank_payload(rk):
    """Rangs : évolution de l'équipe et niveau des adversaires (rangs en clair)."""
    if not rk or not (rk.get("history") or rk.get("games")):
        return None
    def b(x):
        return f"{x['wins']}/{x['games']}, adversaires {rank_label(x.get('enemy'))}"
    out = {}
    h = rk.get("history")
    if h:
        out["rang_flex_actuel"] = {p["player"]: rank_label(p["score"], lp=True) for p in h["players"]}
        out["rang_moyen_équipe_par_relevé"] = [f"{p['date']} {rank_label(p['value'], lp=True)}"
                                               for p in h["points"][-8:] if p["value"] is not None]
    if rk.get("games"):
        out.update({
            "rang_moyen_nous_vs_adversaires": f"{rank_label(rk['summary']['our'])} vs {rank_label(rk['summary']['enemy'])}",
            "winrate_selon_écart_de_rang": {x["label"]: b(x) for x in rk["by_gap"] if x["games"]},
            "winrate_selon_rang_moyen_adverse": {x["label"]: f"{x['wins']}/{x['games']}" for x in rk["by_tier"]},
            "winrate_selon_rôle_du_meilleur_adversaire": {x["role"]: b(x) for x in rk["top_role"]},
            "parties_avec_un_adversaire_2_divisions_au_dessus_de_notre_meilleur": f"{rk['stomp']['wins']}/{rk['stomp']['games']}",
            "parties_au_rang_approximatif (relevé tardif)": rk["approx"],
        })
    return out


def _global_payload(rep, cfg, name):
    def champs(rows):
        return [f"{name(c['champion'])} {c['wins']}/{c['games']}" for c in rows]
    return {
        "contexte": cfg.get("ai", {}).get("team_context", ""),
        "champ_pools_déclarés": cfg.get("champion_pools", {}),
        "bilan": rep["summary"],
        "champions_par_rôle (victoires/parties)": {r: champs(rows) for r, rows in rep["champions"].items()},
        "duos (victoires/parties)": {d["label"]: [f"{name(r['pair'][0])} + {name(r['pair'][1])} {r['wins']}/{r['games']}"
                                                  for r in d["rows"][:8]] for d in rep["duos"]},
        "adversaires_les_plus_durs": [f"{name(e['champion'])} {e['wins']}/{e['games']}" for e in rep["enemies"]["hardest"]],
        "adversaires_les_plus_faciles": [f"{name(e['champion'])} {e['wins']}/{e['games']}" for e in rep["enemies"]["easiest"]],
        "bans": {"parties_avec_bans_connus": rep["bans"]["games_with_bans"],
                 "nos_bans": [(name(c), n) for c, n in rep["bans"]["our_bans"]],
                 "bans_adverses_contre_nous": [(name(c), n) for c, n in rep["bans"]["enemy_bans"]]},
        "par_durée": rep["durations"],
        "par_rang_dans_la_soirée": rep["game_index"],
        "objectifs": rep["objectives"],
        "objectifs_moyennes (nous, eux)": rep.get("objective_totals"),
        "début_de_partie (écarts nous-eux)": _early_payload(rep.get("early"), name),
        "joueurs": [{k: v for k, v in p.items() if k != "champions"} | {"champions": [(name(c), n) for c, n in p["champions"]]}
                    for p in rep["players"]],
        "historique_sessions": rep["sessions"],
        "indicateurs_clés": _key_payload(rep.get("key_rows")),
        "indicateurs_clés_par_soirée (6 dernières)": {k: [p["value"] for p in v[-6:]] for k, v in (rep.get("trend") or {}).items()},
        "morts_par_zone": rep.get("zones"),
        "winrate_après_victoire_ou_défaite": rep.get("tilt"),
        "winrate_selon_type_de_dégâts": rep.get("composition"),
        "détail_par_joueur (moyennes par partie)": rep.get("player_details"),
        "teamfights": _tf_payload(rep.get("teamfights"), name),
        "classement": _rank_payload(rep.get("ranks")),
    }


def _call(system, user, cfg):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    ai = cfg.get("ai", {})
    STATUS["enabled"] = bool(key) and ai.get("enabled", True)
    if not STATUS["enabled"]:
        return None
    limit = int(ai.get("max_calls_per_run", 3))
    if STATUS["calls"] >= limit:
        print(f"[info] Plafond de {limit} analyse(s) IA par passage atteint : on s'arrête là.")
        return None
    STATUS["calls"] += 1
    base = max(int(ai.get("max_tokens", 16000)), 16000)
    effort = ai.get("effort", "medium")
    # La réflexion interne du modèle est décomptée de max_tokens. Avec l'effort par défaut
    # ("high"), elle peut tout consommer avant la réponse. On fixe donc un effort modéré,
    # puis, si la réponse est encore vide, on réessaie en "low" avec une limite doublée.
    attempts = [(base, effort), (base * 2, "low")]
    text, reason, use_effort = "", None, True
    for max_tokens, eff in attempts:
        body = {
            "model": ai.get("model", "claude-sonnet-5-5"),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if use_effort:
            body["output_config"] = {"effort": eff}
        try:
            r = requests.post(API_URL, timeout=600, headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
            }, json=body)
            if r.status_code == 400 and use_effort and "output_config" in r.text:
                # Modèle qui ne connaît pas le réglage d'effort : on réessaie sans
                print("[info] Ce modèle n'accepte pas le réglage d'effort, nouvel essai sans.")
                use_effort = False
                r = requests.post(API_URL, timeout=600, headers={
                    "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
                }, json={k: v for k, v in body.items() if k != "output_config"})
            if r.status_code >= 400:
                reason = f"erreur {r.status_code} : {r.text[:300]}"
                print(f"[avertissement] Analyse IA impossible, {reason}")
                if r.status_code in (429, 500, 502, 503, 529):  # surcharge passagère : on patiente
                    time.sleep(20)
                continue
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            print(f"[info] IA : {usage.get('input_tokens', '?')} jetons en entrée, "
                  f"{usage.get('output_tokens', '?')} en sortie (effort {eff if use_effort else 'par défaut'}).")
            if text.strip():
                break
            reason = f"réponse vide (stop_reason={data.get('stop_reason')})"
            print(f"[avertissement] {reason}, nouvel essai plus économe…")
        except Exception as exc:
            reason = str(exc)
            print(f"[avertissement] Analyse IA impossible : {exc}")
    if not text.strip():
        STATUS["errors"].append(reason or "réponse vide")
        return None
    return text


# ------------------------------------------------------------------ textes conservés
def _path(kind, date=None):
    if kind == "global":
        return STORE / "global.json"
    return STORE / ("players" if kind == "players" else "sessions") / f"{date}.json"


def load(kind, date=None):
    f = _path(kind, date)
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("text", "").strip():
            return data
    return None


def save(kind, text, date=None, **meta):
    f = _path(kind, date)
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"text": text, "generated": datetime.now().strftime("%d/%m/%Y"), **meta}
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def global_analysis(rep, cfg, name):
    payload = json.dumps(_global_payload(rep, cfg, name), ensure_ascii=False, indent=1)
    return _call(SYSTEM, f"{GLOBAL_TASK}\n\nDonnées :\n```json\n{payload}\n```", cfg)


def session_analysis(srep, grep, cfg, name):
    payload = {
        "date": srep["date"],
        "bilan_soirée": srep["summary"],
        "parties": [_compact_game(g, name) for g in srep["games"]],
        "picks_de_la_soirée_vs_global": [
            {"rôle": p["role"], "champion": name(p["champion"]), "soirée": f"{p['wins']}/{p['games']}",
             "global": f"{p['global']['wins']}/{p['global']['games']}" if p["global"] else None}
            for p in srep["picks"]],
        "joueurs_soirée": [{k: v for k, v in p.items() if k != "champions"} for p in srep["players"]],
        "bilan_global": grep["summary"],
        "historique_sessions": grep["sessions"][-8:],
        "indicateurs_clés_soirée_vs_moyenne": _key_payload(srep.get("key_rows")),
        "indicateurs_par_partie": srep.get("lines"),
        "morts_par_zone_soirée": srep.get("zones"),
        "détail_par_joueur_soirée": srep.get("player_details"),
        "teamfights_soirée": _tf_payload(srep.get("teamfights"), name),
        "teamfights_moyenne_globale": _tf_payload(srep.get("teamfights_global"), name, short=True),
        "rangs_par_partie (nous, eux, meilleur adverse)": [
            f"{'V' if g['win'] else 'D'} : {rank_label(r['our'])} vs {rank_label(r['enemy'])}, "
            f"meilleur adverse {rank_label(r['enemy_max'])} en {r['enemy_top_role']}" if r else None
            for g, r in zip(srep["games"], srep.get("ranks", []))],
        "rang_moyen_adverse_soirée_vs_habituel": (
            f"{rank_label(srep['rank_summary'].get('enemy'))} vs {rank_label(srep['rank_global'].get('enemy'))}"
            if srep.get("rank_summary", {}).get("games") else None),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    return _call(SYSTEM, f"{SESSION_TASK}\n\nDonnées :\n```json\n{text}\n```", cfg)


def _player_payload(r, name):
    """Données d'un joueur : on garde la soirée et les moyennes, pas la carte."""
    labels = {k: f"{label} ({unit})" if unit else label for k, label, unit, _ in r["defs"]}
    labels.setdefault("lane15", "Or vs vis-à-vis à 15 min")
    keep = ("kills", "deaths", "assists", "cs_min", "dmg_min", "vision_min", "lane15", *labels)
    return {
        "joueur": r["player"], "rôle": r["role"],
        "champ_pool_déclaré": r["pool"],
        "bilan_global": {k: r["profile"].get(k) for k in ("games", "wins", "wr", "kda", "kp", "cs_min", "lane15")},
        "dernière_soirée": {k: r["last_profile"].get(k) for k in ("games", "wins", "wr", "kda")}
                           if r["last_profile"] else "absent",
        "parties_de_la_soirée": [
            {"résultat": "Victoire" if g["win"] else "Défaite", "durée_min": g["duration_min"],
             "champion": name(g["champion"]), "vis-à-vis": name(g["opponent"]) if g["opponent"] else None,
             **{labels.get(k, k): v for k, v in g["m"].items() if k in keep}}
            for g in r["last_games"]],
        "indicateurs_du_rôle (soirée vs habituel)": _key_payload(r["rows"]),
        "indicateurs_du_rôle_par_soirée (6 dernières)": {
            labels[k]: [p["value"] for p in v[-6:]] for k, v in r["trend"].items()},
        "champions (tous les temps)": [
            f"{name(c['champion'])} {c['wins']}/{c['games']}, KDA {c.get('kda')}"
            + (f", {c['lane15']:+} or à 15 min" if c.get("lane15") is not None else "")
            for c in r["champions"][:6]],
        "vis-à-vis_les_plus_durs": [f"{name(c['champion'])} {c['wins']}/{c['games']}" for c in r["matchups"][:4]],
        "équipement": _gear_payload(r.get("gear"), name),
    }


def _gear_payload(gr, name):
    """Stuff du joueur : timings, rentabilité, winrate par objet, builds et adaptation."""
    if not gr:
        return None
    keys = ("first_min", "second_min", "gold_min", "dmg_gold", "items_done")
    labels = {"first_min": "1er_objet_min", "second_min": "2e_objet_min", "gold_min": "or_par_min",
              "dmg_gold": "dégâts_par_or", "items_done": "objets_finis"}
    fmt = lambda rs: [f"{_item(x['item'])} {x['wins']}/{x['games']} ({x['diff']:+} pts)" for x in rs]
    out = {
        "habituel": {labels[k]: gr["profile"].get(k) for k in keys},
        "soirée": {labels[k]: gr["last"].get(k) for k in keys} if gr["last"] else None,
        "winrate_habituel": gr["base_wr"],
        "objets (victoires/parties, écart au winrate habituel)": fmt([x for x in gr["legendary"] if x["games"] >= 2][:8]),
        "bottes": fmt(gr["boots"][:3]),
        "builds_par_champion": [
            f"{name(b['champion'])} ({b['games']} parties) : "
            + (" > ".join(_item(i) for i in b["cores"][0]["ids"]) + f" {b['cores'][0]['wins']}/{b['cores'][0]['games']}"
               if b["cores"] else "pas de build complet")
            for b in gr["builds"][:4]],
    }
    if gr["timing"]:
        t = gr["timing"]
        out["impact_timing_1er_objet"] = (f"avant {t['median']} min : {t['early']['wins']}/{t['early']['games']}, "
                                          f"après : {t['late']['wins']}/{t['late']['games']}")
    if gr["antiheal"]:
        a = gr["antiheal"]
        out["anti_heal_face_aux_soigneurs"] = f"acheté {a['bought']}/{a['needed']}"
    return out


def players_analysis(reports, date, cfg, name):
    payload = {"contexte": cfg.get("ai", {}).get("team_context", ""), "soirée": date,
               "joueurs": [_player_payload(r, name) for r in reports]}
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    return _call(SYSTEM, f"{PLAYERS_TASK}\n\nDonnées :\n```json\n{text}\n```", cfg)


def split_players(text, names):
    """Découpe la réponse en un texte par joueur (sections « ## <joueur> »)."""
    out, cur = {}, None
    lookup = {n.lower(): n for n in names}
    for line in (text or "").splitlines():
        if line.startswith("## "):
            title = line[3:].strip().strip("*` ").split(" (")[0].strip()
            cur = lookup.get(title.lower())
            if cur:
                out[cur] = []
                continue
        if cur:
            out[cur].append(line)
    return {n: "\n".join(v).strip() for n, v in out.items()}
