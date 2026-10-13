# Coaching LoL : rapport automatique de l'équipe

Chaque semaine, l'outil fait quatre choses :

1. Il récupère via l'API Riot les nouvelles parties de ranked flex jouées **à 5**.
2. Il calcule les statistiques : winrate par champion et par rôle, synergies, adversaires, bans, objectifs, joueurs, rang de la partie dans la soirée.
3. Il demande à une IA (Claude) un **bilan global** et un **débrief de la dernière soirée**.
4. Il publie le tout sur un petit site web gratuit (GitHub Pages).

L'historique initial des 43 parties est déjà importé : le site fonctionne dès le premier lancement.

---

## Mise en route pas à pas (environ 30 minutes)

### Étape 1 : créer le dépôt GitHub

1. Crée un compte sur [github.com](https://github.com) si besoin.
2. En haut à droite, clique sur **+ → New repository**.
   - Nom : par exemple `lol-coach`.
   - Visibilité : **Public**. GitHub Pages est gratuit uniquement pour les dépôts publics. Tes clés restent secrètes (voir étape 4). Les données de parties sont de toute façon publiques chez Riot.
   - Ne coche rien d'autre (pas de README) et clique sur **Create repository**.

### Étape 2 : envoyer le code

Tu connais GitLab : c'est exactement le même Git. Dans le dossier du projet décompressé :

```bash
git init
git add .
git commit -m "Premier jet"
git branch -M main
git remote add origin https://github.com/kiskill/lol-coach.git
git push -u origin main
```

Si GitHub demande un mot de passe, il faut un **token** :
- Va dans **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token**.
- Coche `repo` et `workflow`.
- Colle le token à la place du mot de passe.

Plus simple : installe [GitHub Desktop](https://desktop.github.com), qui gère la connexion tout seul.

**Sans Git :** sur la page du dépôt, utilise **uploading an existing file** et glisse-dépose tout le contenu du dossier. Vérifie que le dossier caché `.github` est bien envoyé : sur Mac, `Cmd+Shift+.` affiche les fichiers cachés.

### Étape 3 : adapter `config.yaml`

Tu peux le modifier directement sur GitHub : ouvre le fichier, clique sur le crayon ✏️, puis sur **Commit changes**.

- `team_name` : le nom de ton équipe.
- `players` : le **Riot ID exact** de chaque joueur (`Pseudo#TAG`, comme affiché dans le client) et son rôle.
- `start_date` : la date à partir de laquelle récupérer les parties.
- `min_team_players` : mets `4` si vous jouez parfois avec un remplaçant.

### Étape 4 : obtenir les clés et les enregistrer comme secrets

**Clé Riot**
1. Connecte-toi sur [developer.riotgames.com](https://developer.riotgames.com) avec ton compte LoL.
2. Une **Development API Key** s'affiche sur le tableau de bord.
   - ⚠️ Elle **expire toutes les 24 h**. Elle suffit pour tester, mais pas pour l'automatique.
3. Pour une clé qui n'expire pas : **Register Product → Personal API Key**.
   - Décris le projet, par exemple : « Outil privé de statistiques pour mon équipe de 5 amis, une analyse par semaine, pas de diffusion publique ».
   - La validation par Riot prend généralement quelques jours.

**Clé IA (optionnelle mais recommandée)**
1. Crée un compte sur [console.anthropic.com](https://console.anthropic.com).
2. Ajoute un peu de crédit, puis crée une clé dans **API Keys**.
3. Le coût est très faible : quelques appels par semaine, et les analyses déjà générées sont mises en cache.
4. Sans cette clé, le site fonctionne quand même avec des « constats automatiques ».

**Enregistrer les secrets dans GitHub** (équivalent des *CI/CD Variables* de GitLab) :
1. Ouvre **Settings → Secrets and variables → Actions → New repository secret**.
2. Crée le secret `RIOT_API_KEY` avec ta clé Riot.
3. Crée le secret `ANTHROPIC_API_KEY` avec ta clé IA.

### Étape 5 : activer le site

**Settings → Pages → Build and deployment → Source : GitHub Actions**

### Étape 6 : premier lancement

1. Ouvre l'onglet **Actions**, puis le workflow **Rapport hebdomadaire**.
2. Clique sur **Run workflow**.
3. Après 2 à 10 minutes, la première collecte est terminée. Elle peut être longue s'il y a beaucoup de parties.
4. Ton site est en ligne sur : `https://TON_PSEUDO.github.io/lol-coach/`

Ensuite, tout se fait **automatiquement chaque mercredi matin**. Pour changer le jour, modifie la ligne `cron` dans `.github/workflows/rapport-hebdo.yml`.

> **Tant que tu n'as que la clé de développement (24 h)**
> - Le soir de jeu, régénère-la sur le portail Riot.
> - Mets à jour le secret `RIOT_API_KEY`.
> - Clique sur **Run workflow**.
>
> Si la clé est expirée, le site se régénère quand même avec les anciennes données et affiche un bandeau d'avertissement.

---

## Correspondance GitLab → GitHub

| GitLab | GitHub |
|---|---|
| `.gitlab-ci.yml` | `.github/workflows/*.yml` |
| Pipelines / Jobs | Actions / Workflows / Jobs |
| CI/CD Variables (masked) | Secrets (Settings → Secrets and variables → Actions) |
| Pipeline schedules | `on: schedule: cron` directement dans le fichier |
| GitLab Pages | GitHub Pages |
| Merge Request | Pull Request |
| Personal Access Token | Personal Access Token (Developer settings) |

---

## Lancer en local (pour modifier le code)

```bash
pip install -r requirements.txt
export RIOT_API_KEY="RGAPI-..."           # Windows PowerShell : $env:RIOT_API_KEY="RGAPI-..."
export ANTHROPIC_API_KEY="sk-ant-..."     # facultatif
python main.py update                      # collecte + génération
# puis ouvre site/index.html dans ton navigateur
```

Autres commandes :
- `python main.py build` : régénère le site sans appeler Riot.
- `python main.py collect` : collecte uniquement.
- `python main.py import-csv fichier.csv` : importe un historique CSV.

## Organisation du code

```
config.yaml              ← tout ce qui se règle (joueurs, file, fuseau, IA, seuils)
main.py                  ← commandes
coach/riot.py            ← appels API Riot + conversion des parties
coach/stats.py           ← tous les calculs
coach/insights.py        ← constats automatiques sans IA
coach/ai.py              ← prompts et appel à l'IA (modifie les consignes ici)
coach/site.py            ← génération des pages
coach/templates/         ← HTML / CSS du site
data/games.json          ← parties normalisées (sauvegardées à chaque passage)
data/raw/                ← réponses brutes de Riot (tout le détail, pour de futures stats)
data/ai_cache/           ← analyses IA déjà générées (évite de repayer)
```

## Limites connues et pistes d'amélioration

- **Les 43 parties importées du CSV** n'ont ni bans, ni KDA, ni objectifs. Lors de la première collecte API, si `start_date` les couvre, elles sont remplacées automatiquement par la version complète.
- **Le rôle de chaque joueur** vient de la position détectée par Riot. Si la détection échoue, l'outil utilise le rôle indiqué dans `config.yaml`.
- **Pistes d'amélioration :**
  - écart d'or à 15 min (endpoint *timeline*) ;
  - page par joueur ;
  - envoi du débrief sur Discord via un webhook ;
  - filtre par patch.
- **Désactivation automatique :** GitHub désactive les tâches planifiées d'un dépôt public sans activité pendant 60 jours. Les commits hebdomadaires de données devraient l'éviter. Si ça arrive, réactive le workflow dans l'onglet Actions.
