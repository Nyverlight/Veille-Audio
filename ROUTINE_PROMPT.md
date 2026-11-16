# Instruction de la tâche programmée « Veille Audio »

Tu produis ma veille audio quotidienne, un épisode de podcast par domaine.
Tu travailles dans le dépôt local `Veille-Audio`, sur Windows. Utilise l'outil
Bash (Git Bash), lance toutes les commandes depuis la racine du dépôt, et
utilise toujours l'interpréteur Python du dépôt : `.venv/Scripts/python`.

## 1. Préparation
- `git pull --ff-only origin main` (récupère d'éventuelles modifications).
- Détermine la date du jour au format AAAA-MM-JJ (variable DATE).
- Liste les domaines : `.venv/Scripts/python scripts/veille.py domains`
  (aujourd'hui : `cyber` et `ia`).

## 2. Pour CHAQUE domaine (variable D), l'un après l'autre

### 2a. Collecte
- `.venv/Scripts/python scripts/veille.py collect D`
- Lis `work/D/raw_news.json`.
- Si aucune actualité : écris un court épisode disant qu'aucune actualité
  marquante n'a été détectée aujourd'hui, puis passe à l'étape 2d.

### 2b. Travail éditorial (le cœur de la qualité — c'est toi qui le fais)
Lis `prompts/D.md` : ce sont les consignes propres au domaine (public,
hiérarchie, sujets à écarter). En plus de ces consignes :
- **Traduis en français** tout ce qui vient de sources anglophones.
- Pour chaque sujet retenu, rédige un résumé court, clair et factuel
  (2 à 5 phrases), en mentionnant la ou les sources à l'oral.

### 2c. Rédaction du script parlé
Écris le texte final dans `work/D/script.txt`. Contraintes :
- **Texte parlé pur** : aucune balise, aucun symbole de liste, aucune URL lue
  à voix haute, aucun markdown. Ce texte sera lu tel quel par une voix de
  synthèse.
- Commence par une intro courte : le domaine, la date du jour et le nombre de
  sujets.
- Enchaîne les sujets en paragraphes fluides, avec des transitions naturelles.
- Termine par une phrase de clôture brève.
- Vise une durée d'écoute de 5 à 8 minutes (environ 800 à 1300 mots). Si
  l'actualité est dense, privilégie la sélection à l'exhaustivité.

Écris aussi, dans `work/D/desc.txt`, une description d'une seule ligne de
l'épisode (les 2-3 sujets principaux), pour le flux podcast.

### 2d. Audio et flux
- `.venv/Scripts/python scripts/veille.py publish D --date DATE`
  (génère `audio/D/D-DATE.mp3` et met à jour `feed-D.xml`).
- Si cette commande échoue pour un domaine, note l'erreur et **continue avec
  le domaine suivant** : un domaine en échec ne doit pas bloquer l'autre.

## 3. Publication (une seule fois, après tous les domaines)
- `git add -A audio/ feed-*.xml` (y compris les suppressions dues à la
  rétention). N'ajoute rien d'autre : `work/` et `.venv/` sont ignorés.
- Commite avec le message « Veille Audio - DATE » (préciser entre parenthèses
  un domaine en échec, le cas échéant), puis `git push origin main`.
- En cas de refus du push (dépôt distant en avance) : `git pull --rebase
  origin main`, puis repousse.

## Règles
- Ne publie jamais d'épisode sans audio généré avec succès.
- Ne modifie ni les scripts, ni la configuration, ni les sources : signale
  plutôt les problèmes (flux en `[ECHEC]`, etc.) dans le compte rendu.
- Ne signe pas les commits et ne refais pas de commit (amend).
- Termine par un compte rendu court : pour chaque domaine, nombre
  d'actualités collectées, sujets retenus, flux en échec, et statut de
  publication.
