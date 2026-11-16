# Veille Audio — IA & cybersécurité en podcast, mise en place pas-à-pas

Ce dépôt produit chaque matin **un épisode audio par domaine de veille**
(aujourd'hui : intelligence artificielle et cybersécurité), qui arrive tout
seul dans votre application de podcast.

Le traitement tourne **en local, sur votre PC**, via une tâche programmée de
l'application Claude Desktop. Le stockage et la diffusion passent par ce dépôt
GitHub + GitHub Pages (gratuits).

---

## Sommaire

- [A. Ce que fait la tâche chaque matin](#a-ce-que-fait-la-tâche-chaque-matin)
- [B. Prérequis](#b-prérequis)
- [C. Organisation du dépôt](#c-organisation-du-dépôt)
- [D. Étape 1 — Récupérer le dépôt et installer l'environnement Python](#d-étape-1--récupérer-le-dépôt-et-installer-lenvironnement-python)
- [E. Étape 2 — Activer GitHub Pages](#e-étape-2--activer-github-pages)
- [F. Étape 3 — Personnaliser la configuration](#f-étape-3--personnaliser-la-configuration)
- [G. Étape 4 — Créer la tâche programmée](#g-étape-4--créer-la-tâche-programmée)
- [H. Étape 5 — Test « Run now » et vérifications](#h-étape-5--test--run-now--et-vérifications)
- [I. Étape 6 — S'abonner dans l'app podcast](#i-étape-6--sabonner-dans-lapp-podcast)
- [J. Ajouter un nouveau domaine de veille](#j-ajouter-un-nouveau-domaine-de-veille)
- [K. Dépannage](#k-dépannage)
- [L. Tests](#l-tests)

---

## A. Ce que fait la tâche chaque matin

Pour **chaque domaine** configuré (un fichier `config/<domaine>.json`), l'un
après l'autre :

1. **Collecte** les actualités parues depuis le dernier épisode (au moins
   30 h, au plus 96 h si des passages ont été manqués) depuis les flux RSS du
   domaine (`scripts/fetch_news.py`), avec un dédoublonnage par lien et par
   titre, et en écartant ce qui a déjà été transmis un jour précédent. Un
   rapport de santé signale les flux morts ou bloqués.
2. **Claude lui-même** fait le travail éditorial selon les consignes du
   domaine (`prompts/<domaine>.md`) : il fusionne les doublons restants,
   écarte le promotionnel, traduit l'anglais, hiérarchise, relit les deux
   épisodes précédents pour ne pas se répéter, puis rédige un script parlé en
   français de 5 à 8 minutes.
3. **Transforme ce script en MP3** avec une voix neuronale française
   (`scripts/make_audio.py`, via edge-tts, gratuit).
4. **Met à jour le flux podcast du domaine** (`feed-<domaine>.xml`) et
   applique la rétention : seuls les N derniers épisodes sont gardés, et la
   rétention d'un domaine ne touche jamais aux fichiers d'un autre. La
   transcription est archivée dans `episodes/<domaine>/`.

Puis, **une seule fois** pour tous les domaines :

5. **Publie** avec `veille.py deploy` : le site (flux + MP3 + vignettes) est
   poussé sur la branche `gh-pages`, **réécrite chaque jour en un seul commit
   sans historique** ; les transcriptions (du texte) sont poussées sur `main`.

**Pourquoi deux branches ?** Un MP3 supprimé d'une branche git reste pour
toujours dans son historique. En gardant les MP3 hors de `main` et en
republiant chaque jour `gh-pages` comme un commit unique, la taille du site
reste bornée (`keep_episodes` MP3 par domaine) au lieu de grossir d'environ
1,5 Go par an.

Si un domaine échoue, les autres sont quand même publiés ; le compte rendu
de fin de tâche indique lequel a échoué et pourquoi.

Vous, le matin : vous ouvrez votre app podcast, les épisodes du jour sont là.

---

## B. Prérequis

- **Un PC Windows allumé** à l'heure de la tâche, avec **l'application
  Claude Desktop ouverte** (onglet Code). Si l'app est fermée à l'heure
  prévue, la tâche s'exécute à sa prochaine ouverture.
- **Un plan Claude payant** (Pro suffit) : chaque passage consomme votre
  quota d'utilisation comme une session normale.
- **Python 3.10 ou plus récent** (testé avec Python 3.15).
- **Git**, avec des identifiants GitHub capables de pousser sur ce dépôt
  (Git Credential Manager ou `gh auth login`).
- **Un compte GitHub** (gratuit) et ce dépôt en **public**.

---

## C. Organisation du dépôt

```
Veille-Audio/
  config/
    ia.json               paramètres du domaine IA (voix, flux, rétention…)
    cyber.json            paramètres du domaine cyber
  sources/
    ia.txt                flux RSS IA (une URL par ligne)
    cyber.txt             flux RSS cyber
  prompts/
    ia.md                 consignes éditoriales IA
    cyber.md              consignes éditoriales cyber
  scripts/
    veille.py             point d'entrée : domains | collect D | publish D
                          | deploy | restore
    fetch_news.py         collecte RSS + dédoublonnage + rapport de santé
    make_audio.py         synthèse vocale (edge-tts)
    update_feed.py        mise à jour du flux podcast + rétention
  audio/
    ia/                   MP3 du domaine IA (locaux + branche gh-pages)
    cyber/                MP3 du domaine cyber (locaux + branche gh-pages)
  covers/
    ia.jpg, cyber.jpg     vignettes des podcasts
  episodes/
    ia/, cyber/           transcriptions des épisodes (AAAA-MM-JJ.txt)
  tests/                  tests hors ligne des scripts
  feed-ia.xml             flux podcast IA (local + branche gh-pages)
  feed-cyber.xml          flux podcast cyber (local + branche gh-pages)
  ROUTINE_PROMPT.md       déroulé complet suivi par la tâche programmée
  requirements.txt        dépendances Python
  work/                   fichiers intermédiaires (non suivis par git)
  .venv/                  environnement Python local (non suivi par git)
```

Le principe : **les scripts sont communs**, tout ce qui est propre à un
domaine tient dans quatre fichiers (`config/`, `sources/`, `prompts/`,
`covers/`) et deux dossiers de sortie (`audio/<domaine>/`,
`feed-<domaine>.xml`).

Les MP3 et les flux ne sont **pas suivis dans `main`** (voir `.gitignore`) :
ils vivent dans votre dossier local et sur la branche `gh-pages`.

---

## D. Étape 1 — Récupérer le dépôt et installer l'environnement Python

Dans un terminal (Git Bash ou PowerShell), à l'endroit où vous rangez vos
dépôts :

```bash
git clone https://github.com/Nyverlight/Veille-Audio.git
```

```bash
cd Veille-Audio
```

Créez l'environnement Python du dépôt et installez les dépendances
(`requests`, `curl_cffi`, `edge-tts`) :

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

Si vous repartez d'un clone neuf (nouveau PC, dossier perdu), récupérez les
épisodes et les flux déjà en ligne, sans quoi le prochain passage refusera de
publier :

```bash
.venv/Scripts/python scripts/veille.py restore
```

Vérifiez que la collecte fonctionne :

```bash
.venv/Scripts/python scripts/veille.py collect ia
```

Le log liste chaque flux avec `[OK]` ou `[ECHEC]`, puis le nombre
d'actualités écrites dans `work/ia/raw_news.json`.

⏱️ ~10 min

---

## E. Étape 2 — Activer GitHub Pages

1. Dépôt → **Settings** → **Pages**.
2. Source : **Deploy from a branch**, branche **gh-pages**, dossier
   **/(root)**. (La branche est créée par le premier `veille.py deploy`.)
3. Enregistrez. GitHub affiche l'URL du site :
   `https://nyverlight.github.io/Veille-Audio`.
4. Vérifiez que la valeur de `base_url` dans **chaque** fichier
   `config/*.json` correspond **exactement** à cette URL (sans slash final).

Alternative en ligne de commande :

```bash
gh api -X PUT repos/Nyverlight/Veille-Audio/pages -f "source[branch]=gh-pages" -f "source[path]=/"
```

⏱️ ~5 min (+ quelques minutes de propagation côté GitHub)

---

## F. Étape 3 — Personnaliser la configuration

Dans `config/<domaine>.json` :

| Clé | Rôle | Valeur actuelle |
|---|---|---|
| `voice` | voix de synthèse | `fr-FR-RemyMultilingualNeural` |
| `rate` | débit de lecture (ex. `+10%` pour accélérer) | `+0%` |
| `lookback_hours` | fenêtre de collecte minimale | `30` |
| `max_lookback_hours` | fenêtre maximale quand des passages ont été manqués | `96` |
| `max_items_fetch` | nombre max d'actualités transmises à Claude | `80` |
| `max_items_per_feed` | nombre max d'actualités retenues par flux | `8` |
| `keep_episodes` | nombre d'épisodes conservés dans le flux | `30` |
| `feed_title` / `feed_description` | titre et description du podcast | — |
| `episode_title_prefix` | début du titre (« Veille IA du 16 novembre 2026 ») | `Veille IA`, `Veille Cyber` |
| `feed_category` | catégorie du podcast | `Technology` |
| `base_url` | URL GitHub Pages du dépôt | `https://nyverlight.github.io/Veille-Audio` |
| `feed_file`, `audio_dir`, `cover` | fichiers de sortie du domaine | à ne changer qu'en ajoutant un domaine |

**Voix** : les voix multilingues (`fr-FR-RemyMultilingualNeural`,
`fr-FR-VivienneMultilingualNeural`) prononcent mieux les termes anglais
fréquents en IA et en cyber. Autres voix françaises : `fr-FR-DeniseNeural`
(féminine), `fr-FR-HenriNeural` (masculine). Pour lister toutes les voix :

```bash
.venv/Scripts/edge-tts --list-voices
```

**Sources** : dans `sources/<domaine>.txt`, une URL de flux RSS par ligne ;
les lignes vides et celles commençant par `#` sont ignorées. Le catalogue
JSON CISA KEV est aussi accepté (adaptateur dédié). Pour tester sans tenir
compte de ce qui a déjà été traité :
`.venv/Scripts/python scripts/veille.py collect cyber --all`.

**Ligne éditoriale** : dans `prompts/<domaine>.md` — public visé, ordre de
priorité des sujets, ce qu'il faut écarter, manière de citer les sources.
Les contraintes communes (texte parlé pur, 800 à 1300 mots, intro et
clôture) sont dans `ROUTINE_PROMPT.md`.

⏱️ ~15-20 min

---

## G. Étape 4 — Créer la tâche programmée

Dans l'application **Claude Desktop**, onglet **Code**, section
**Scheduled** de la barre latérale → nouvelle tâche :

1. **Nom** : `Veille Audio (IA + Cyber)`.
2. **Fréquence** : tous les jours, ex. **06:00** (heure locale).
3. **Mode d'autorisation** : **Auto**, pour que la tâche puisse exécuter
   Python, git et pousser sans attendre de confirmation.
4. **Prompt** : collez le texte ci-dessous (en adaptant le chemin du dépôt
   si besoin) :

   ```text
   Tu produis ma veille audio quotidienne (podcasts IA et cybersécurité).

   Le dépôt se trouve sur ce PC Windows : C:\Users\admin\Documents\GitHub\Veille-Audio
   (en Git Bash : /c/Users/admin/Documents/GitHub/Veille-Audio).

   1. Place-toi à la racine de ce dépôt (cd vers le chemin ci-dessus) et lance toutes les commandes depuis là.
   2. Lis intégralement le fichier ROUTINE_PROMPT.md à la racine du dépôt.
   3. Exécute-le étape par étape, pour chaque domaine listé, jusqu'à la commande de publication (veille.py deploy).
   4. Termine par le compte rendu demandé dans ROUTINE_PROMPT.md.

   Ne modifie ni les scripts, ni la configuration, ni les sources : signale les problèmes dans le compte rendu.
   ```

Le prompt de la tâche est volontairement court : **le vrai déroulé est dans
`ROUTINE_PROMPT.md`**. Pour faire évoluer le comportement de la tâche, il
suffit donc de modifier ce fichier dans le dépôt, sans toucher à la tâche.

La tâche est stockée dans
`C:\Users\admin\.claude\scheduled-tasks\veille-audio\SKILL.md`.

**Modèle** : le travail éditorial ne demande pas le modèle le plus puissant.
Sonnet suffit et consomme nettement moins de quota qu'Opus ; le modèle se
choisit dans les réglages de la tâche, et le compte rendu de chaque passage
indique celui qui a tourné.

**Sécurité** : la tâche lit du texte venant de dizaines de sites externes.
`ROUTINE_PROMPT.md` lui impose de le traiter comme une donnée (jamais comme
une instruction) et limite les commandes autorisées à cinq. Le mode Auto lui
laisse malgré tout un accès complet au PC : évitez de garder des secrets
(`.env`, clés) dans des dossiers voisins du dépôt.

⏱️ ~5 min

---

## H. Étape 5 — Test « Run now » et vérifications

Lancez la tâche manuellement avec **Run now**, puis vérifiez, dans l'ordre :

1. **Collecte** : pour chaque domaine, le log de `veille.py collect` liste
   les flux. Repérez les `[ECHEC]` (voir Dépannage) ; `[OK] 0/N` signifie
   seulement que les N articles du flux sont plus vieux que la fenêtre.
2. **Éditorial** : ouvrez `work/ia/script.txt` et `work/cyber/script.txt` —
   le texte doit être du français parlé propre, sans markdown ni URL.
3. **Audio** : `audio/ia/ia-AAAA-MM-JJ.mp3` et
   `audio/cyber/cyber-AAAA-MM-JJ.mp3` existent et font plus de 1 Mo.
4. **Flux** : `feed-ia.xml` et `feed-cyber.xml` contiennent un nouvel
   `<item>` avec la bonne `<enclosure>`.
5. **Publication** : `veille.py deploy` se termine par
   `DEPLOIEMENT TERMINE.` ; la branche `gh-pages` ne contient qu'un commit
   (`git rev-list --count origin/gh-pages` affiche `1`) et un commit
   « Veille Audio - AAAA-MM-JJ » avec les transcriptions est poussé sur
   `main`.
6. **En ligne** : après 1 à 2 minutes (construction Pages),
   `https://nyverlight.github.io/Veille-Audio/feed-ia.xml` s'ouvre dans un
   navigateur.

Un passage complet (deux domaines) prend environ 10 minutes.

⏱️ ~15-30 min (dont le calibrage : longueur, style, voix)

---

## I. Étape 6 — S'abonner dans l'app podcast

Dans votre app podcast (Pocket Casts, Apple Podcasts, AntennaPod, etc.) :
« Ajouter par URL » / « Add by URL », puis collez l'URL de chaque flux :

| Domaine | URL du flux |
|---|---|
| Intelligence artificielle | `https://nyverlight.github.io/Veille-Audio/feed-ia.xml` |
| Cybersécurité | `https://nyverlight.github.io/Veille-Audio/feed-cyber.xml` |

Les jours suivants, chaque nouvel épisode arrivera automatiquement.

⏱️ ~5 min

---

## J. Ajouter un nouveau domaine de veille

Exemple pour un domaine `cloud` :

1. Copiez `config/ia.json` en `config/cloud.json` et changez :
   `domain_label`, `domain_slug` (`cloud`), `episode_title_prefix`,
   `sources_file` (`sources/cloud.txt`), `editorial_file`
   (`prompts/cloud.md`), `feed_file` (`feed-cloud.xml`), `audio_dir`
   (`audio/cloud`), `cover` (`covers/cloud.jpg`), `feed_title`,
   `feed_description`.
2. Créez `sources/cloud.txt` (vos flux RSS) et `prompts/cloud.md` (vos
   consignes éditoriales — inspirez-vous de `prompts/cyber.md`).
3. Créez le dossier `audio/cloud/` avec un fichier vide `.gitkeep`, et
   déposez une image carrée `covers/cloud.jpg` (ex. 1400×1400).
4. Testez la collecte : `.venv/Scripts/python scripts/veille.py collect cloud`.
5. Commitez et poussez.

C'est tout : la tâche traite automatiquement chaque fichier présent dans
`config/`. Abonnez-vous ensuite à `…/feed-cloud.xml`.

---

## K. Dépannage

- **Pas d'épisode un matin** : l'app Claude Desktop était fermée ou le PC
  en veille à l'heure prévue. La tâche s'exécute à la prochaine ouverture de
  l'app ; consultez son historique dans la section **Scheduled**.
- **`[ECHEC]` dans la collecte** :
  - `403` → protection anti-bot. `fetch_news.py` imite déjà un navigateur
    (curl_cffi) ; si le 403 persiste, retirez la source ou passez par un
    proxy de flux (RSSHub).
  - `404` → l'URL du flux est morte : retrouvez la bonne URL sur le site et
    corrigez `sources/<domaine>.txt`.
- **Aucune actualité récupérée** : vérifiez la connexion Internet du PC et
  la validité des URLs du fichier de sources.
- **Pas de MP3 généré** : le service de synthèse d'edge-tts est injoignable
  ou a changé. Mettez edge-tts à jour :
  `.venv/Scripts/python -m pip install -U edge-tts`.
- **`ModuleNotFoundError`** : l'environnement `.venv` est absent ou
  incomplet → refaites l'étape 1.
- **Le push échoue** : identifiants GitHub expirés → `gh auth login`, ou
  reconnectez Git Credential Manager. Si `main` distant est en avance,
  `deploy` fait lui-même un `git pull --rebase` avant de repousser.
- **`deploy` s'arrête sur « Incoherences detectees »** : un MP3 référencé par
  un flux manque en local, ou le flux local contient moins d'épisodes que
  celui en ligne. C'est un garde-fou : il évite d'écraser le site avec un
  dossier incomplet. Lancez `veille.py restore` (récupère ce qui est en
  ligne), ou `veille.py deploy --force` si l'état local est bien le bon.
- **`update_feed.py` s'arrête sur un flux « illisible »** : le fichier
  `feed-<domaine>.xml` local est corrompu. Rien n'a été supprimé ; récupérez
  la version en ligne avec `veille.py restore --force`.
- **Un sujet revient deux jours de suite** : la mémoire anti-répétition est
  dans `work/<domaine>/seen.json` (local, purgée au bout de 7 jours) et dans
  `episodes/<domaine>/`.
- **L'app podcast ne voit pas le flux** : Pages pas encore construit
  (attendez quelques minutes, ou regardez l'onglet **Actions** du dépôt), ou
  `base_url` mal renseigné dans `config/*.json`.
- **La tâche s'arrête pour demander une autorisation** : elle n'est pas en
  mode Auto → modifiez-la dans la section **Scheduled**.

**Taille du dépôt** : `main` ne contient que du code et du texte. Le site
(`gh-pages`) est borné à `keep_episodes` MP3 par domaine, soit ~120 Mo avec
deux domaines et 30 épisodes — loin de la limite de 1 Go de GitHub Pages.
Pour le réduire encore, baissez `keep_episodes`. Côté GitHub, les anciens MP3
devenus inaccessibles sont nettoyés par leur maintenance, à leur rythme : la
taille affichée du dépôt peut baisser avec retard.

---

## L. Tests

Les scripts ont des tests hors ligne (aucun accès réseau, aucune synthèse
vocale). À relancer après toute modification :

```bash
.venv/Scripts/python -m unittest discover -s tests
```

Pour vérifier un script d'épisode sans rien générer :

```bash
.venv/Scripts/python scripts/veille.py publish ia --dry-run
```
