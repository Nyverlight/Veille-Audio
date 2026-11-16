#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_news.py
Recupere les entrees des sources d'un domaine (flux RSS/Atom, plus le
catalogue JSON CISA KEV), filtre sur une fenetre temporelle, dedoublonne
(par lien et par titre normalise) et ecrit le resultat dans
work/<domaine>/raw_news.json.

Le tri editorial fin (fusion semantique, traduction, resume) est fait
ENSUITE par Claude, pas ici.

Points cles :
  - Telechargement en imitant l'empreinte TLS d'un navigateur (curl_cffi),
    repli sur requests. Flux recuperes en parallele.
  - Fenetre adaptative : si le dernier episode publie date de plus de
    `lookback_hours`, la fenetre s'allonge pour ne rien perdre (plafond
    `max_lookback_hours`).
  - Anti-repetition : les actualites deja transmises lors d'un episode
    publie un jour precedent (work/<domaine>/seen.json) sont ecartees.
  - Quota par flux (`max_items_per_feed`) pour qu'un flux bavard n'evince
    pas les autres, puis plafond global (`max_items_fetch`).
  - Le texte recupere est NON FIABLE : il est nettoye (balises, entites,
    caracteres de controle) et tronque, et les telechargements sont
    plafonnes en taille.

Dependances : requests, curl_cffi (optionnel mais recommande)

Usage:
    python scripts/fetch_news.py --config config/ia.json
    (sortie par defaut : work/<domain_slug>/raw_news.json)
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' n'est pas installe. "
          "Lancez: .venv/Scripts/python -m pip install -r requirements.txt",
          file=sys.stderr)
    sys.exit(1)

# curl_cffi imite l'empreinte TLS/JA3 d'un vrai navigateur : necessaire pour
# les flux derriere une protection anti-bot (Cloudflare/DataDome) qui
# renvoient 403 a requests meme avec un bon User-Agent. Si absent, on retombe
# sur requests.
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CFFI = True
except ImportError:
    _HAS_CFFI = False


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/rss+xml, application/atom+xml, "
        "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

MAX_FEED_BYTES = 10 * 1024 * 1024   # plafond de taille par source
MAX_TITLE_CHARS = 300
MAX_SUMMARY_CHARS = 600
SEEN_KEEP_DAYS = 7
FETCH_WORKERS = 8


# ---------------------------------------------------------------------------
# Nettoyage / normalisation
# ---------------------------------------------------------------------------

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‏"
                         r"‪-‮⁠-⁤﻿]")


