"""Jeu de données de l'explorateur : une ligne par joueur et par partie, avec toutes les
statistiques numériques du détail Riot (dont les "challenges") et les indicateurs de l'outil."""
from . import store

# Indicateurs calculés par l'outil (prioritaires dans la liste)
TOOL_METRICS = {
    "ind.deaths15": "Morts avant 15 min",
    "ind.cs10": "CS à 10 min",
    "ind.cs10_diff": "Écart de CS à 10 min (vs vis-à-vis)",
    "ind.lane15": "Écart d'or à 15 min (vs vis-à-vis)",
    "ind.kp": "Participation aux kills (%)",
    "ind.tf": "Teamfights où le joueur est impliqué",
    "ind.tf_first_death": "1er mort dans un teamfight perdu",
    "ind.tf_dmg": "Dégâts sur les adversaires tués en teamfight",
    "ind.tank_min": "Dégâts encaissés (subis + atténués) / min",
}

# Libellés français des champs Riot les plus utiles (les autres gardent leur nom anglais)
LABELS = {
    "kills": "Kills", "deaths": "Morts", "assists": "Assistances",
    "totalMinionsKilled": "Sbires tués", "neutralMinionsKilled": "Monstres neutres tués",
    "goldEarned": "Or gagné", "goldSpent": "Or dépensé", "champLevel": "Niveau final",
    "totalDamageDealtToChampions": "Dégâts aux champions",
    "physicalDamageDealtToChampions": "Dégâts physiques aux champions",
    "magicDamageDealtToChampions": "Dégâts magiques aux champions",
    "trueDamageDealtToChampions": "Dégâts bruts aux champions",
    "totalDamageTaken": "Dégâts subis", "damageSelfMitigated": "Dégâts atténués",
    "totalHeal": "Soins", "totalHealsOnTeammates": "Soins sur les alliés",
    "totalDamageShieldedOnTeammates": "Boucliers sur les alliés",
    "timeCCingOthers": "Temps de contrôle infligé (s)", "totalTimeCCDealt": "Durée totale de CC infligé",
    "visionScore": "Score de vision", "wardsPlaced": "Wards posées", "wardsKilled": "Wards détruites",
    "visionWardsBoughtInGame": "Pinks achetées", "detectorWardsPlaced": "Pinks posées",
    "damageDealtToObjectives": "Dégâts aux objectifs", "damageDealtToBuildings": "Dégâts aux bâtiments",
    "turretKills": "Tours détruites", "inhibitorKills": "Inhibiteurs détruits",
    "dragonKills": "Dragons tués", "baronKills": "Nashors tués",
    "largestKillingSpree": "Plus longue série de kills", "largestMultiKill": "Plus gros multi-kill",
    "doubleKills": "Doublés", "tripleKills": "Triplés", "quadraKills": "Quadras", "pentaKills": "Pentas",
    "longestTimeSpentLiving": "Plus longue période en vie (s)", "totalTimeSpentDead": "Temps passé mort (s)",
    "spell1Casts": "Sort A lancé", "spell2Casts": "Sort Z lancé", "spell3Casts": "Sort E lancé",
    "spell4Casts": "Ultimes lancés", "summoner1Casts": "Sort d'invocateur 1 lancé",
    "summoner2Casts": "Sort d'invocateur 2 lancé", "itemsPurchased": "Objets achetés",
    "consumablesPurchased": "Consommables achetés", "totalAllyJungleMinionsKilled": "Camps alliés tués",
    "totalEnemyJungleMinionsKilled": "Camps adverses tués (contre-jungle)",
    # challenges
    "challenges.killParticipation": "Participation aux kills (Riot)",
    "challenges.soloKills": "Solo kills", "challenges.turretPlatesTaken": "Plaques de tour prises",
    "challenges.laneMinionsFirst10Minutes": "Sbires de lane à 10 min",
    "challenges.controlWardsPlaced": "Pinks posées (Riot)", "challenges.epicMonsterSteals": "Objectifs volés",
    "challenges.enemyChampionImmobilizations": "Immobilisations d'adversaires",
    "challenges.skillshotsDodged": "Skillshots esquivés", "challenges.skillshotsHit": "Skillshots touchés",
    "challenges.outnumberedKills": "Kills en infériorité numérique",
    "challenges.teamDamagePercentage": "Part des dégâts de l'équipe",
    "challenges.damageTakenOnTeamPercentage": "Part des dégâts encaissés par l'équipe",
    "challenges.visionScorePerMinute": "Score de vision / min", "challenges.goldPerMinute": "Or / min",
    "challenges.damagePerMinute": "Dégâts / min", "challenges.kda": "KDA (Riot)",
    "challenges.effectiveHealAndShielding": "Soins et boucliers effectifs",
    "challenges.saveAllyFromDeath": "Alliés sauvés de la mort",
    "challenges.survivedSingleDigitHpCount": "Survies à moins de 10 PV",
    "challenges.dragonTakedowns": "Participations aux dragons",
    "challenges.baronTakedowns": "Participations aux Nashors",
    "challenges.riftHeraldTakedowns": "Participations aux Hérauts",
    "challenges.wardTakedowns": "Wards détruites (Riot)", "challenges.stealthWardsPlaced": "Wards posées (Riot)",
    "challenges.maxCsAdvantageOnLaneOpponent": "Plus grande avance de CS sur le vis-à-vis",
    "challenges.visionScoreAdvantageLaneOpponent": "Avantage de vision sur le vis-à-vis",
    "challenges.multikills": "Multi-kills", "challenges.takedowns": "Participations aux kills",
    "challenges.immobilizeAndKillWithAlly": "Kills après immobilisation avec un allié",
    "challenges.pickKillWithAlly": "Picks avec un allié",
    "challenges.knockEnemyIntoTeamAndKill": "Adversaire repoussé dans l'équipe puis tué",
}

