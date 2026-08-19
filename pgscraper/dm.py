"""dm Magyarország (www.dm.hu) scraper.

A dm.hu egyoldalas (JavaScript) alkalmazás, ezért a nyers HTML nem tartalmazza
az árakat. A scraper három lépcsőben próbálkozik – automatikusan azt választja,
amelyik működik:

  1. STATIKUS  – hátha a szerver mégis rendereli az adatokat (leggyorsabb).
  2. API-FELDERÍTÉS – egy fejléc nélküli böngésző (Playwright) megnyit 1-2
     termékoldalt, közben elkapja a háttérben lefutó JSON kéréseket. Ha talál
     egy termékadatokat visszaadó végpontot, abból *sablont* készít, és a többi
     terméket már sima HTTP-vel, gyorsan lekéri. Így akkor is működik, ha a dm
     megváltoztatja az API címét – a program futás közben tanulja meg.
  3. BÖNGÉSZŐS – minden termékoldalt megnyit és a kirenderelt DOM-ból olvas
     (lassú, de mindig működik).

A termék-URL-eket a robots.txt által engedélyezett termék-sitemapből gyűjti.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .brands import Brand, match_brand
from .extract import extract_product, product_from_dict
from .http import Http, parallel_map
from .models import Product
from .parsing import (
    clean_text,
    gtin_is_valid,
    looks_like_product,
    normalize,
    parse_size,
    walk_json,
)

BASE = "https://www.dm.hu"
SITEMAP_INDEX = BASE + "/sitemap.xml"
FALLBACK_PRODUCT_SITEMAP = BASE + "/product-sitemap.xml"
STORE = "dm"

_DAN_RE = re.compile(r"/p/d/(\d+)/")

# Süti-sáv: elsősorban az elutasító / csak-szükséges gombot keressük
REJECT_SELECTORS = [
    "button:has-text('Csak a szükséges')",
    "button:has-text('Csak szükséges')",
    "button:has-text('Elutasítom')",
    "button:has-text('Elutasít')",
    "button:has-text('Nem fogadom el')",
    "button:has-text('Ablak bezárása')",
    "[data-dmid='cookie-banner-decline']",
    "#onetrust-reject-all-handler",
    "button[aria-label*='elutas' i]",
]


class DmScraper:
    def __init__(self, http: Optional[Http] = None, log: Optional[Callable[[str], None]] = None,
                 mode: str = "auto", headless: bool = True):
        self.http = http or Http(min_interval=0.25)
        self.log = log or (lambda msg: None)
        self.mode = mode          # auto | static | api | browser
        self.headless = headless
        self._sitemap_urls: Optional[List[str]] = None
        self.api_template: Optional[str] = None
        self.api_headers: Dict[str, str] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ sitemap
    def sitemap_urls(self) -> List[str]:
        if self._sitemap_urls is not None:
            return self._sitemap_urls
        urls: List[str] = []
        maps: List[str] = []
        try:
            index = self.http.get_text(SITEMAP_INDEX)
            maps = [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", index) if "product" in u.lower()]
        except Exception as exc:  # noqa: BLE001
            self.log("  ! dm sitemap index hiba: {}".format(exc))
        if not maps:
            maps = [FALLBACK_PRODUCT_SITEMAP]
        for sm in maps:
            try:
                body = self.http.get_text(sm)
            except Exception as exc:  # noqa: BLE001
                self.log("  ! dm sitemap hiba ({}): {}".format(sm, exc))
                continue
            urls.extend(u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body) if "/p/" in u)
        self._sitemap_urls = sorted(set(urls))
        self.log("  dm sitemap: {} termék-URL".format(len(self._sitemap_urls)))
        return self._sitemap_urls

    @staticmethod
    def dan_of(url: str) -> Optional[str]:
        m = _DAN_RE.search(url)
        return m.group(1) if m else None

    # -------------------------------------------------------- 1. statikus
    def try_static(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            html = self.http.get_text(url)
        except Exception:  # noqa: BLE001
            return None
        data = extract_product(html, url)
        if data.get("name") and data.get("price"):
            return data
        return None

    # ------------------------------------------------ 2. API-felderítés
    def discover_api(self, sample_urls: List[str]) -> bool:
        """Playwright-tal megnyit pár oldalt és megkeresi a termék-JSON végpontot."""
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            self.log("  ! A Playwright nincs telepítve – dm API-felderítés kihagyva.")
            return False

        captured: List[Tuple[str, Dict[str, str], Any]] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            ctx = browser.new_context(locale="hu-HU", user_agent=self.http.session.headers.get("User-Agent"))
            page = ctx.new_page()

            def on_response(resp):
                try:
                    ctype = (resp.headers or {}).get("content-type", "")
                    if "json" not in ctype.lower():
                        return
                    if resp.request.resource_type not in ("xhr", "fetch"):
                        return
                    body = resp.json()
                except Exception:  # noqa: BLE001
                    return
                captured.append((resp.url, dict(resp.request.headers or {}), body))

            page.on("response", on_response)

            for url in sample_urls[:2]:
                dan = self.dan_of(url) or ""
                captured.clear()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    self._dismiss_cookies(page)
                    page.wait_for_timeout(3500)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:  # noqa: BLE001
                        pass
                except Exception as exc:  # noqa: BLE001
                    self.log("  ! dm oldal betöltési hiba: {}".format(exc))
                    continue

                for req_url, headers, body in captured:
                    rec = self._product_from_payload(body, dan)
                    if not rec:
                        continue
                    template = self._templatize(req_url, dan, rec.get("ean"))
                    if not template:
                        continue
                    with self._lock:
                        self.api_template = template
                        self.api_headers = {
                            k: v for k, v in headers.items()
                            if k.lower() in ("accept", "accept-language", "user-agent", "origin", "referer")
                        }
                    self.log("  dm API megtalálva: {}".format(template))
                    browser.close()
                    return True
            browser.close()
        self.log("  ! dm API-t nem sikerült felderíteni – böngészős módra váltok.")
        return False

    def _dismiss_cookies(self, page) -> None:
        for sel in REJECT_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click(timeout=2500)
                    page.wait_for_timeout(600)
                    return
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _templatize(url: str, dan: str, ean: Optional[str]) -> Optional[str]:
        t = url
        if dan and dan in t:
            t = t.replace(dan, "{dan}")
        elif ean and ean in t:
            t = t.replace(ean, "{gtin}")
        else:
            return None
        return t

    def _product_from_payload(self, body: Any, dan: str = "") -> Optional[Dict[str, Any]]:
        best: Optional[Dict[str, Any]] = None
        best_score = 0
        for _, node in walk_json(body):
            if not looks_like_product(node):
                continue
            rec = product_from_dict(node)
            if not rec.get("name"):
                continue
            score = 1 + (2 if rec.get("price") else 0) + (2 if rec.get("ean") else 0)
            if dan and (rec.get("sku") == dan or dan in json.dumps(node, default=str)[:4000]):
                score += 3
            if score > best_score:
                best, best_score = rec, score
        return best

    def fetch_via_api(self, url: str) -> Optional[Dict[str, Any]]:
        if not self.api_template:
            return None
        dan = self.dan_of(url) or ""
        api_url = self.api_template.replace("{dan}", dan)
        if "{gtin}" in api_url:
            return None
        try:
            body = self.http.get_json(api_url, headers=self.api_headers or None)
        except Exception:  # noqa: BLE001
            return None
        rec = self._product_from_payload(body, dan)
        if rec:
            rec["strategy"] = "dm-api"
        return rec

    # --------------------------------------------------------- 3. böngésző
    def fetch_via_browser(self, urls: List[str], progress: Optional[Callable[[int, int, str], None]] = None,
                          should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            self.log("  ! Playwright hiányzik – a dm adatok nem tölthetők le. "
                     "Telepítés: pip install playwright && python -m playwright install chromium")
            return out

        total = len(urls)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            ctx = browser.new_context(locale="hu-HU", user_agent=self.http.session.headers.get("User-Agent"))
            ctx.route("**/*.{png,jpg,jpeg,webp,gif,svg,woff,woff2,mp4}", lambda route: route.abort())
            page = ctx.new_page()
            first = True
            for i, url in enumerate(urls, 1):
                if should_stop and should_stop():
                    break
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=40000)
                    if first:
                        self._dismiss_cookies(page)
                        first = False
                    page.wait_for_timeout(1500)
                    html = page.content()
                    data = extract_product(html, url)
                    if data.get("name"):
                        data["strategy"] = "dm-böngésző+" + str(data.get("strategy", ""))
                        out[url] = data
                except Exception as exc:  # noqa: BLE001
                    self.log("  ! {} -> {}".format(url, exc))
                if progress:
                    progress(i, total, STORE)
            browser.close()
        return out

    # --------------------------------------------------------------- futás
    def scrape(
        self,
        brands: List[Brand],
        *,
        workers: int = 5,
        max_per_brand: int = 0,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> List[Product]:
        sitemap = self.sitemap_urls()
        targets: List[Tuple[str, Brand]] = []
        seen = set()
        for brand in brands:
            urls = [u for u in sitemap if brand.matches_url(u)]
            if max_per_brand:
                urls = urls[:max_per_brand]
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    targets.append((u, brand))
            self.log("  {}: {} termék a dm sitemapből".format(brand.display, len(urls)))

        if not targets:
            self.log("  ! dm: egy termék sem illeszkedett a kiválasztott márkákra.")
            return []

        sample = [u for u, _ in targets[:2]]
        raw: Dict[str, Dict[str, Any]] = {}

        # 1) statikus próba
        if self.mode in ("auto", "static"):
            probe = self.try_static(sample[0])
            if probe:
                self.log("  dm: statikus HTML is tartalmazza az adatokat – böngésző nem kell.")
                raw[sample[0]] = probe
                rest = [u for u, _ in targets if u != sample[0]]
                done = {"n": 1}
                total = len(targets)

                def work_static(u: str):
                    d = self.try_static(u)
                    done["n"] += 1
                    if progress:
                        progress(done["n"], total, STORE)
                    return (u, d) if d else None

                for item in parallel_map(work_static, rest, workers=workers, should_stop=should_stop):
                    if item:
                        raw[item[0]] = item[1]
                return self._build(raw, targets, brands)
            elif self.mode == "static":
                self.log("  ! dm: statikus módban nem található adat.")
                return []

        # 2) API-felderítés
        if self.mode in ("auto", "api"):
            if self.api_template or self.discover_api(sample):
                total = len(targets)
                done = {"n": 0}

                def work_api(item):
                    u, _b = item
                    d = self.fetch_via_api(u)
                    done["n"] += 1
                    if progress:
                        progress(done["n"], total, STORE)
                    return (u, d) if d else None

                for item in parallel_map(work_api, targets, workers=workers, should_stop=should_stop):
                    if item:
                        raw[item[0]] = item[1]
                ok = len(raw)
                self.log("  dm API: {}/{} termék sikeres.".format(ok, len(targets)))
                if ok >= max(1, int(0.5 * len(targets))):
                    return self._build(raw, targets, brands)
                self.log("  dm: az API kevés adatot adott – böngészős módra váltok.")

        # 3) böngészős tartalék
        missing = [u for u, _ in targets if u not in raw]
        raw.update(self.fetch_via_browser(missing, progress=progress, should_stop=should_stop))
        return self._build(raw, targets, brands)

    def _build(self, raw: Dict[str, Dict[str, Any]], targets: List[Tuple[str, Brand]],
               brands: List[Brand]) -> List[Product]:
        by_url = {u: b for u, b in targets}
        out: List[Product] = []
        for url, data in raw.items():
            name = clean_text(str(data.get("name") or ""))
            if not name:
                continue
            brand = match_brand(name, brands) or by_url.get(url)
            if brand is None:
                continue
            size_source = str(data.get("size_text") or "") or name
            value, unit, pack, label = parse_size(size_source)
            if not label:
                value, unit, pack, label = parse_size(name)
            ean = str(data.get("ean") or "") or None
            if ean and not gtin_is_valid(ean):
                ean = None
            price = data.get("price")
            out.append(Product(
                store=STORE,
                brand=brand.display,
                brand_group=brand.group,
                name=name,
                size_value=value, size_unit=unit, pack_count=pack, size_label=label,
                variant_group="{} {}".format(brand.display, label).strip(),
                price=float(price) if isinstance(price, (int, float)) else None,
                unit_price=str(data.get("unit_price") or "") or None,
                old_price=float(data["old_price"]) if isinstance(data.get("old_price"), (int, float)) else None,
                ean=ean,
                sku=str(data.get("sku") or "") or self.dan_of(url),
                availability=str(data.get("availability") or "") or None,
                url=url,
                extraction=str(data.get("strategy") or ""),
            ))
        return out
