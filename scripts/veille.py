#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
veille.py - point d'entree unique.

    python scripts/veille.py domains
        -> liste les domaines configures (un fichier config/<slug>.json chacun)

    python scripts/veille.py collect ia [--all]
        -> recupere les flux dans work/ia/raw_news.json
           (--all : sans ecarter les actualites deja traitees)

    python scripts/veille.py publish ia [--date AAAA-MM-JJ] [--dry-run]
        -> lit work/ia/script.txt et work/ia/desc.txt (ecrits par Claude),
           genere audio/ia/ia-DATE.mp3, met a jour feed-ia.xml et archive le
           script dans episodes/ia/DATE.txt

    python scripts/veille.py deploy [--force]
        -> publie le site (flux + MP3 + vignettes) sur la branche gh-pages,
           reecrite a chaque fois en UN SEUL commit sans historique, puis
           pousse les transcriptions (episodes/) sur main

    python scripts/veille.py restore [--force]
        -> recupere audio/ et feed-*.xml depuis la branche gh-pages
           (nouveau PC, dossier local perdu)

Le travail editorial (entre collect et publish) est fait par Claude, selon
ROUTINE_PROMPT.md et prompts/<slug>.md.

Pourquoi gh-pages en un seul commit : un MP3 supprime d'une branche reste
dans son historique. En republiant chaque jour un commit orphelin, la taille
du site reste bornee a `keep_episodes` MP3 par domaine, et main ne contient
que du texte.
"""

import argparse
import datetime as dt
import html
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PAGES_BRANCH = "gh-pages"
PAGES_REF = f"origin/{PAGES_BRANCH}"

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def date_fr(d: dt.date) -> str:
    jour = "1er" if d.day == 1 else str(d.day)
    return f"{jour} {MOIS[d.month - 1]} {d.year}"


def domains():
    return sorted(p.stem for p in (ROOT / "config").glob("*.json"))


def load_cfg(slug):
    path = ROOT / "config" / f"{slug}.json"
    if not path.exists():
        sys.exit(f"ERREUR: domaine inconnu '{slug}'. Domaines : {', '.join(domains())}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def run(*args):
    cmd = [sys.executable, *map(str, args)]
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode != 0:
        sys.exit(f"ERREUR: echec de {' '.join(map(str, args))} (code {res.returncode})")


def git(*args, env=None, data=None, check=True):
    """Lance git a la racine du depot. Retourne (code, sortie bytes)."""
    full_env = dict(os.environ, **(env or {}))
    res = subprocess.run(["git", *args], cwd=ROOT, env=full_env, input=data,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and res.returncode != 0:
        err = res.stderr.decode("utf-8", "replace").strip()
        sys.exit(f"ERREUR: git {' '.join(args[:3])}… a echoue: {err}")
    return res.returncode, res.stdout


def git_text(*args, **kw) -> str:
    return git(*args, **kw)[1].decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------------
# collect / publish
# ---------------------------------------------------------------------------

def previous_scripts(slug, n=2):
    files = sorted((ROOT / "episodes" / slug).glob("*.txt"))
    return [f.relative_to(ROOT).as_posix() for f in files[-n:]]


def cmd_collect(slug, all_items):
    cfg_path, _ = load_cfg(slug)
    extra = ["--all"] if all_items else []
    run(SCRIPTS / "fetch_news.py", "--config",
        cfg_path.relative_to(ROOT).as_posix(), *extra)
    prev = previous_scripts(slug)
    if prev:
        print("Episodes precedents a relire (pour ne pas se repeter) : "
              + ", ".join(prev))


def cmd_publish(slug, date_str, dry_run):
    try:
        date = dt.date.fromisoformat(date_str)
    except ValueError:
        sys.exit(f"ERREUR: date invalide '{date_str}' (attendu AAAA-MM-JJ).")
    cfg_path, cfg = load_cfg(slug)
    cfg_rel = cfg_path.relative_to(ROOT).as_posix()
    work = ROOT / "work" / slug
    script, desc_file = work / "script.txt", work / "desc.txt"
    for f in (script, desc_file):
        if not f.exists() or not f.read_text(encoding="utf-8").strip():
            sys.exit(f"ERREUR: {f.relative_to(ROOT).as_posix()} manquant ou vide.")
    text = script.read_text(encoding="utf-8")
    desc = " ".join(desc_file.read_text(encoding="utf-8").split())[:500]
    words = len(text.split())

    audio = f"{cfg['audio_dir']}/{slug}-{date.isoformat()}.mp3"
    title = f"{cfg.get('episode_title_prefix', 'Veille ' + slug)} du {date_fr(date)}"
    print(f"Episode : {title} ({words} mots, ~{words / 160:.0f} min)")
    if "http://" in text or "https://" in text:
        print("ATTENTION: le script contient une URL (elle sera lue a voix haute).")

    if dry_run:
        print(f"ESSAI A BLANC: {audio} et {cfg['feed_file']} ne sont pas modifies.")
        return

    run(SCRIPTS / "make_audio.py", "--config", cfg_rel,
        "--in", script.relative_to(ROOT).as_posix(), "--out", audio)
    run(SCRIPTS / "update_feed.py", "--config", cfg_rel,
        "--audio", audio, "--title", title, "--desc", desc)

    # Transcription archivee (suivie dans main) : sert de memoire editoriale.
    archive = ROOT / "episodes" / slug / f"{date.isoformat()}.txt"
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(script, archive)

    # Memorise les actualites transmises, pour ne pas les resservir demain.
    raw = work / "raw_news.json"
    if raw.exists():
        try:
            import fetch_news
            fetch_news.mark_seen(cfg, json.loads(raw.read_text(encoding="utf-8")),
                                 date)
        except Exception as e:
            print(f"ATTENTION: memoire anti-repetition non mise a jour ({e}).")

    print(f"PUBLIE: {title} -> {audio}")


# ---------------------------------------------------------------------------
# deploy / restore (branche gh-pages en un seul commit)
# ---------------------------------------------------------------------------

def feed_enclosures(xml_bytes: bytes):
    """[(url, length)] des episodes d'un flux."""
    root = ET.fromstring(xml_bytes)
    out = []
    for enc in root.iter("enclosure"):
        out.append((enc.get("url", ""), enc.get("length", "0")))
    return out