# Champs numériques sans intérêt (identifiants, positions, drapeaux techniques)
SKIP = {"participantId", "teamId", "championId", "profileIcon", "summonerLevel", "item0", "item1", "item2",
        "item3", "item4", "item5", "item6", "summoner1Id", "summoner2Id", "championTransform",
        "playerScore0", "playerScore1", "playerScore2", "playerScore3", "playerScore4", "playerScore5",
        "playerScore6", "playerScore7", "playerScore8", "playerScore9", "playerScore10", "playerScore11",
        "placement", "subteamPlacement", "playerAugment1", "playerAugment2", "playerAugment3",
        "playerAugment4", "playerAugment5", "playerAugment6", "missions", "riotIdTagline"}


def _numeric(d, prefix=""):
    for k, v in d.items():
        if k in SKIP or isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            yield prefix + k, v


def build_dataset(games, session_of, name):
    rows, keys = [], {}
    for g in games:
        if g.get("source") != "api" or not g.get("ind"):
            continue
        raw = store.load_raw(g["match_id"])
        if not raw:
            continue
        by_champ = {p["championName"]: p for p in raw["info"]["participants"]}
        lanes15 = g.get("early", {}).get("15", {}).get("lanes", {})
        for p in g["our"]:
            rp = by_champ.get(p["champion"])
            if not rp:
                continue
            vals = {}
            for k, v in _numeric(rp):
                vals[k] = v
            for k, v in _numeric(rp.get("challenges") or {}, "challenges."):
                vals[k] = round(v, 3) if isinstance(v, float) else v
            ind = g["ind"]["players"].get(p["role"], {})
            for k in TOOL_METRICS:
                short = k[4:]
                v = lanes15.get(p["role"], {}).get("gold") if short == "lane15" else ind.get(short)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals[k] = v
            for k in vals:
                keys[k] = True
            rows.append({"game": g["match_id"],
                         "date": session_of[g["match_id"]], "win": g["win"], "player": p.get("player") or p["role"],
                         "role": p["role"], "champion": name(p["champion"]), "minutes": g["duration_min"],
                         "v": vals})

    def group(k):
        return "tool" if k.startswith("ind.") else "challenge" if k.startswith("challenges.") else "game"

    def label(k):
        if k in TOOL_METRICS:
            return TOOL_METRICS[k]
        return LABELS.get(k) or k.replace("challenges.", "")

    order = list(TOOL_METRICS) + sorted((k for k in keys if k not in TOOL_METRICS),
                                        key=lambda k: (k not in LABELS, group(k), label(k).lower()))
    metrics = [{"key": k, "label": label(k), "group": group(k), "fr": k in LABELS or k in TOOL_METRICS}
               for k in order if k in keys]
    idx = {m["key"]: i for i, m in enumerate(metrics)}
    # format compact : chaque ligne porte un tableau de valeurs aligné sur la liste des indicateurs
    game_idx = {}
    compact = []
    for r in rows:
        gi = game_idx.setdefault(r["game"], len(game_idx))
        arr = [None] * len(metrics)
        for k, v in r["v"].items():
            arr[idx[k]] = v
        compact.append([r["date"], int(r["win"]), r["player"], r["role"], r["champion"], r["minutes"], arr, gi])
    return {"metrics": metrics, "rows": compact}
