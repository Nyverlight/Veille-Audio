# -*- coding: utf-8 -*-
"""
Tests hors ligne (aucun acces reseau, aucun appel a edge-tts).

    .venv/Scripts/python -m unittest discover -s tests -v
"""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_news  # noqa: E402
import update_feed  # noqa: E402
import veille  # noqa: E402

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Flux &amp; Test</title>
<item><title>Titre &lt;b&gt;un&lt;/b&gt;</title><link>https://ex.test/a</link>
<pubDate>Mon, 16 Nov 2026 08:00:00 +0100</pubDate>
<description><![CDATA[<p>R&eacute;sum&eacute; <a href="x">lien</a></p>]]></description></item>
<item><title></title><link>https://ex.test/vide</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Test</title>
<entry><title>Entree</title><link rel="alternate" href="https://ex.test/b"/>
<updated>2026-11-16T07:00:00Z</updated><summary>Texte</summary></entry></feed>"""

KEV = json.dumps({"vulnerabilities": [{
    "cveID": "CVE-2026-0001", "vendorProject": "Acme", "product": "Routeur",
    "vulnerabilityName": "Injection", "dateAdded": "2026-11-15",
    "shortDescription": "Desc.", "knownRansomwareCampaignUse": "Known"}]}).encode()


class TestParsing(unittest.TestCase):
    def test_rss(self):
        feed = fetch_news.parse_source(RSS, "u")
        self.assertEqual(feed["title"], "Flux & Test")
        self.assertEqual(len(feed["entries"]), 1)      # item sans titre ignore
        e = feed["entries"][0]
        self.assertEqual(e["link"], "https://ex.test/a")
        self.assertEqual(fetch_news.clean_text(e["title"]), "Titre un")
        self.assertEqual(fetch_news.clean_text(e["summary"]), "Résumé lien")

    def test_atom(self):
        feed = fetch_news.parse_source(ATOM, "u")
        self.assertEqual(feed["title"], "Atom Test")
        self.assertEqual(feed["entries"][0]["link"], "https://ex.test/b")

    def test_kev_json(self):
        feed = fetch_news.parse_source(KEV, "u")
        e = feed["entries"][0]
        self.assertIn("CVE-2026-0001", e["title"])
        self.assertIn("ransomware", e["summary"])
        self.assertEqual(fetch_news.parse_date(e["published"]),
                         dt.datetime(2026, 11, 15, 12, tzinfo=dt.timezone.utc))

    def test_invalid_xml(self):
        with self.assertRaises(ValueError):
            fetch_news.parse_source(b"<rss><channel>", "u")

    def test_dates(self):
        utc = dt.timezone.utc
        self.assertEqual(fetch_news.parse_date("Mon, 16 Nov 2026 08:00:00 +0100"),
                         dt.datetime(2026, 11, 16, 7, tzinfo=utc))
        self.assertEqual(fetch_news.parse_date("2026-11-16T09:30:00+02:00"),
                         dt.datetime(2026, 11, 16, 7, 30, tzinfo=utc))
        self.assertIsNone(fetch_news.parse_date("n'importe quoi"))
        self.assertIsNone(fetch_news.parse_date(""))

    def test_clean_text(self):
        dirty = "A​<script>x</script>\x00 B &amp; C   \n D"
        self.assertEqual(fetch_news.clean_text(dirty), "A x B & C D")
        self.assertEqual(len(fetch_news.clean_text("x" * 50, 10)), 11)

    def test_date_fr(self):
        self.assertEqual(veille.date_fr(dt.date(2026, 11, 16)), "16 novembre 2026")
        self.assertEqual(veille.date_fr(dt.date(2026, 8, 1)), "1er août 2026")


class InTmpDir(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.cfg = {
            "domain_slug": "t", "base_url": "https://ex.test/site",
            "feed_file": "feed-t.xml", "audio_dir": "audio/t",
            "cover": "covers/t.jpg", "feed_title": "Titre é",
            "feed_description": "Desc", "keep_episodes": 2,
            "lookback_hours": 30, "max_lookback_hours": 96,
        }
        Path("audio/t").mkdir(parents=True)
        Path("audio/autre").mkdir(parents=True)
        Path("audio/autre/autre-1.mp3").write_bytes(b"z" * 10)

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()

    def add(self, day, when=None):
        p = Path(f"audio/t/t-{day}.mp3")
        p.write_bytes(b"x" * 60_000)
        return update_feed.update(self.cfg, p, f"Ep {day}", "d",
                                  Path("feed-t.xml"), now=when)


class TestFeed(InTmpDir):
    def test_retention_and_tags(self):
        self.add("2026-11-14")
        self.add("2026-11-15")
        count, removed = self.add("2026-11-16")
        self.assertEqual((count, removed), (2, 1))
        self.assertFalse(Path("audio/t/t-2026-11-14.mp3").exists())
        self.assertTrue(Path("audio/autre/autre-1.mp3").exists())  # autre domaine

        root = ET.parse("feed-t.xml").getroot()
        items = root.findall("channel/item")
        self.assertEqual([i.findtext("title") for i in items],
                         ["Ep 2026-11-16", "Ep 2026-11-15"])
        it = "{%s}" % update_feed.ITUNES
        self.assertEqual(items[0].findtext(it + "duration"), "10")  # 60000 o / 6000
        self.assertEqual(items[0].find("guid").get("isPermaLink"), "false")
        self.assertEqual(items[0].find("enclosure").get("url"),
                         "https://ex.test/site/audio/t/t-2026-11-16.mp3")
        ch = root.find("channel")
        self.assertEqual(ch.findtext(it + "explicit"), "false")
        self.assertEqual(ch.find("{%s}link" % update_feed.ATOM).get("href"),
                         "https://ex.test/site/feed-t.xml")
        self.assertIsNotNone(ch.find("lastBuildDate"))

    def test_same_day_rerun_no_duplicate(self):
        self.add("2026-11-16")
        count, _ = self.add("2026-11-16")
        self.assertEqual(count, 1)

    def test_corrupted_feed_deletes_nothing(self):
        self.add("2026-11-15")
        Path("feed-t.xml").write_text("<rss><channel>", encoding="utf-8")
        with self.assertRaises(update_feed.FeedError):
            self.add("2026-11-16")
        self.assertTrue(Path("audio/t/t-2026-11-15.mp3").exists())
        self.assertTrue(Path("audio/t/t-2026-11-16.mp3").exists())
        self.assertEqual(Path("feed-t.xml").read_text(encoding="utf-8"),
                         "<rss><channel>")

    def test_audio_outside_domain_dir_refused(self):
        with self.assertRaises(update_feed.FeedError):
            update_feed.update(self.cfg, Path("audio/autre/autre-1.mp3"), "t",
                               "d", Path("feed-t.xml"))


class TestWindowAndSeen(InTmpDir):
    def test_adaptive_lookback(self):
        now = dt.datetime(2026, 11, 16, 6, tzinfo=dt.timezone.utc)
        self.assertEqual(fetch_news.effective_lookback(self.cfg, now), 30)  # pas de flux
        self.add("2026-11-15", when=now - dt.timedelta(hours=24))
        self.assertEqual(fetch_news.effective_lookback(self.cfg, now), 30)
        self.add("2026-11-15", when=now - dt.timedelta(hours=70))
        self.assertEqual(fetch_news.effective_lookback(self.cfg, now), 72)
        self.add("2026-11-15", when=now - dt.timedelta(days=10))
        self.assertEqual(fetch_news.effective_lookback(self.cfg, now), 96)  # plafond

    def test_seen_memory(self):
        item = {"title": "Un Titre !", "link": "https://ex.test/a"}
        d = dt.date(2026, 11, 15)
        fetch_news.mark_seen(self.cfg, [item], d)
        seen = fetch_news.load_seen(fetch_news.seen_path(self.cfg), d)
        self.assertEqual(seen, {"l:https://ex.test/a": "2026-11-15",
                                "t:un titre": "2026-11-15"})
        # purge au-dela de SEEN_KEEP_DAYS
        later = d + dt.timedelta(days=fetch_news.SEEN_KEEP_DAYS + 1)
        self.assertEqual(fetch_news.load_seen(fetch_news.seen_path(self.cfg), later), {})


if __name__ == "__main__":
    unittest.main()
