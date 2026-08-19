"""Parancssori futtatás webfelület nélkül.

Példa:
  python cli.py --bolt rossmann --marka head-shoulders pantene
  python cli.py --bolt dm rossmann --mind --kimenet C:\\arak
"""
from __future__ import annotations

import argparse
import os
import sys

from pgscraper.brands import BRANDS, get_brands
from pgscraper.runner import Job, run_job


def main() -> int:
    ap = argparse.ArgumentParser(description="P&G ár-scraper (dm.hu / Rossmann)")
    ap.add_argument("--bolt", nargs="+", default=["rossmann"], choices=["dm", "rossmann"])
    ap.add_argument("--marka", nargs="*", default=[], help="márka kulcsok, pl. head-shoulders gillette")
    ap.add_argument("--mind", action="store_true", help="az összes ismert P&G márka")
    ap.add_argument("--gyors", action="store_true", help="termékoldalak nélkül (nincs EAN)")
    ap.add_argument("--szalak", type=int, default=5)
    ap.add_argument("--keses", type=float, default=0.35)
    ap.add_argument("--max-markankent", type=int, default=0)
    ap.add_argument("--dm-mod", default="auto", choices=["auto", "api", "browser", "static"])
    ap.add_argument("--kimenet", default="kimenet")
    ap.add_argument("--lista", action="store_true", help="márkakulcsok kiírása és kilépés")
    args = ap.parse_args()

    if args.lista:
        for b in BRANDS:
            print("{:<18} {:<22} {}".format(b.key, b.display, b.group))
        return 0

    keys = [b.key for b in BRANDS] if args.mind else args.marka
    if not keys:
        keys = [b.key for b in get_brands(None)]

    job = Job({
        "stores": args.bolt, "brands": keys, "with_details": not args.gyors,
        "workers": args.szalak, "delay": args.keses,
        "max_per_brand": args.max_markankent, "dm_mode": args.dm_mod,
        "out_dir": args.kimenet,
    })
    run_job(job)
    if job.excel_path:
        print("\nKész: {}".format(os.path.abspath(job.excel_path)))
        return 0
    print("\nNem készült Excel (nincs adat).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
