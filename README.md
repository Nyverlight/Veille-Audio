# Veille Audio

Veille quotidienne en podcast, un flux par domaine (aujourd'hui **IA** et
**cybersécurité**). Chaque matin, une tâche programmée Claude, exécutée sur ce
PC :

1. récupère les flux RSS de chaque domaine (`scripts/fetch_news.py`) ;
2. fait le tri éditorial et rédige un script parlé en français (Claude) ;
3. le transforme en MP3 avec une voix neuronale (`scripts/make_audio.py`,
   edge-tts) ;
4. met à jour le flux podcast du domaine (`scripts/update_feed.py`) ;
5. commite et pousse sur `main` → publié par GitHub Pages.

## Flux à ajouter dans l'app podcast

| Domaine | URL du flux |
|---|---|
| IA | `https://nyverlight.github.io/Veille-Audio/feed-ia.xml` |
| Cybersécurité | `https://nyverlight.github.io/Veille-Audio/feed-cyber.xml` |

## Organisation

```
config/<domaine>.json    voix, fenêtre, titre du flux, rétention…
sources/<domaine>.txt    flux RSS (une URL par ligne)
prompts/<domaine>.md     consignes éditoriales propres au domaine
ROUTINE_PROMPT.md        déroulé complet suivi par la tâche programmée
scripts/veille.py        point d'entrée : domains | collect D | publish D
audio/<domaine>/         MP3 publiés (rétention : keep_episodes)
feed-<domaine>.xml       flux podcast (générés)
covers/<domaine>.jpg     vignettes des podcasts
work/                    fichiers intermédiaires (non suivis)
```

## Installation locale (une fois)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Test manuel d'un domaine :

```bash
.venv/Scripts/python scripts/veille.py collect cyber
```

## Ajouter un domaine

1. Créer `config/<slug>.json` (copie d'un existant ; changer `domain_slug`,
   `episode_title_prefix`, `sources_file`, `editorial_file`, `feed_file`,
   `audio_dir`, `cover`, `feed_title`, `feed_description`).
2. Créer `sources/<slug>.txt`, `prompts/<slug>.md`, `audio/<slug>/.gitkeep`
   et `covers/<slug>.jpg`.
3. C'est tout : la tâche traite automatiquement chaque fichier de `config/`.

## Dépannage

- **`[ECHEC]` dans la collecte** : 403 (anti-bot) ou 404 (URL morte) → corriger
  `sources/<domaine>.txt`.
- **Pas de MP3** : le service de synthèse d'edge-tts est injoignable ou a
  changé → mettre à jour edge-tts (`pip install -U edge-tts`).
- **L'app podcast ne voit pas le flux** : vérifier que GitHub Pages est actif
  (Settings → Pages → branche `main`, dossier `/`) et que `base_url` des
  configs correspond exactement à l'URL Pages.
- **Pas d'épisode un matin** : l'app Claude Desktop doit être ouverte et le PC
  allumé à l'heure de la tâche.