def normalize_title(title: str) -> str:
    """Normalise un titre pour comparaison (minuscules, sans accents/ponctuation)."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def clean_text(raw: str, limit: int = 0) -> str:
    """Texte brut sur : sans balises HTML, entites decodees, sans caracteres
    de controle ni invisibles, espaces compactes, tronque a `limit`."""
    txt = re.sub(r"<[^>]+>", " ", raw or "")
    txt = html.unescape(txt)
    txt = re.sub(r"<[^>]+>", " ", txt)      # balises qui etaient echappees
    txt = _CONTROL_RE.sub(" ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if limit and len(txt) > limit:
        txt = txt[:limit].rstrip() + "…"
    return txt


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2}).*?(Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_ONLY_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})$")


def _parse_iso(s: str):
    """Parse une date ISO 8601 basique en datetime UTC."""
    s = s.strip()
    m = _DATE_ONLY_RE.match(s)
    if m:
        # Date sans heure (ex. CISA KEV) : on prend midi UTC.
        y, mo, d = (int(x) for x in m.groups())
        return dt.datetime(y, mo, d, 12, tzinfo=dt.timezone.utc)
    m = _ISO_RE.match(s)
    if not m:
        return None
    parts = [int(x) for x in m.groups()[:6]]
    tz_str = m.group(7)
    if tz_str in (None, "Z", "+00:00", "-00:00"):
        tz = dt.timezone.utc
    else:
        sign = 1 if tz_str[0] == "+" else -1
        tz_str_clean = tz_str[1:].replace(":", "")
        h, mi = int(tz_str_clean[:2]), int(tz_str_clean[2:])
        tz = dt.timezone(dt.timedelta(hours=sign * h, minutes=sign * mi))
    return dt.datetime(*parts, tzinfo=tz).astimezone(dt.timezone.utc)


def parse_date(date_str: str):
    """Parse une date RSS (RFC 2822) ou Atom (ISO 8601) -> datetime UTC ou None."""
    if not date_str:
        return None
    date_str = date_str.strip()
    try:
        result = _parse_iso(date_str)
        if result:
            return result
    except Exception:
        pass
    try:
        d = parsedate_to_datetime(date_str)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Parsing RSS 2.0 / Atom 1.0 / CISA KEV (JSON)
# ---------------------------------------------------------------------------

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc":   "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def _text(el, *paths):
    """Cherche le premier path qui retourne un texte non vide."""
    for path in paths:
        node = el.find(path, _NS)
        if node is not None and node.text:
            return node.text.strip()
    return ""


def parse_rss_feed(xml_bytes: bytes, url: str) -> dict:
    """
    Parse un flux RSS 2.0 ou Atom 1.0 depuis des bytes bruts.
    Retourne {"title": str, "entries": [{"title","link","published","summary"}]}.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"XML invalide : {e}")

    tag = root.tag  # peut contenir un namespace ex. {http://...}feed

    # --- Atom ---
    if tag.rsplit("}", 1)[-1] == "feed":
        feed_title = _text(root, "atom:title", "title") or url
        entries = []
        for entry in root.findall("atom:entry", _NS) or root.findall("entry"):
            title = _text(entry, "atom:title", "title")
            if not title:
                continue
            link = ""
            for lk in entry.findall("atom:link", _NS) or entry.findall("link"):
                rel = lk.get("rel", "alternate")
                if rel in ("alternate", ""):
                    link = lk.get("href", "")
                    break
            published = _text(entry, "atom:published", "atom:updated",
                              "published", "updated")
            summary = _text(entry, "atom:summary", "atom:content",
                            "summary", "content")
            entries.append({
                "title": title,
                "link": link.strip(),
                "published": published,
                "summary": summary,
            })
        return {"title": feed_title, "entries": entries}

    # --- RSS 2.0 (root = <rss> ou <rdf:RDF>) ---
    channel = root.find("channel")
    if channel is None:
        channel = root
    feed_title = _text(channel, "title") or url
    entries = []
    item_iter = list(channel.findall("item")) or list(root.findall("item"))
    for item in item_iter:
        title = _text(item, "title")
        if not title:
            continue
        link = _text(item, "link", "dc:identifier")
        if not link:
            lk_el = item.find("link")
            if lk_el is not None:
                link = ((lk_el.text or "") + (lk_el.tail or "")).strip()
        published = _text(item, "pubDate", "dc:date", "published")
        summary = _text(item, "description", "content:encoded", "summary")
        entries.append({
            "title": title,
            "link": link.strip(),
            "published": published,
            "summary": summary,
        })
    return {"title": feed_title, "entries": entries}


def parse_kev_json(raw: bytes) -> dict:
    """Catalogue CISA KEV (vulnerabilites activement exploitees), au format JSON."""
    data = json.loads(raw.decode("utf-8-sig"))
    entries = []
    for v in data.get("vulnerabilities", []):
        cve = str(v.get("cveID", "")).strip()
        if not cve:
            continue
        summary = str(v.get("shortDescription", ""))
        if str(v.get("knownRansomwareCampaignUse", "")).lower() == "known":
            summary += " Exploitation connue dans des campagnes de ransomware."
        entries.append({
            "title": f"{cve} activement exploitee : {v.get('vendorProject', '')} "
                     f"{v.get('product', '')} - {v.get('vulnerabilityName', '')}",
            "link": f"https://nvd.nist.gov/vuln/detail/{cve}",
            "published": str(v.get("dateAdded", "")),
            "summary": summary,
        })
    return {"title": "CISA KEV (vulnerabilites activement exploitees)",
            "entries": entries}


def parse_source(raw: bytes, url: str) -> dict:
    """Aiguille vers le bon parseur selon le contenu."""
    if raw.lstrip()[:1] == b"{":
        return parse_kev_json(raw)
    return parse_rss_feed(raw, url)


