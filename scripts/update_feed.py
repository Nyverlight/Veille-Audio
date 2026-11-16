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

Securites :
  - si le flux existant est illisible, on s'arrete SANS rien ecrire ni
    supprimer (sinon la retention effacerait tous les MP3 du domaine) ;
  - le flux est ecrit dans un fichier temporaire puis renomme (ecriture
    atomique) ; la retention ne s'execute qu'ensuite.

Usage:
    python scripts/update_feed.py --config config/ia.json \
        --audio audio/ia/ia-2026-06-05.mp3 \
        --title "Veille IA du 5 juin 2026" \
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
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("atom", ATOM)

# edge-tts produit du MP3 mono a debit constant 48 kbit/s.
MP3_BYTES_PER_SECOND = 48_000 / 8


class FeedError(Exception):
    pass


def rfc822(d: dt.datetime) -> str:
    return format_datetime(d)


def estimate_duration(length) -> str:
    """Duree en secondes (texte) estimee depuis la taille du MP3."""
    try:
        return str(max(1, round(int(length) / MP3_BYTES_PER_SECOND)))
    except (TypeError, ValueError):
        return "0"


def parse_existing(feed_path: Path):
    """Retourne la liste des episodes existants. Leve FeedError si le flux
    existe mais n'est pas lisible."""
    if not feed_path.exists():
        return []
    try:
        root = ET.parse(feed_path).getroot()
    except Exception as e:
        raise FeedError(f"{feed_path.as_posix()} illisible ({e})")
    channel = root.find("channel")
    if channel is None:
        raise FeedError(f"{feed_path.as_posix()} sans element <channel>")
    episodes = []
    for item in channel.findall("item"):
        enc = item.find("enclosure")
        length = enc.get("length") if enc is not None else "0"
        episodes.append({
            "title": (item.findtext("title") or "").strip(),
            "desc": (item.findtext("description") or "").strip(),
            "guid": (item.findtext("guid") or "").strip(),
            "url": enc.get("url") if enc is not None else "",
            "length": length,
            "pubdate": (item.findtext("pubDate") or "").strip(),
            "duration": (item.findtext("{%s}duration" % ITUNES) or "").strip()
                        or estimate_duration(length),
        })
    return episodes


def build_feed(cfg, episodes, now: dt.datetime):
    base = cfg["base_url"].rstrip("/")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = cfg["feed_title"]
    ET.SubElement(channel, "link").text = base
    ET.SubElement(channel, "{%s}link" % ATOM, {
        "href": base + "/" + cfg.get("feed_file", "feed.xml"),
        "rel": "self",
        "type": "application/rss+xml",
    })
    ET.SubElement(channel, "language").text = cfg.get("feed_language", "fr-FR")
    ET.SubElement(channel, "description").text = cfg["feed_description"]
    ET.SubElement(channel, "lastBuildDate").text = rfc822(now)
    ET.SubElement(channel, "{%s}author" % ITUNES).text = cfg.get("feed_author", "")
    ET.SubElement(channel, "{%s}explicit" % ITUNES).text = "false"
    ET.SubElement(channel, "{%s}category" % ITUNES,
                  {"text": cfg.get("feed_category", "Technology")})
    img = ET.SubElement(channel, "{%s}image" % ITUNES)
    img.set("href", base + "/" + cfg.get("cover", "cover.jpg"))
    for ep in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep["title"]
        ET.SubElement(item, "description").text = ep["desc"]
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = ep["guid"]
        ET.SubElement(item, "pubDate").text = ep["pubdate"]
        ET.SubElement(item, "{%s}duration" % ITUNES).text = ep["duration"]
        ET.SubElement(item, "enclosure", {
            "url": ep["url"],
            "length": str(ep["length"]),
            "type": "audio/mpeg",
        })
    return ET.ElementTree(rss)


def write_atomic(tree, feed_path: Path) -> None:
    ET.indent(tree, space="  ")
    tmp = feed_path.with_name(feed_path.name + ".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    ET.parse(tmp)                 # relecture : on ne publie pas un XML casse
    os.replace(tmp, feed_path)


def update(cfg, audio_path: Path, title: str, desc: str, feed_path: Path,
           now: dt.datetime = None):
    """Ajoute l'episode, ecrit le flux, applique la retention.
    Chemins relatifs au repertoire courant. Retourne (nb episodes, nb supprimes)."""
    base = cfg["base_url"].rstrip("/")
    keep = int(cfg.get("keep_episodes", 14))
    audio_dir = Path(cfg.get("audio_dir", "audio"))
    now = now or dt.datetime.now(dt.timezone.utc)

    if not audio_path.exists():
        raise FeedError(f"fichier audio introuvable: {audio_path.as_posix()}")
    if audio_path.parent.as_posix() != audio_dir.as_posix():
        raise FeedError(f"le MP3 doit etre dans {audio_dir.as_posix()}/ "
                        f"(recu: {audio_path.as_posix()})")

    url = base + "/" + audio_path.as_posix()
    size = audio_path.stat().st_size
    new_ep = {
        "title": title,
        "desc": desc,
        "guid": url,
        "url": url,
        "length": str(size),
        "pubdate": rfc822(now),
        "duration": estimate_duration(size),
    }

    episodes = parse_existing(feed_path)          # leve FeedError si illisible
    # Evite les doublons si on relance le meme jour
    episodes = [e for e in episodes if e["guid"] != new_ep["guid"]]
    episodes.insert(0, new_ep)
    episodes = episodes[:keep]

    write_atomic(build_feed(cfg, episodes, now), feed_path)

    # Retention: supprime les MP3 de CE domaine qui ne sont plus references
    referenced = {e["url"][len(base) + 1:] for e in episodes
                  if e["url"].startswith(base + "/")}
    removed = 0
    for mp3 in audio_dir.glob("*.mp3"):
        if mp3.as_posix() not in referenced:
            mp3.unlink()
            removed += 1
    return len(episodes), removed


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
    feed_path = Path(args.feed or cfg.get("feed_file", "feed.xml"))
    audio_path = Path(args.audio)
    if audio_path.is_absolute():
        audio_path = audio_path.resolve().relative_to(root)

    try:
        count, removed = update(cfg, audio_path, args.title, args.desc, feed_path)
    except FeedError as e:
        print(f"ERREUR: {e}. Rien n'a ete modifie ni supprime.", file=sys.stderr)
        sys.exit(1)

    print(f"{feed_path.as_posix()} mis a jour: {count} episode(s).")
    print(f"Retention: {removed} ancien(s) MP3 supprime(s) dans "
          f"{cfg.get('audio_dir', 'audio')}/.")


if __name__ == "__main__":
    main()
