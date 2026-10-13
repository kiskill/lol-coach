"""Analyse texte par IA (API Claude d'Anthropic).

Chaque texte est généré UNE fois puis conservé dans data/ai/ :
  data/ai/global.json             -> bilan global (regénéré seulement sur demande)
  data/ai/sessions/AAAA-MM-JJ.json -> débrief d'une soirée (généré une fois)
Les relances, pushs ou redéploiements réutilisent ces fichiers sans rien payer.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

STORE = Path("data/ai")
API_URL = "https://api.anthropic.com/v1/messages"
PROMPT_VERSION = "v2"
# État de l'IA pour l'affichage : désactivée (pas de clé) ou en erreur
STATUS = {"enabled": False, "errors": [], "calls": 0}

SYSTEM = """Tu es un coach League of Legends expérimenté qui analyse les statistiques \
d'une équipe amateur. Tu écris en français, de façon directe et concrète, pour le coach \
de l'équipe. Règles :
- Appuie chaque affirmation sur les chiffres fournis (ex. « 7/9 victoires »).
- Signale clairement quand un échantillon est trop petit (moins de 4 parties) pour conclure.
- N'invente aucune donnée absente (ex. si les bans ne sont pas fournis, n'en parle pas comme d'un fait).
- Tu peux utiliser tes connaissances du jeu (synergies, contres, champions simples à prendre en main) \
pour interpréter, en le présentant comme du conseil et non comme une statistique.
- Format : Markdown avec des titres ## et des listes courtes. Pas de tableau de plus de 6 lignes."""

GLOBAL_TASK = """Voici les statistiques globales de l'équipe. Rédige un bilan de coaching \
(500 à 800 mots) avec ces sections :
## Identité de jeu (ce qui marche, compo signature, plan de jeu)
## Forces
## Faiblesses
## Synergies à privilégier / à éviter
## Phase de lane et conversion de l'avance (seulement si des données de début de partie sont fournies : écarts d'or à 10/15 min, throws, comebacks, objectifs)
## Draft : bans prioritaires et picks conseillés
## Élargir les champ-pools (2-3 champions simples ou proches des pools actuels par rôle)
## 3 actions prioritaires pour les prochaines sessions"""

SESSION_TASK = """Voici le détail de la dernière soirée de jeu, avec le bilan global pour \
comparaison. Rédige un débrief de session (250 à 450 mots) avec ces sections :
## Résumé de la soirée
## Ce qui a marché
## Ce qui a coincé (picks, drafts, adversaires, phase de lane, objectifs, joueurs)
## À retenir pour la semaine prochaine (2-3 points concrets)"""


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
    base = max(int(ai.get("max_tokens", 8000)), 8000)
    text, reason = "", None
    # 2 essais : si la réponse est vide (limite de longueur atteinte), on double la limite
    for max_tokens in (base, base * 2):
        try:
            r = requests.post(API_URL, timeout=300, headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
            }, json={
                "model": ai.get("model", "claude-sonnet-5-5"),
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            })
            if r.status_code >= 400:
                reason = f"erreur {r.status_code} : {r.text[:300]}"
                print(f"[avertissement] Analyse IA impossible, {reason}")
                if r.status_code in (429, 500, 502, 503, 529):  # surcharge passagère : on patiente
                    time.sleep(20)
                continue
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            if text.strip():
                break
            reason = f"réponse vide (stop_reason={data.get('stop_reason')})"
            print(f"[avertissement] {reason}, nouvel essai avec une limite plus haute…")
        except Exception as exc:
            reason = str(exc)
            print(f"[avertissement] Analyse IA impossible : {exc}")
    if not text.strip():
        STATUS["errors"].append(reason or "réponse vide")
        return None
    return text


# ------------------------------------------------------------------ textes conservés
def _path(kind, date=None):
    return STORE / "global.json" if kind == "global" else STORE / "sessions" / f"{date}.json"


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
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    return _call(SYSTEM, f"{SESSION_TASK}\n\nDonnées :\n```json\n{text}\n```", cfg)