def remote_pages_exists() -> bool:
    git("fetch", "--quiet", "origin", PAGES_BRANCH, check=False)
    code, _ = git("rev-parse", "--verify", "--quiet", PAGES_REF, check=False)
    return code == 0


def collect_site_files(force: bool, has_remote: bool):
    """Verifie la coherence locale et retourne (fichiers du site, podcasts)."""
    files, podcasts, problems = [], [], []
    for slug in domains():
        _, cfg = load_cfg(slug)
        base = cfg["base_url"].rstrip("/")
        feed_rel = cfg["feed_file"]
        feed = ROOT / feed_rel
        remote_count = 0
        if has_remote:
            code, blob = git("cat-file", "blob", f"{PAGES_REF}:{feed_rel}",
                             check=False)
            if code == 0:
                try:
                    remote_count = len(feed_enclosures(blob))
                except ET.ParseError:
                    remote_count = 0
        if not feed.exists():
            if remote_count:
                problems.append(f"{feed_rel} absent en local alors qu'il est "
                                f"publie ({remote_count} episodes)")
            else:
                print(f"  [{slug}] pas encore de flux : domaine ignore.")
            continue
        try:
            encs = feed_enclosures(feed.read_bytes())
        except ET.ParseError as e:
            problems.append(f"{feed_rel} illisible ({e})")
            continue
        keep = int(cfg.get("keep_episodes", 14))
        if len(encs) < min(remote_count, keep):
            problems.append(f"{feed_rel} contient {len(encs)} episode(s) en "
                            f"local contre {remote_count} en ligne")
        files.append(feed_rel)
        for url, length in encs:
            if not url.startswith(base + "/"):
                problems.append(f"{feed_rel}: URL hors site {url}")
                continue
            rel = url[len(base) + 1:]
            p = ROOT / rel
            if not p.is_file():
                problems.append(f"{rel} reference par {feed_rel} mais absent")
            elif str(p.stat().st_size) != str(length):
                problems.append(f"{rel}: taille differente de celle du flux")
            else:
                files.append(rel)
        cover = cfg.get("cover")
        if cover and (ROOT / cover).is_file():
            files.append(cover)
        podcasts.append((cfg["feed_title"], feed_rel, len(encs)))

    if problems:
        print("Incoherences detectees :")
        for p in problems:
            print(f"  - {p}")
        if not force:
            sys.exit("ERREUR: deploiement annule pour ne pas abimer le site en "
                     "ligne. Lancez `veille.py restore` pour recuperer les "
                     "fichiers publies, ou `deploy --force` si l'etat local "
                     "est bien celui voulu.")
        files = [f for f in files if (ROOT / f).is_file()]
    if not files:
        sys.exit("ERREUR: rien a publier (aucun flux local).")
    return files, podcasts


def index_html(podcasts) -> bytes:
    rows = "\n".join(
        f'    <li><strong>{html.escape(t)}</strong> — '
        f'<a href="{html.escape(f)}">{html.escape(f)}</a> ({n} épisodes)</li>'
        for t, f, n in podcasts)
    page = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>Veille Audio</title>
  <style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem;line-height:1.6}}</style>
