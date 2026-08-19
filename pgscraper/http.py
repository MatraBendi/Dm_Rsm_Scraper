"""Udvarias HTTP réteg: retry, rate-limit, párhuzamosítás."""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Iterable, List, Optional, Tuple, TypeVar

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

T = TypeVar("T")


class RateLimiter:
    """Egyszerű, szálbiztos minimum-késleltetés két kérés között."""

    def __init__(self, min_interval: float = 0.35):
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                sleep_for = self._next_at - now
            else:
                sleep_for = 0.0
            self._next_at = max(now, self._next_at) + self.min_interval
        if sleep_for > 0:
            time.sleep(sleep_for + random.uniform(0, 0.08))


class Http:
    def __init__(self, min_interval: float = 0.35, timeout: int = 25, headers: Optional[Dict[str, str]] = None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_UA,
            "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.6",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if headers:
            self.session.headers.update(headers)
        self.limiter = RateLimiter(min_interval)
        self.timeout = timeout

    def get(self, url: str, *, retries: int = 3, **kwargs) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            self.limiter.wait()
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                if resp.status_code in (429, 503):
                    time.sleep(2.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.8 * (attempt + 1))
        raise RuntimeError("Sikertelen letöltés: {} ({})".format(url, last_exc))

    def get_text(self, url: str, **kwargs) -> str:
        resp = self.get(url, **kwargs)
        resp.encoding = resp.encoding or "utf-8"
        return resp.text

    def get_json(self, url: str, **kwargs):
        return self.get(url, **kwargs).json()

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass


def parallel_map(
    func: Callable[[T], object],
    items: Iterable[T],
    workers: int = 5,
    on_result: Optional[Callable[[object], None]] = None,
    on_error: Optional[Callable[[T, Exception], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> List[object]:
    items = list(items)
    results: List[object] = []
    if not items:
        return results
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(func, it): it for it in items}
        for fut in as_completed(futures):
            if should_stop and should_stop():
                for f in futures:
                    f.cancel()
                break
            item = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001
                if on_error:
                    on_error(item, exc)
                continue
            if res is not None:
                results.append(res)
            if on_result:
                on_result(res)
    return results