# ---------------------------------------------------------------------------
# Telechargement
# ---------------------------------------------------------------------------

# Profils de navigateurs a imiter (empreinte TLS + en-tetes coherents). On en
# essaie plusieurs car un WAF qui bloque Chrome laisse parfois passer Safari
# ou Firefox. NE PAS forcer d'en-tete User-Agent ici : curl_cffi pose lui-meme
# un jeu d'en-tetes coherent avec l'empreinte TLS choisie.
_IMPERSONATE_PROFILES = ["chrome", "safari170", "firefox133", "edge101"]


def _check_size(content: bytes) -> bytes:
    if len(content) > MAX_FEED_BYTES:
        raise ValueError(f"reponse trop volumineuse ({len(content)} octets)")
    return content


def _requests_get_capped(url: str, timeout: int) -> bytes:
    """GET via requests, en arretant la lecture au-dela de MAX_FEED_BYTES."""
    with requests.get(url, headers=BROWSER_HEADERS, timeout=timeout,
                      stream=True) as resp:
        resp.raise_for_status()
        chunks, total = [], 0
        for chunk in resp.iter_content(65536):
            total += len(chunk)
            if total > MAX_FEED_BYTES:
                raise ValueError("reponse trop volumineuse")
            chunks.append(chunk)
        return b"".join(chunks)


def fetch_feed(url: str, timeout: int = 20) -> dict:
    """
    Telecharge et parse une source. Leve une exception en cas d'echec definitif.
    """
    last_err = None

    if _HAS_CFFI:
        for profile in _IMPERSONATE_PROFILES:
            try:
                resp = cffi_requests.get(url, impersonate=profile,
                                         timeout=timeout)
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                continue
            if resp.status_code == 200:
                return parse_source(_check_size(resp.content), url)
            last_err = f"HTTP {resp.status_code}"
            # 403/429/503 = anti-bot ou limite de debit -> un autre profil
            # peut passer. Tout autre code ne sera pas resolu ainsi.
            if resp.status_code not in (403, 429, 503):
                break

    try:
        return parse_source(_requests_get_capped(url, timeout), url)
    except Exception as e:
        if last_err:
            raise RuntimeError(f"{last_err} (repli requests: {e})")
        raise


# ---------------------------------------------------------------------------
# Fenetre adaptative et memoire des actualites deja traitees
# ---------------------------------------------------------------------------

def last_episode_time(feed_path: Path):
    """Date (UTC) du dernier episode publie dans le flux podcast, ou None."""
    try:
        root = ET.parse(feed_path).getroot()
    except Exception:
        return None
    dates = [parse_date(el.text or "") for el in root.iter("pubDate")]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def effective_lookback(cfg: dict, now: dt.datetime) -> float:
    """Fenetre en heures : au moins lookback_hours, etendue jusqu'au dernier
    episode publie (+2 h de marge), plafonnee a max_lookback_hours."""
    base = float(cfg.get("lookback_hours", 30))
    cap = float(cfg.get("max_lookback_hours", 96))
    last = last_episode_time(Path(cfg.get("feed_file", "feed.xml")))
    if last is None:
        return base
    since = (now - last).total_seconds() / 3600 + 2
    return max(base, min(since, cap))


def seen_path(cfg: dict) -> Path:
    return Path("work") / cfg["domain_slug"] / "seen.json"


