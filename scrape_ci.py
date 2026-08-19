# -*- coding: utf-8 -*-
"""GitHub Actions belépési pont: lefuttatja a scrape-et és kiírja a docs/data
mappába azokat a fájlokat, amelyeket a GitHub Pages-en futó nézegető oldal olvas.

Kimenetek:
  docs/data/latest.json            – a legfrissebb futás összes terméke + meta
  docs/data/history.csv            – napi idősor (minden futás hozzáfűződik)
  docs/data/PG_arak_latest.xlsx    – mindig a legfrissebb Excel (nem nő a repó)
  docs/data/runs/PG_arak_<dátum>.xlsx – dátumozott mentés (régiek automatikusan törlődnek)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pgscraper.brands import BRANDS, get_brands  # noqa: E402
from pgscraper.export import export_excel  # noqa: E402
from pgscraper.models import Product  # noqa: E402
from pgscraper.runner import Job, run_job  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Budapest")
except Exception:  # noqa: BLE001
    TZ = None

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "docs", "data")
RUNS_DIR = os.path.join(DATA_DIR, "runs")
TMP_DIR = os.path.join(ROOT, ".tmp_run")   # a runner ide írja a saját időbélyeges fájlját
HISTORY = os.path.join(DATA_DIR, "history.csv")
LATEST_JSON = os.path.join(DATA_DIR, "latest.json")
LATEST_XLSX = os.path.join(DATA_DIR, "PG_arak_latest.xlsx")

HISTORY_FIELDS = ["date", "store", "brand", "brand_group", "name", "size_label",
                  "size_value", "size_unit", "ean", "price", "unit_price", "url"]
HISTORY_KEEP_DAYS = 400
RUNS_KEEP = 30


def now() -> datetime:
    return datetime.now(TZ) if TZ else datetime.now()


def key_of(p: Product) -> str:
    return "{}|{}".format(p.store, p.ean or p.url)


def read_previous_prices() -> Dict[str, Tuple[str, float]]:
    """kulcs -> (dátum, ár) a legutóbbi *korábbi* napról."""
    out: Dict[str, Tuple[str, float]] = {}
    if not os.path.exists(HISTORY):
        return out
    today = now().strftime("%Y-%m-%d")
    with open(HISTORY, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            date = (row.get("date") or "").strip()
            if not date or date == today:
                continue
            try:
                price = float(row.get("price") or "")
            except ValueError:
                continue
            key = "{}|{}".format(row.get("store", ""), row.get("ean") or row.get("url") or "")
            prev = out.get(key)
            if prev is None or date > prev[0]:
                out[key] = (date, price)
    return out


def append_history(products: List[Product], date: str) -> None:
    rows: List[Dict[str, object]] = []
    if os.path.exists(HISTORY):
        with open(HISTORY, "r", encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if (r.get("date") or "") != date]
    cutoff = (now() - timedelta(days=HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    rows = [r for r in rows if (r.get("date") or "") >= cutoff]

    for p in products:
        rows.append({
            "date": date, "store": p.store, "brand": p.brand, "brand_group": p.brand_group,
            "name": p.name, "size_label": p.size_label,
            "size_value": p.size_value if p.size_value is not None else "",
            "size_unit": p.size_unit or "", "ean": p.ean or "",
            "price": p.price if p.price is not None else "",
            "unit_price": p.unit_price or "", "url": p.url,
        })

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prune_runs() -> None:
    if not os.path.isdir(RUNS_DIR):
        return
    files = sorted(f for f in os.listdir(RUNS_DIR) if f.endswith(".xlsx"))
    for stale in files[:-RUNS_KEEP]:
        try:
            os.remove(os.path.join(RUNS_DIR, stale))
        except OSError:
            pass


def write_latest(products: List[Product], job: Job, date: str) -> None:
    prev = read_previous_prices()
    payload_products = []
    for p in products:
        row = p.to_dict()
        old = prev.get(key_of(p))
        if old and p.price is not None:
            row["prev_price"] = old[1]
            row["prev_date"] = old[0]
            row["change"] = round(p.price - old[1], 1)
            row["change_pct"] = round(100.0 * (p.price - old[1]) / old[1], 2) if old[1] else None
        else:
            row["prev_price"] = None
            row["prev_date"] = None
            row["change"] = None
            row["change_pct"] = None
        payload_products.append(row)

    changed = [r for r in payload_products if r.get("change")]
    payload = {
        "generated_at": now().isoformat(timespec="seconds"),
        "generated_date": date,
        "stores": job.options.get("stores", []),
        "brands": sorted({p.brand for p in products}),
        "counts": {
            "total": len(products),
            "with_price": sum(1 for p in products if p.price is not None),
            "with_ean": sum(1 for p in products if p.ean),
            "changed": len(changed),
        },
        "warnings": job.stats.warnings,
        "errors": job.stats.errors,
        "products": payload_products,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LATEST_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bolt", nargs="+", default=["rossmann", "dm"], choices=["dm", "rossmann"])
    ap.add_argument("--marka", nargs="*", default=[], help="üresen hagyva: minden márka")
    ap.add_argument("--szalak", type=int, default=3)
    ap.add_argument("--keses", type=float, default=0.8)
    ap.add_argument("--max-markankent", type=int, default=0)
    ap.add_argument("--gyors", action="store_true")
    args = ap.parse_args()

    keys = args.marka or [b.key for b in BRANDS]
    brands = get_brands(keys)
    date = now().strftime("%Y-%m-%d")

    job = Job({
        "stores": args.bolt,
        "brands": [b.key for b in brands],
        "with_details": not args.gyors,
        "workers": args.szalak,
        "delay": args.keses,
        "max_per_brand": args.max_markankent,
        "dm_mode": "auto",
        "out_dir": TMP_DIR,
    })
    run_job(job)

    products = job.products
    print("\n=== {} termék, ebből {} árral, {} EAN-nal ===".format(
        len(products),
        sum(1 for p in products if p.price is not None),
        sum(1 for p in products if p.ean)))

    if not products:
        print("HIBA: egyetlen termék sem jött vissza – a korábbi adatokat nem írom felül.")
        return 1

    os.makedirs(RUNS_DIR, exist_ok=True)
    write_latest(products, job, date)
    append_history(products, date)
    export_excel(products, job.stats, LATEST_XLSX)
    export_excel(products, job.stats, os.path.join(RUNS_DIR, "PG_arak_{}.xlsx".format(date)))
    prune_runs()

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## P&G ár-scrape – {}\n\n".format(date))
            fh.write("| mutató | érték |\n|---|---|\n")
            fh.write("| termék | {} |\n".format(len(products)))
            fh.write("| árral | {} |\n".format(sum(1 for p in products if p.price is not None)))
            fh.write("| EAN-nal | {} |\n".format(sum(1 for p in products if p.ean)))
            for store in job.options["stores"]:
                n = sum(1 for p in products if p.store.lower().startswith(store[:4].lower()))
                fh.write("| {} | {} |\n".format(store, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
