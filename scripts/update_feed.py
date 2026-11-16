#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_feed.py
Met a jour le flux podcast d'un domaine (ex. feed-ia.xml) en ajoutant
l'episode du jour, puis applique une retention (garde les N derniers episodes)
et supprime les MP3 de CE domaine qui ne sont plus references.

Chaque domaine a son propre flux (cle "feed_file") et son propre dossier audio
(cle "audio_dir") : la retention d'un domaine ne touche jamais aux MP3 d'un
autre domaine.

Usage:
    python scripts/update_feed.py --config config/ia.json \
        --audio audio/ia/ia-2026-06-05.mp3 \
        --title "Veille IA - 2026-06-05" \
        --desc "Resume des actualites IA du jour."
"""

import argparse
import datetime as dt
import json
import os
import sys
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES)


def rfc822(d: dt.datetime) -> str:
    return format_datetime(d)


def parse_existing(feed_path: Path):
    """Retourne la liste des episodes existants [{title,desc,guid,url,length,pubdate}]."""
    episodes = []
    if not feed_path.exists():
        return episodes
    try:
        tree = ET.parse(feed_path)
    except Exception:
        return episodes
    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        return episodes
    for item in channel.findall("item"):
        enc = item.find("enclosure")
        episodes.append({
            "title": (item.findtext("title") or "").strip(),
            "desc": (item.findtext("description") or "").strip(),
            "guid": (item.findtext("guid") or "").strip(),
            "url": enc.get("url") if enc is not None else "",
            "length": enc.get("length") if enc is not None else "0",
            "pubdate": (item.findtext("pubDate") or "").strip(),
        })
    return episodes


def build_feed(cfg, episodes):
    base = cfg["base_url"].rstrip("/")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = cfg["feed_title"]
    ET.SubElement(channel, "link").text = base
    ET.SubElement(channel, "language").text = cfg.get("feed_language", "fr-FR")
    ET.SubElement(channel, "description").text = cfg["feed_description"]
    ET.SubElement(channel, "{%s}author" % ITUNES).text = cfg.get("feed_author", "")
    img = ET.SubElement(channel, "{%s}image" % ITUNES)
    img.set("href", base + "/" + cfg.get("cover", "cover.jpg"))
    for ep in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep["title"]
        ET.SubElement(item, "description").text = ep["desc"]
        ET.SubElement(item, "guid").text = ep["guid"]
        ET.SubElement(item, "pubDate").text = ep["pubdate"]
        ET.SubElement(item, "enclosure", {
            "url": ep["url"],
            "length": str(ep["length"]),
            "type": "audio/mpeg",
        })
    return ET.ElementTree(rss)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="ex. config/ia.json")
    ap.add_argument("--audio", required=True, help="chemin du MP3 du jour")
    ap.add_argument("--title", required=True)
    ap.add_argument("--desc", required=True)
    ap.add_argument("--feed", default=None, help="defaut: cle feed_file")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    base = cfg["base_url"].rstrip("/")
    keep = int(cfg.get("keep_episodes", 14))
    feed_path = Path(args.feed or cfg.get("feed_file", "feed.xml"))
    audio_dir = Path(cfg.get("audio_dir", "audio"))

    audio_path = Path(args.audio)
    if audio_path.is_absolute():
        audio_path = audio_path.resolve().relative_to(root)
    if not audio_path.exists():
        print(f"ERREUR: fichier audio introuvable: {audio_path}", file=sys.stderr)
        sys.exit(1)
    if audio_path.parent.as_posix() != audio_dir.as_posix():
        print(f"ERREUR: le MP3 doit etre dans {audio_dir.as_posix()}/ "
              f"(recu: {audio_path.as_posix()})", file=sys.stderr)
        sys.exit(1)

    now = dt.datetime.now(dt.timezone.utc)
    url = base + "/" + audio_path.as_posix()
    new_ep = {
        "title": args.title,
        "desc": args.desc,
        "guid": url,
        "url": url,
        "length": str(audio_path.stat().st_size),
        "pubdate": rfc822(now),
    }

    episodes = parse_existing(feed_path)
    # Evite les doublons si on relance le meme jour
    episodes = [e for e in episodes if e["guid"] != new_ep["guid"]]
    episodes.insert(0, new_ep)
    episodes = episodes[:keep]

    tree = build_feed(cfg, episodes)
    ET.indent(tree, space="  ")
    tree.write(feed_path, encoding="utf-8", xml_declaration=True)
    print(f"{feed_path.as_posix()} mis a jour: {len(episodes)} episode(s).")

    # Retention: supprime les MP3 de CE domaine qui ne sont plus references
    referenced = {e["url"][len(base) + 1:] for e in episodes
                  if e["url"].startswith(base + "/")}
    removed = 0
    for mp3 in audio_dir.glob("*.mp3"):
        if mp3.as_posix() not in referenced:
            mp3.unlink()
            removed += 1
    print(f"Retention: {removed} ancien(s) MP3 supprime(s) dans "
          f"{audio_dir.as_posix()}/.")


if __name__ == "__main__":
    main()
