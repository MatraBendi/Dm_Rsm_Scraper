"""Rossmann Magyarország (shop.rossmann.hu) scraper.

A Rossmann webshopja szerveroldalon rendereli a termékeket, ezért sima
HTTP + HTML feldolgozás elég – nincs szükség böngészőre.

Két forrásból gyűjti a termék-URL-eket:
  1. márkaoldalak  https://shop.rossmann.hu/markak/<slug>
  2. termék-sitemap https://shop.rossmann.hu/sitemaps/sitemap-products.xml
A kettő uniója adja a teljes listát; a részletadatokat (ár, EAN, kiszerelés)
a termékoldalak adják.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from .brands import Brand, match_brand
from .extract import extract_product, soup_of
from .http import Http, parallel_map
from .models import Product
from .parsing import clean_text, normalize, parse_price_hu, parse_size

BASE = "https://shop.rossmann.hu"
SITEMAP_INDEX = BASE + "/sitemap.xml"
STORE = "Rossmann"

_PRODUCT_PATH = re.compile(r"^/termek/[^/?#]+/?$")


class RossmannScraper:
    def __init__(self, http: Optional[Http] = None, log: Optional[Callable[[str], None]] = None):
        self.http = http or Http(min_interval=0.3)
        self.log = log or (lambda msg: None)
        self._sitemap_urls: Optional[List[str]] = None

    # ------------------------------------------------------------ sitemap
    def sitemap_urls(self) -> List[str]:
        if self._sitemap_urls is not None:
            return self._sitemap_urls
        urls: List[str] = []
        try:
            index = self.http.get_text(SITEMAP_INDEX)
            sub = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", index)
            product_maps = [u for u in sub if "product" in u.lower()] or sub
            for sm in product_maps:
                try:
                    body = self.http.get_text(sm)
                except Exception as exc:  # noqa: BLE001
                    self.log("  ! sitemap hiba ({}): {}".format(sm, exc))
                    continue
                found = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
                urls.extend(u for u in found if "/termek/" in u)
            self.log("  Rossmann sitemap: {} termék-URL".format(len(urls)))
        except Exception as exc:  # noqa: BLE001
            self.log("  ! Rossmann sitemap nem elérhető: {}".format(exc))
        self._sitemap_urls = sorted(set(urls))
        return self._sitemap_urls

    # -------------------------------------------------------- márkaoldalak
    def brand_page_products(self, brand: Brand, max_pages: int = 12) -> Dict[str, Dict[str, object]]:
        """URL -> {name, price} a márkaoldalról (gyors, EAN nélkül)."""
        slug = brand.rossmann_slug or brand.key
        found: Dict[str, Dict[str, object]] = {}
        seen_signature: Set[str] = set()

        for page in range(1, max_pages + 1):
            url = "{}/markak/{}".format(BASE, slug)
            if page > 1:
                url += "?page={}".format(page)
            try:
                html = self.http.get_text(url)
            except Exception as exc:  # noqa: BLE001
                if page == 1:
                    self.log("  ! {} márkaoldal nem érhető el: {}".format(brand.display, exc))
                break

            page_items = self._parse_listing(html, url)
            if not page_items:
                break
            signature = "|".join(sorted(page_items))
            if signature in seen_signature:
                break  # ugyanaz az oldal jött vissza -> nincs lapozás
            seen_signature.add(signature)
            new = 0
            for u, data in page_items.items():
                if u not in found:
                    found[u] = data
                    new += 1
            if new == 0:
                break
        return found

    def _parse_listing(self, html: str, page_url: str) -> Dict[str, Dict[str, object]]:
        soup = soup_of(html)
        out: Dict[str, Dict[str, object]] = {}
        for a in soup.find_all("a", href=True):
            href = a["href"].split("?")[0]
            path = urlparse(href).path or href
            if not _PRODUCT_PATH.match(path):
                continue
            full = urljoin(BASE, path)
            name = clean_text(a.get("title") or a.get_text(" "))
            price = None
            card = a
            for _ in range(4):
                card = card.parent if card.parent is not None else card
                text = clean_text(card.get_text(" "))
                if "Ft" in text:
                    if not name or len(name) < 8:
                        heading = card.find(["h2", "h3", "h4"])
                        if heading:
                            name = clean_text(heading.get_text(" "))
                    for chunk in re.findall(r"[^|]{0,40}?\d[\d\s.,]*\s*Ft(?!\s*/)", text):
                        price = parse_price_hu(chunk)
                        if price:
                            break
                    break
            prev = out.get(full, {})
            out[full] = {
                "name": name or prev.get("name", ""),
                "price": price if price is not None else prev.get("price"),
            }
        return out

    # ------------------------------------------------------------- részletek
    def fetch_detail(self, url: str, brands: List[Brand]) -> Optional[Product]:
        html = self.http.get_text(url)
        data = extract_product(html, url)
        return self._to_product(data, url, brands)

    def _to_product(self, data: Dict[str, object], url: str, brands: List[Brand]) -> Optional[Product]:
        name = clean_text(str(data.get("name") or ""))
        if not name:
            return None
        brand = match_brand(name, brands) or match_brand(str(data.get("brand_raw") or ""), brands)
        if brand is None:
            brand = match_brand(url.replace("-", " "), brands)
        if brand is None:
            return None

        size_source = str(data.get("size_text") or "") or name
        value, unit, pack, label = parse_size(size_source)
        if not label:
            value, unit, pack, label = parse_size(name)

        price = data.get("price")
        return Product(
            store=STORE,
            brand=brand.display,
            brand_group=brand.group,
            name=name,
            size_value=value,
            size_unit=unit,
            pack_count=pack,
            size_label=label,
            variant_group="{} {}".format(brand.display, label).strip(),
            price=float(price) if isinstance(price, (int, float)) else None,
            unit_price=str(data.get("unit_price") or "") or None,
            old_price=float(data["old_price"]) if isinstance(data.get("old_price"), (int, float)) else None,
            ean=str(data.get("ean") or "") or None,
            sku=str(data.get("sku") or "") or None,
            availability=str(data.get("availability") or "") or None,
            url=url,
            extraction=str(data.get("strategy") or ""),
        )

    # ------------------------------------------------------------------ futás
    def scrape(
        self,
        brands: List[Brand],
        *,
        with_details: bool = True,
        workers: int = 5,
        max_per_brand: int = 0,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> List[Product]:
        self.log("Rossmann: {} márka gyűjtése...".format(len(brands)))
        sitemap = self.sitemap_urls()

        targets: List[tuple] = []          # (url, brand, listing_name, listing_price)
        seen: Set[str] = set()
        for brand in brands:
            if should_stop and should_stop():
                break
            listing = self.brand_page_products(brand)
            from_sitemap = [u for u in sitemap if brand.matches_url(u)]
            urls = list(listing.keys()) + [u for u in from_sitemap if u not in listing]
            if max_per_brand:
                urls = urls[:max_per_brand]
            for u in urls:
                if u in seen:
                    continue
                seen.add(u)
                info = listing.get(u, {})
                targets.append((u, brand, info.get("name", ""), info.get("price")))
            self.log("  {}: {} termék (márkaoldal {} + sitemap {})".format(
                brand.display, len(urls), len(listing), len(from_sitemap)))

        if not with_details:
            out: List[Product] = []
            for url, brand, name, price in targets:
                if not name:
                    continue
                value, unit, pack, label = parse_size(name)
                out.append(Product(
                    store=STORE, brand=brand.display, brand_group=brand.group, name=name,
                    size_value=value, size_unit=unit, pack_count=pack, size_label=label,
                    variant_group="{} {}".format(brand.display, label).strip(),
                    price=float(price) if isinstance(price, (int, float)) else None,
                    url=url, extraction="listaoldal",
                ))
            return out

        total = len(targets)
        self.log("Rossmann: {} termékoldal letöltése ({} szálon)...".format(total, workers))
        done = {"n": 0}
        results: List[Product] = []

        def work(item):
            url, brand, listing_name, listing_price = item
            try:
                prod = self.fetch_detail(url, [brand] + [b for b in brands if b is not brand])
            except Exception as exc:  # noqa: BLE001
                self.log("  ! {} -> {}".format(url, exc))
                prod = None
            if prod is None and listing_name:
                value, unit, pack, label = parse_size(listing_name)
                prod = Product(
                    store=STORE, brand=brand.display, brand_group=brand.group, name=listing_name,
                    size_value=value, size_unit=unit, pack_count=pack, size_label=label,
                    variant_group="{} {}".format(brand.display, label).strip(),
                    price=float(listing_price) if isinstance(listing_price, (int, float)) else None,
                    url=url, extraction="listaoldal(fallback)",
                )
            if prod is not None and prod.price is None and isinstance(listing_price, (int, float)):
                prod.price = float(listing_price)
                prod.extraction += "+listaár"
            done["n"] += 1
            if progress:
                progress(done["n"], total, STORE)
            return prod

        results = [p for p in parallel_map(work, targets, workers=workers, should_stop=should_stop)
                   if isinstance(p, Product)]
        return results
