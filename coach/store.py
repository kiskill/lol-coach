"""Stockage simple en fichiers JSON dans le dossier data/ (versionné dans Git)."""
import json
import re
from pathlib import Path

import requests

DATA = Path("data")
RAW = DATA / "raw"              # réponses brutes de l'API Riot (1 fichier par partie)
GAMES = DATA / "games.json"     # parties normalisées utilisées pour les stats
STATE = DATA / "state.json"     # PUUID des joueurs + parties ignorées
CHAMPS = DATA / "champions.json"  # noms des champions (Data Dragon)
ICONS = DATA / "icons"            # icônes des champions (téléchargées une fois)


def _read(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_games():
    return _read(GAMES, [])


def save_games(games):
    games = sorted(games, key=lambda g: g["start_utc"])
    _write(GAMES, games)


def upsert_games(new_games):
    """Ajoute ou remplace des parties (une partie API remplace une partie CSV)."""
    by_id = {g["match_id"]: g for g in load_games()}
    for g in new_games:
        old = by_id.get(g["match_id"])
        if old and old.get("source") == "api" and g.get("source") != "api":
            continue
        by_id[g["match_id"]] = g
    save_games(list(by_id.values()))
    return len(by_id)


def load_state():
    return _read(STATE, {"puuids": {}, "ignored": []})


def save_state(state):
    _write(STATE, state)


def save_raw(match):
    _write(RAW / f"{match['metadata']['matchId']}.json", match)


def load_raw(match_id):
    return _read(RAW / f"{match_id}.json", None)


# ---------------------------------------------------------------- champions
_OVERRIDES = {
    "monkeyking": "Wukong", "drmundo": "Dr. Mundo", "jarvaniv": "Jarvan IV",
    "ksante": "K'Sante", "chogath": "Cho'Gath", "kaisa": "Kai'Sa",
    "khazix": "Kha'Zix", "velkoz": "Vel'Koz", "reksai": "Rek'Sai",
    "kogmaw": "Kog'Maw", "belveth": "Bel'Veth", "leblanc": "LeBlanc",
    "nunu": "Nunu & Willump", "renata": "Renata Glasc",
}


class Champions:
    """Correspondance identifiant <-> nom affiché, via Data Dragon (avec repli hors ligne)."""

    def __init__(self, lang="fr_FR"):
        cache = _read(CHAMPS, None)
        if cache is None:
            cache = self._download(lang)
        self.version = cache.get("version")
        self.by_key = cache.get("by_key", {})       # "17" -> "Teemo"
        self.names = cache.get("names", {})          # "monkeyking" -> "Wukong"
        self.ids = cache.get("ids", {})              # "monkeyking" -> "MonkeyKing"

    @staticmethod
    def _download(lang):
        try:
            version = requests.get(
                "https://ddragon.leagueoflegends.com/api/versions.json", timeout=20
            ).json()[0]
            data = requests.get(
                f"https://ddragon.leagueoflegends.com/cdn/{version}/data/{lang}/champion.json",
                timeout=20,
            ).json()["data"]
            cache = {
                "version": version,
                "by_key": {c["key"]: c["id"] for c in data.values()},
                "names": {c["id"].lower(): c["name"] for c in data.values()},
                "ids": {c["id"].lower(): c["id"] for c in data.values()},
            }
            _write(CHAMPS, cache)
            return cache
        except Exception as exc:  # pas de réseau : on continue sans icônes
            print(f"[info] Data Dragon indisponible ({exc}) : noms approximatifs, pas d'icônes.")
            return {}

    def id_from_key(self, key):
        return self.by_key.get(str(key))

    def name(self, champ_id):
        low = champ_id.lower()
        if low in self.names:
            return self.names[low]
        if low in _OVERRIDES:
            return _OVERRIDES[low]
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", champ_id)

    def cdn_id(self, champ_id):
        return self.ids.get(champ_id.lower(), champ_id)

    def icon(self, champ_id):
        """Chemin relatif de l'icône si elle a été téléchargée, sinon None (initiales)."""
        f = ICONS / f"{self.cdn_id(champ_id)}.png"
        return f"img/{f.name}" if f.exists() else None

    def fetch_icons(self, champ_ids):
        """Télécharge les icônes manquantes. Si la toute dernière version de Data Dragon
        n'a pas encore l'image, on essaie les 2 versions précédentes."""
        ICONS.mkdir(parents=True, exist_ok=True)
        versions, online, files = None, bool(self.version), []
        for cid in sorted(champ_ids):
            f = ICONS / f"{self.cdn_id(cid)}.png"
            if not f.exists() and online:
                if versions is None:
                    versions = self._versions()
                for v in versions:
                    try:
                        r = requests.get(
                            f"https://ddragon.leagueoflegends.com/cdn/{v}/img/champion/{f.name}", timeout=15)
                    except Exception as exc:
                        print(f"[info] Icônes indisponibles ({exc.__class__.__name__}) : initiales à la place.")
                        online = False
                        break
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                        f.write_bytes(r.content)
                        break
            if f.exists():
                files.append(f)
        return files

    def _versions(self):
        try:
            allv = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=15).json()
            return [self.version] + [v for v in allv[:3] if v != self.version][:2]
        except Exception:
            return [self.version]
