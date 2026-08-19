"""Hibakereső: egyetlen termékoldal elemzése, a kinyert mezők kiírása.

  python diagnose.py https://shop.rossmann.hu/termek/...
  python diagnose.py https://www.dm.hu/p/d/1234567/... --bongeszo
"""
from __future__ import annotations

import argparse
import json
import sys

from pgscraper.extract import extract_product
from pgscraper.http import Http
from pgscraper.parsing import parse_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--bongeszo", action="store_true", help="Playwright-tal renderelve")
    ap.add_argument("--html", help="a letöltött HTML mentése ide")
    args = ap.parse_args()

    if args.bongeszo:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context(locale="hu-HU").new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
    else:
        html = Http(min_interval=0).get_text(args.url)

    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("HTML mentve: {} ({} karakter)".format(args.html, len(html)))

    data = extract_product(html, args.url)
    specs = data.pop("specs", None)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("\nKiszerelés a névből:", parse_size(data.get("name", "")))
    if specs:
        print("\nSpecifikációs mezők:")
        for k, v in list(specs.items())[:40]:
            print("  {:<28} {}".format(k[:28], v[:70]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