def load_seen(path: Path, today: dt.date) -> dict:
    """{cle: 'AAAA-MM-JJ' de publication}, purge des entrees trop anciennes."""
    try:
        seen = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    limit = (today - dt.timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    return {k: v for k, v in seen.items()
            if isinstance(v, str) and v >= limit}


def item_keys(item: dict):
    """Cles d'identification d'une actualite (lien et titre normalise)."""
    keys = []
    if item.get("link"):
        keys.append("l:" + item["link"])
    norm = normalize_title(item.get("title", ""))
    if norm:
        keys.append("t:" + norm)
    return keys


def mark_seen(cfg: dict, items: list, day: dt.date) -> None:
    """Memorise les actualites transmises pour l'episode publie le `day`."""
    path = seen_path(cfg)
    seen = load_seen(path, day)
    for it in items:
        for k in item_keys(it):
            seen.setdefault(k, day.isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def read_sources(sources_file: Path) -> list:
    sources = []
    for line in sources_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            sources.append(line)
    return sources


def _fetch_safe(url: str):
    try:
        return fetch_feed(url)
    except Exception as e:
        return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="ex. config/ia.json")
    ap.add_argument("--out", default=None,
                    help="defaut: work/<domain_slug>/raw_news.json")
    ap.add_argument("--all", action="store_true",
                    help="ignore la memoire des actualites deja traitees")
    args = ap.parse_args()

    # Chemins relatifs a la racine du depot, d'ou que le script soit lance
    os.chdir(Path(__file__).resolve().parent.parent)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    max_items = int(cfg.get("max_items_fetch", 60))
    per_feed = int(cfg.get("max_items_per_feed", 8))

    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    lookback_hours = effective_lookback(cfg, now)
    cutoff = now - dt.timedelta(hours=lookback_hours)

    sources = read_sources(Path(cfg["sources_file"]))
    seen = {} if args.all else load_seen(seen_path(cfg), today)
    today_iso = today.isoformat()

    print(f"=== Recuperation de {len(sources)} flux "
          f"(fenetre: {lookback_hours:.0f}h) ===")

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(_fetch_safe, sources))

    seen_run: set = set()
    items = []
    already_covered = 0
    feeds_with_items = 0
    feeds_reachable_empty = 0
    feeds_failed = []  # (url, raison)

    for url, feed in zip(sources, results):
        if isinstance(feed, Exception):
            print(f"  [ECHEC] {url} -> {feed}")
            feeds_failed.append((url, str(feed)))
            continue

        source_name = clean_text(feed["title"], 120) or url
        raw_count = len(feed["entries"])
        kept = []

        for e in feed["entries"]:
            when = parse_date(e["published"])
            # On garde si recent, ou si date inconnue (la memoire seen.json
            # evite de les repeter d'un jour sur l'autre).
            if when is not None and when < cutoff:
                continue

            item = {
                "title": clean_text(e["title"], MAX_TITLE_CHARS),
                "link": clean_text(e["link"], 500),
                "source": source_name,
                "published": when.isoformat() if when else None,
                "summary": clean_text(e["summary"], MAX_SUMMARY_CHARS),
            }
            if not item["title"]:
                continue
            keys = item_keys(item)
            if any(k in seen_run for k in keys):
                continue
            seen_run.update(keys)
            # Deja transmis pour un episode publie un jour precedent
            if any(seen.get(k, today_iso) < today_iso for k in keys):
                already_covered += 1
                continue
            kept.append(item)

        # Quota par flux : on garde les plus recents
        kept.sort(key=lambda x: x["published"] or "", reverse=True)
        kept = kept[:per_feed]
        items.extend(kept)

        # kept/raw : 0/0 -> flux vide ou mal parse ; 0/N -> tout est hors
        # fenetre ou deja traite.
        print(f"  [OK]    {source_name}: {len(kept)}/{raw_count} item(s) retenu(s)")
        if kept:
            feeds_with_items += 1
        else:
            feeds_reachable_empty += 1

    # Tri par date (les plus recents d'abord), inconnus a la fin
    items.sort(key=lambda x: x["published"] or "", reverse=True)
    items = items[:max_items]

    out = Path(args.out or f"work/{cfg['domain_slug']}/raw_news.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    print("=== Sante des flux ===")
    print(f"  Avec items            : {feeds_with_items}")
    print(f"  Joignables mais vides : {feeds_reachable_empty}")
    print(f"  En echec (reseau/URL) : {len(feeds_failed)}")
    if feeds_failed:
        print("  -> Flux en echec a verifier (anti-bot ou URL morte) :")
        for url, reason in feeds_failed:
            print(f"       {url}")
    if already_covered:
        print(f"  Ecartees car deja traitees un jour precedent : {already_covered}")

    print(f"=== {len(items)} actualite(s) ecrite(s) dans {out.as_posix()} ===")
    if not items:
        print("ATTENTION: aucune actualite recuperee. "
              "Verifiez la connexion Internet et la validite des URLs du "
              "fichier de sources.")


if __name__ == "__main__":
    main()
