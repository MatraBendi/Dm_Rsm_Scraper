# -*- coding: utf-8 -*-
"""Egységtesztek a feldolgozó logikára (nem igényel internetet)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgscraper.brands import BRANDS, match_brand, get_brands  # noqa: E402
from pgscraper.extract import extract_product, read_spec_pairs, soup_of  # noqa: E402
from pgscraper.parsing import (  # noqa: E402
    find_ean, gtin_is_valid, normalize, parse_price_hu, parse_size,
)


class TestPrice(unittest.TestCase):
    def test_formats(self):
        cases = {
            "2 354 Ft": 2354.0,
            "2 354 Ft": 2354.0,
            "2.354 Ft": 2354.0,
            "2,354 Ft": 2354.0,
            "1 995,50 Ft": 1995.5,
            "1995 Ft": 1995.0,
            "12 999 Ft": 12999.0,
            "Akciós ár: 4 010 Ft": 4010.0,
            "999 Ft": 999.0,
        }
        for text, expected in cases.items():
            self.assertAlmostEqual(parse_price_hu(text), expected, msg=text)

    def test_none(self):
        self.assertIsNone(parse_price_hu(""))
        self.assertIsNone(parse_price_hu(None))

    def test_plain_number(self):
        self.assertEqual(parse_price_hu("2354"), 2354.0)
        self.assertEqual(parse_price_hu(2354), 2354.0)


class TestSize(unittest.TestCase):
    def test_from_names(self):
        cases = [
            ("Head & Shoulders Apple Fresh sampon - 400 ml", (400.0, "ml", None, "400 ml")),
            ("Head & Shoulders Classic Clean 2az1-ben sampon - 625 ml", (625.0, "ml", None, "625 ml")),
            ("Ariel Color mosógél 2,2 l", (2200.0, "ml", None, "2200 ml")),
            ("Gillette Fusion5 borotvabetét 8 db", (8.0, "db", None, "8 db")),
            ("Lenor öblítő 3 x 1,2 l", (1200.0, "ml", 3, "3x1200 ml")),
            ("Blend-a-med fogkrém 100 ml", (100.0, "ml", None, "100 ml")),
            ("Always Ultra Normal betét 20 db", (20.0, "db", None, "20 db")),
            ("Pampers Premium Care 4-es pelenka 52 db", (52.0, "db", None, "52 db")),
            ("Old Spice deo stift 50 g", (50.0, "g", None, "50 g")),
        ]
        for name, expected in cases:
            self.assertEqual(parse_size(name), expected, msg=name)

    def test_prefers_volume_over_count(self):
        # a "2az1" és a "3 db" nem nyomhatja el a valódi kiszerelést
        self.assertEqual(parse_size("H&S 2in1 sampon 3 db-os csomag 400 ml")[0], 400.0)

    def test_empty(self):
        self.assertEqual(parse_size("Valami termék")[3], "")


class TestEan(unittest.TestCase):
    def test_checksum(self):
        self.assertTrue(gtin_is_valid("5410076659456"))   # H&S Apple Fresh 400 ml
        self.assertTrue(gtin_is_valid("4058172680564"))
        self.assertFalse(gtin_is_valid("5410076659457"))
        self.assertFalse(gtin_is_valid("12345"))
        self.assertFalse(gtin_is_valid(""))

    def test_find_in_text(self):
        text = "Cikkszám 5410076659456 Kiszerelés 400 ml Szélesség 44 mm"
        self.assertEqual(find_ean(text), "5410076659456")

    def test_ignores_random_digits(self):
        self.assertIsNone(find_ean("Magasság 211 mm Súly 458 g"))


class TestBrands(unittest.TestCase):
    def test_match(self):
        self.assertEqual(match_brand("Head & Shoulders Apple Fresh sampon 400 ml").key, "head-shoulders")
        self.assertEqual(match_brand("Oral-B Pro 3 elektromos fogkefe").key, "oral-b")
        self.assertEqual(match_brand("Blend-a-med Complete fogkrém").key, "blend-a-med")
        self.assertEqual(match_brand("Gillette Venus Smooth borotva").key, "venus")
        self.assertIsNone(match_brand("Nivea Men tusfürdő"))

    def test_url_match(self):
        b = {x.key: x for x in BRANDS}
        self.assertTrue(b["head-shoulders"].matches_url(
            "https://shop.rossmann.hu/termek/head-shoulders-apple-fresh-sampon-400-ml"))
        self.assertTrue(b["oral-b"].matches_url("https://www.dm.hu/p/d/123/oral-b-fogkefe"))
        self.assertFalse(b["ariel"].matches_url("https://shop.rossmann.hu/termek/nivea-krem"))

    def test_defaults(self):
        self.assertGreaterEqual(len(get_brands(None)), 15)


ROSSMANN_HTML = u"""
<html><head>
<meta property="og:title" content="Head &amp; Shoulders Apple Fresh Korpásodás Elleni sampon - 400 ml">
</head><body>
<h1>Head &amp; Shoulders Apple Fresh Korpásodás Elleni sampon - 400 ml</h1>
<div class="product-price"><span class="price">2 354 Ft</span></div>
<div class="unit-price">5 885 Ft/l</div>
<div class="availability">Nincs online készleten</div>
<table class="product-params">
  <tr><th>Cikkszám</th><td>5410076659456</td></tr>
  <tr><th>Kiszerelés</th><td>400 ml</td></tr>
  <tr><th>Csomagolási típus</th><td>Palack</td></tr>
  <tr><th>Szélesség</th><td>44 mm</td></tr>
  <tr><th>Magasság</th><td>211 mm</td></tr>
</table>
</body></html>
"""

DM_LIKE_HTML = u"""
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Pantene Pro-V Repair & Protect sampon 400 ml",
 "gtin13":"8001841496559",
 "brand":{"@type":"Brand","name":"Pantene"},
 "offers":{"@type":"Offer","price":"2199","priceCurrency":"HUF",
           "availability":"https://schema.org/InStock"}}
</script></head><body><h1>Pantene Pro-V Repair &amp; Protect sampon</h1>
<span class="price">2 199 Ft</span></body></html>
"""


class TestExtract(unittest.TestCase):
    def test_rossmann_like(self):
        data = extract_product(ROSSMANN_HTML, "https://shop.rossmann.hu/termek/x")
        self.assertIn("Head & Shoulders", data["name"])
        self.assertEqual(data["price"], 2354.0)
        self.assertEqual(data["ean"], "5410076659456")
        self.assertEqual(data.get("size_text"), "400 ml")
        self.assertIn("Ft/l", data.get("unit_price", ""))

    def test_jsonld(self):
        data = extract_product(DM_LIKE_HTML, "https://www.dm.hu/p/d/1/x")
        self.assertEqual(data["ean"], "8001841496559")
        self.assertEqual(data["price"], 2199.0)
        self.assertEqual(data.get("availability"), "InStock")

    def test_spec_pairs(self):
        pairs = read_spec_pairs(soup_of(ROSSMANN_HTML))
        self.assertEqual(pairs.get("cikkszam"), "5410076659456")
        self.assertEqual(pairs.get("kiszereles"), "400 ml")

    def test_no_crash_on_garbage(self):
        data = extract_product("<html><body>semmi</body></html>", "http://x")
        self.assertEqual(data.get("strategy"), "nincs")


class TestNormalize(unittest.TestCase):
    def test(self):
        self.assertEqual(normalize("Head & Shoulders"), "head and shoulders")
        self.assertEqual(normalize("Kiszerelés"), "kiszereles")
        self.assertEqual(normalize("Oral-B"), "oral b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
