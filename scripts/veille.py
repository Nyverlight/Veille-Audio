#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
veille.py - point d'entree unique, pour un domaine donne (ia, cyber, ...).

    python scripts/veille.py domains
        -> liste les domaines configures (un fichier config/<slug>.json chacun)

    python scripts/veille.py collect ia
        -> recupere les flux RSS dans work/ia/raw_news.json

    python scripts/veille.py publish ia [--date AAAA-MM-JJ]
        -> lit work/ia/script.txt et work/ia/desc.txt (ecrits par Claude),
           genere audio/ia/ia-DATE.mp3 et met a jour feed-ia.xml

Le travail editorial (entre collect et publish) est fait par Claude, selon
ROUTINE_PROMPT.md et prompts/<slug>.md.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


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


def cmd_collect(slug):
    cfg_path, _ = load_cfg(slug)
    run(SCRIPTS / "fetch_news.py", "--config", cfg_path.relative_to(ROOT).as_posix())


def cmd_publish(slug, date):
    cfg_path, cfg = load_cfg(slug)
    cfg_rel = cfg_path.relative_to(ROOT).as_posix()
    work = ROOT / "work" / slug
    script, desc_file = work / "script.txt", work / "desc.txt"
    for f in (script, desc_file):
        if not f.exists() or not f.read_text(encoding="utf-8").strip():
            sys.exit(f"ERREUR: {f.relative_to(ROOT).as_posix()} manquant ou vide.")
    desc = " ".join(desc_file.read_text(encoding="utf-8").split())

    audio = f"{cfg['audio_dir']}/{slug}-{date}.mp3"
    run(SCRIPTS / "make_audio.py", "--config", cfg_rel,
        "--in", script.relative_to(ROOT).as_posix(), "--out", audio)
    if (ROOT / audio).stat().st_size < 10_000:
        sys.exit(f"ERREUR: {audio} trop petit, episode non publie.")

    title = f"{cfg.get('episode_title_prefix', 'Veille ' + slug)} - {date}"
    run(SCRIPTS / "update_feed.py", "--config", cfg_rel,
        "--audio", audio, "--title", title, "--desc", desc)
    print(f"PUBLIE: {title} -> {audio}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("domains")
    c = sub.add_parser("collect")
    c.add_argument("domain")
    p = sub.add_parser("publish")
    p.add_argument("domain")
    p.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args()

    if args.cmd == "domains":
        print("\n".join(domains()))
    elif args.cmd == "collect":
        cmd_collect(args.domain)
    else:
        cmd_publish(args.domain, args.date)


if __name__ == "__main__":
    main()