</head>
<body>
  <h1>Veille Audio</h1>
  <p>Ajoutez l'adresse d'un flux dans votre application de podcast (« Ajouter par URL »).</p>
  <ul>
{rows}
  </ul>
</body>
</html>
"""
    return page.encode("utf-8")


def cmd_deploy(force):
    today = dt.date.today().isoformat()
    has_remote = remote_pages_exists()
    files, podcasts = collect_site_files(force, has_remote)

    # Arbre du site construit dans un index temporaire : ni la branche
    # courante ni l'index habituel ne sont touches.
    index = ROOT / "work" / ".deploy-index"
    index.parent.mkdir(exist_ok=True)
    index.unlink(missing_ok=True)
    env = {"GIT_INDEX_FILE": str(index)}
    git("-c", "core.autocrlf=false", "add", "-f", "--", *files, env=env)
    for name, content in (("index.html", index_html(podcasts)),
                          (".nojekyll", b"")):
        sha = git_text("hash-object", "-w", "--stdin", data=content)
        git("update-index", "--add", "--cacheinfo", f"100644,{sha},{name}", env=env)
    tree = git_text("write-tree", env=env)
    index.unlink(missing_ok=True)

    remote_tree = git_text("rev-parse", "--verify", "--quiet",
                           f"{PAGES_REF}^{{tree}}", check=False) if has_remote else ""
    if tree == remote_tree:
        print(f"{PAGES_BRANCH}: site deja a jour, rien a pousser.")
    else:
        # Commit SANS parent : la branche ne garde aucun historique.
        commit = git_text("commit-tree", tree, "-m", f"Veille Audio - {today}")
        git("push", "--force", "--quiet", "origin",
            f"{commit}:refs/heads/{PAGES_BRANCH}")
        mp3 = sum(1 for f in files if f.endswith(".mp3"))
        print(f"{PAGES_BRANCH}: site publie ({mp3} MP3, {len(podcasts)} flux), "
              f"commit unique {commit[:7]}.")

    # Transcriptions sur main (texte uniquement).
    branch = git_text("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        print(f"ATTENTION: branche courante '{branch}' : transcriptions non poussees.")
    else:
        if (ROOT / "episodes").is_dir():
            git("add", "-A", "--", "episodes")
            code, _ = git("diff", "--cached", "--quiet", "--", "episodes",
                          check=False)
            if code != 0:
                git("commit", "--quiet", "-m", f"Veille Audio - {today}",
                    "--", "episodes")
        code, _ = git("push", "--quiet", "origin", "main", check=False)
        if code != 0:
            git("pull", "--rebase", "--quiet", "origin", "main")
            git("push", "--quiet", "origin", "main")
        print("main: transcriptions a jour.")

    # Menage local : les anciens commits gh-pages ne sont plus references.
    git("reflog", "expire", "--expire=now",
        f"refs/remotes/origin/{PAGES_BRANCH}", check=False)
    git("gc", "--quiet", "--prune=12.hours.ago", check=False)
    print("DEPLOIEMENT TERMINE.")


def cmd_restore(force):
    if not remote_pages_exists():
        sys.exit(f"ERREUR: la branche {PAGES_BRANCH} n'existe pas sur origin.")
    restored = skipped = 0
    for path in git_text("ls-tree", "-r", "--name-only", PAGES_REF).splitlines():
        is_feed = "/" not in path and path.startswith("feed-") and path.endswith(".xml")
        if not (is_feed or path.startswith("audio/")):
            continue
        dest = ROOT / path
        if dest.exists() and not force:
            skipped += 1
            continue
        _, blob = git("cat-file", "blob", f"{PAGES_REF}:{path}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        restored += 1
    print(f"Restauration: {restored} fichier(s) recupere(s), {skipped} deja "
          f"present(s) conserve(s) (--force pour les ecraser).")


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("domains")
    c = sub.add_parser("collect")
    c.add_argument("domain")
    c.add_argument("--all", action="store_true")
    p = sub.add_parser("publish")
    p.add_argument("domain")
    p.add_argument("--date", default=dt.date.today().isoformat())
    p.add_argument("--dry-run", action="store_true")
    d = sub.add_parser("deploy")
    d.add_argument("--force", action="store_true")
    r = sub.add_parser("restore")
    r.add_argument("--force", action="store_true")
    args = ap.parse_args()

    os.chdir(ROOT)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:
            pass

    if args.cmd == "domains":
        print("\n".join(domains()))
    elif args.cmd == "collect":
        cmd_collect(args.domain, args.all)
    elif args.cmd == "publish":
        cmd_publish(args.domain, args.date, args.dry_run)
    elif args.cmd == "deploy":
        cmd_deploy(args.force)
    else:
        cmd_restore(args.force)


if __name__ == "__main__":
    main()
