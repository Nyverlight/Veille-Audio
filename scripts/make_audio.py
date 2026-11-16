#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_audio.py
Transforme un fichier texte en MP3 via edge-tts (voix neuronales Microsoft,
gratuites). La voix et le debit sont lus dans la config du domaine.

Le service est distant et parfois capricieux : on fait plusieurs essais, et
le MP3 n'est mis a sa place definitive qu'une fois complet (jamais de fichier
partiel dans audio/).

Usage:
    python scripts/make_audio.py --config config/ia.json \
        --in work/ia/script.txt --out audio/ia/ia-2026-06-05.mp3
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

try:
    import edge_tts
except ImportError:
    print("ERREUR: le module 'edge-tts' n'est pas installe. "
          "Lancez: .venv/Scripts/python -m pip install -r requirements.txt",
          file=sys.stderr)
    sys.exit(1)

MIN_BYTES = 10_000          # en dessous, le MP3 est considere comme rate
RETRY_WAITS = (5, 20)       # attentes (s) avant les 2e et 3e essais


async def synth(text: str, out_path: str, voice: str, rate: str):
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(out_path)


def synth_with_retry(text: str, out: Path, voice: str, rate: str) -> int:
    """Genere `out` (via un fichier temporaire). Retourne la taille en octets."""
    tmp = out.with_name(out.name + ".part")
    attempts = len(RETRY_WAITS) + 1
    last_err = None
    for n in range(1, attempts + 1):
        try:
            asyncio.run(synth(text, str(tmp), voice, rate))
            size = tmp.stat().st_size
            if size < MIN_BYTES:
                raise RuntimeError(f"audio trop petit ({size} octets)")
            os.replace(tmp, out)
            return size
        except Exception as e:
            last_err = e
            print(f"  essai {n}/{attempts} en echec: {type(e).__name__}: {e}",
                  file=sys.stderr)
            if n < attempts:
                time.sleep(RETRY_WAITS[n - 1])
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"synthese vocale impossible apres {attempts} essais: "
                       f"{last_err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="ex. config/ia.json")
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--out", dest="outfile", required=True)
    args = ap.parse_args()

    # Chemins relatifs a la racine du depot, d'ou que le script soit lance
    os.chdir(Path(__file__).resolve().parent.parent)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    voice = cfg.get("voice", "fr-FR-DeniseNeural")
    rate = cfg.get("rate", "+0%")

    text = Path(args.infile).read_text(encoding="utf-8").strip()
    if not text:
        print("ERREUR: le fichier texte est vide.", file=sys.stderr)
        sys.exit(1)

    out = Path(args.outfile)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Synthese vocale (voix={voice}, debit={rate}) -> {out.as_posix()}")
    try:
        size = synth_with_retry(text, out, voice, rate)
    except RuntimeError as e:
        print(f"ERREUR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {out.as_posix()} ({size} octets)")


if __name__ == "__main__":
    main()
