"""Futásvezérlő: a kiválasztott boltok és márkák bejárása, Excel export."""
from __future__ import annotations

import threading
import traceback
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .brands import Brand, get_brands
from .dm import DmScraper
from .export import default_filename, export_excel
from .http import Http
from .models import Product, RunStats
from .rossmann import RossmannScraper


class Job:
    """Egy scrape-futás állapota (a webes felület ezt kérdezi le)."""

    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, options: Dict):
        with Job._seq_lock:
            Job._seq += 1
            self.id = "job{}".format(Job._seq)
        self.options = options
        self.status = "pending"          # pending | running | done | error | stopped
        self.log_lines: List[str] = []
        self.products: List[Product] = []
        self.stats = RunStats()
        self.excel_path: Optional[str] = None
        self.progress = {"current": 0, "total": 0, "store": ""}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- naplózás
    def log(self, msg: str) -> None:
        line = "[{}] {}".format(datetime.now().strftime("%H:%M:%S"), msg)
        with self._lock:
            self.log_lines.append(line)
            if len(self.log_lines) > 800:
                del self.log_lines[:200]
        print(line, flush=True)

    def set_progress(self, current: int, total: int, store: str) -> None:
        self.progress = {"current": current, "total": total, "store": store}

    def stop(self) -> None:
        self._stop.set()

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def snapshot(self) -> Dict:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "log": self.log_lines[-120:],
            "count": len(self.products),
            "with_price": sum(1 for p in self.products if p.price is not None),
            "with_ean": sum(1 for p in self.products if p.ean),
            "excel_ready": bool(self.excel_path),
            "stats": self.stats.to_dict(),
        }


def run_job(job: Job) -> None:
    opts = job.options
    job.status = "running"
    stores: List[str] = opts.get("stores") or ["rossmann"]
    brand_keys: List[str] = opts.get("brands") or []
    brands: List[Brand] = get_brands(brand_keys)
    delay = float(opts.get("delay", 0.35))
    workers = int(opts.get("workers", 5))
    max_per_brand = int(opts.get("max_per_brand", 0))
    with_details = bool(opts.get("with_details", True))
    dm_mode = opts.get("dm_mode", "auto")
    out_dir = opts.get("out_dir") or "kimenet"

    job.stats.stores = stores
    job.stats.brands = [b.display for b in brands]
    job.log("Indulás – boltok: {} | márkák: {}".format(", ".join(stores), len(brands)))

    try:
        if "rossmann" in stores and not job.should_stop():
            http = Http(min_interval=delay)
            scraper = RossmannScraper(http=http, log=job.log)
            found = scraper.scrape(
                brands, with_details=with_details, workers=workers,
                max_per_brand=max_per_brand,
                progress=job.set_progress, should_stop=job.should_stop,
            )
            job.products.extend(found)
            job.log("Rossmann kész: {} termék.".format(len(found)))
            http.close()

        if "dm" in stores and not job.should_stop():
            http = Http(min_interval=delay)
            scraper = DmScraper(http=http, log=job.log, mode=dm_mode,
                                headless=not bool(opts.get("show_browser")))
            found = scraper.scrape(
                brands, workers=workers, max_per_brand=max_per_brand,
                progress=job.set_progress, should_stop=job.should_stop,
            )
            job.products.extend(found)
            job.log("dm kész: {} termék.".format(len(found)))
            http.close()

        job.stats.total_found = len(job.products)
        job.stats.with_price = sum(1 for p in job.products if p.price is not None)
        job.stats.with_ean = sum(1 for p in job.products if p.ean)
        job.stats.finished_at = datetime.now().isoformat(timespec="seconds")

        if job.products:
            path = default_filename(stores, out_dir)
            export_excel(job.products, job.stats, path)
            job.excel_path = path
            job.log("Excel elkészült: {}".format(path))
        else:
            job.stats.warnings.append("Nem található termék a megadott szűrőkkel.")
            job.log("Nem található termék.")

        job.status = "stopped" if job.should_stop() else "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.stats.errors.append(str(exc))
        job.log("HIBA: {}".format(exc))
        job.log(traceback.format_exc(limit=3))


def start_job(options: Dict, registry: Dict[str, Job]) -> Job:
    job = Job(options)
    registry[job.id] = job
    thread = threading.Thread(target=run_job, args=(job,), daemon=True)
    thread.start()
    return job
