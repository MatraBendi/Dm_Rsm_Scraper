"""Általános termékadat-kinyerés HTML-ből, több stratégiával.

A stratégiák sorrendben futnak; az első, amelyik nevet ÉS árat ad, nyer.
A hiányzó mezőket (EAN, kiszerelés) a többi stratégia is kiegészítheti.
Ez teszi lehetővé, hogy a scraper akkor is működjön, ha a bolt megváltoztatja
a CSS osztályneveit.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup  # type: ignore

from .parsing import (
    clean_text,
    deep_price,
    find_ean,
    get_first,
    gtin_is_valid,
    json_blocks,
    looks_like_product,
    normalize,
    parse_price_hu,
    parse_size,
    walk_json,
)

# A specifikációs táblákban keresett címkék (ékezet nélkül, kisbetűvel)
LABELS = {
    "ean": ["ean", "cikkszam", "vonalkod", "gtin", "termekkod", "cikk szam"],
    "size": ["kiszereles", "kiszerelesi egyseg", "urtartalom", "tomeg", "nettó tömeg", "netto tomeg", "mennyiseg"],
    "brand": ["marka", "gyarto", "brand"],
    "unit_price": ["egysegar", "egyseg ar"],
}

_PRICE_NEG = ("regi", "old", "eredeti", "strike", "was", "unit", "egyseg", "base", "compare", "listprice", "crossed")


def soup_of(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 – lxml hiányában
        return BeautifulSoup(html, "html.parser")


# --------------------------------------------------------------- JSON-LD

def from_jsonld(blocks: List[Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for block in blocks:
        for _, node in walk_json(block):
            if not isinstance(node, dict):
                continue
            types = node.get("@type") or node.get("type")
            types = [types] if isinstance(types, str) else (types or [])
            if not any(str(t).lower() == "product" for t in types):
                continue
            out.setdefault("name", clean_text(node.get("name")))
            for key in ("gtin13", "gtin", "gtin12", "gtin14", "ean"):
                val = node.get(key)
                if val and gtin_is_valid(str(val).strip()):
                    out.setdefault("ean", str(val).strip())
                    break
            brand = node.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            if brand:
                out.setdefault("brand_raw", clean_text(brand))
            offers = node.get("offers")
            offers = offers if isinstance(offers, list) else ([offers] if offers else [])
            for off in offers:
                if not isinstance(off, dict):
                    continue
                price = off.get("price") or off.get("lowPrice")
                p = deep_price(price)
                if p:
                    out.setdefault("price", p)
                avail = off.get("availability")
                if avail:
                    out.setdefault("availability", str(avail).split("/")[-1])
            if node.get("sku"):
                out.setdefault("sku", clean_text(node.get("sku")))
            if out.get("name") and out.get("price"):
                out["strategy"] = "json-ld"
                return out
    if out:
        out.setdefault("strategy", "json-ld(részleges)")
    return out


# ------------------------------------------------------ beágyazott JSON

def from_embedded_json(blocks: List[Any], hint: str = "") -> Dict[str, Any]:
    best: Dict[str, Any] = {}
    best_score = -1
    hint_n = normalize(hint)
    for block in blocks:
        for _, node in walk_json(block):
            if not looks_like_product(node):
                continue
            rec = product_from_dict(node)
            if not rec.get("name"):
                continue
            score = 0
            if rec.get("price"):
                score += 3
            if rec.get("ean"):
                score += 2
            if hint_n and normalize(rec["name"])[:25] and normalize(rec["name"])[:25] in hint_n:
                score += 2
            if score > best_score:
                best, best_score = rec, score
    if best:
        best["strategy"] = "beágyazott-json"
    return best


def product_from_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    """Egy termék-szerű dict -> normalizált mezők."""
    rec: Dict[str, Any] = {}
    name = get_first(node, ("name", "title", "productname", "displayname", "headline"))
    if isinstance(name, dict):
        name = get_first(name, ("hu", "value", "text", "default"))
    if name:
        rec["name"] = clean_text(name)

    price = get_first(node, ("price", "grossprice", "currentprice", "sellingprice", "salesprice", "pricevalue"))
    p = deep_price(price)
    if p is None and "prices" in {k.lower() for k in node}:
        p = deep_price(get_first(node, ("prices",)))
    if p is not None:
        rec["price"] = p

    old = deep_price(get_first(node, ("oldprice", "listprice", "regularprice", "strikeprice", "originalprice")))
    if old:
        rec["old_price"] = old

    ean = get_first(node, ("gtin", "gtin13", "ean", "eancode", "barcode", "vonalkod"))
    if ean and gtin_is_valid(str(ean).strip()):
        rec["ean"] = str(ean).strip()

    sku = get_first(node, ("dan", "sku", "articlenumber", "cikkszam", "productid", "id"))
    if sku is not None:
        sku_s = str(sku).strip()
        if sku_s and len(sku_s) <= 24:
            rec["sku"] = sku_s
            if not rec.get("ean") and gtin_is_valid(sku_s):
                rec["ean"] = sku_s

    brand = get_first(node, ("brandname", "brand", "marka", "manufacturer"))
    if isinstance(brand, dict):
        brand = get_first(brand, ("name", "title", "value"))
    if brand:
        rec["brand_raw"] = clean_text(brand)

    qty = get_first(node, ("netquantitycontent", "contentsize", "quantity", "kiszereles", "packsize", "netquantity"))
    if isinstance(qty, dict):
        val = get_first(qty, ("value", "amount", "quantity"))
        unit = get_first(qty, ("unit", "uom", "measure"))
        if val and unit:
            rec["size_text"] = "{} {}".format(val, unit)
    elif qty:
        rec["size_text"] = clean_text(qty)

    unit_price = get_first(node, ("baseprice", "unitprice", "egysegar", "priceperunit"))
    if isinstance(unit_price, dict):
        unit_price = get_first(unit_price, ("formattedvalue", "formatted", "text", "value"))
    if unit_price:
        rec["unit_price"] = clean_text(unit_price)

    url = get_first(node, ("url", "relativeproducturl", "producturl", "link", "canonicalurl"))
    if isinstance(url, str) and url.startswith(("/", "http")):
        rec["url_hint"] = url

    avail = get_first(node, ("availability", "instock", "stockstatus", "available"))
    if avail is not None:
        rec["availability"] = ("Készleten" if avail is True else "Nincs készleten" if avail is False
                               else clean_text(avail))
    return rec


# --------------------------------------------------------------- meta tag

def from_meta(soup: BeautifulSoup) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    def meta(*names: str) -> Optional[str]:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return clean_text(tag["content"])
        return None

    title = meta("og:title", "twitter:title")
    if title:
        out["name"] = title
    price = meta("product:price:amount", "og:price:amount", "twitter:data1")
    if price:
        p = parse_price_hu(price)
        if p:
            out["price"] = p
    if out:
        out["strategy"] = "meta-tag"
    return out


# ------------------------------------------------------------ DOM heurisztika

def from_dom(soup: BeautifulSoup) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    h1 = soup.find("h1")
    if h1:
        out["name"] = clean_text(h1.get_text(" "))

    # --- ár: "Ft"-ot tartalmazó, ár-jellegű osztályú elemek
    candidates = []
    for el in soup.find_all(["span", "div", "p", "strong", "b", "ins", "del", "data"]):
        cls = " ".join(el.get("class") or []) + " " + (el.get("id") or "") + " " + (el.get("data-testid") or "")
        cls_n = normalize(cls)
        txt = clean_text(el.get_text(" "))
        if not txt or len(txt) > 40 or "Ft" not in txt:
            continue
        val = parse_price_hu(txt)
        if not val or val <= 0:
            continue
        # kizárjuk az egységárat ("Ft/l", "Ft/db")
        if re.search(r"Ft\s*/", txt):
            if "unit_price" not in out:
                out["unit_price"] = txt
            continue
        score = 0
        if "price" in cls_n or "ar " in cls_n + " ":
            score += 3
        if el.name == "del" or any(neg in cls_n for neg in _PRICE_NEG):
            score -= 4
        if el.name == "ins":
            score += 2
        candidates.append((score, -len(txt), val, txt))
    if candidates:
        candidates.sort(reverse=True)
        out["price"] = candidates[0][2]
        neg = [c for c in candidates if c[0] < 0]
        if neg and neg[0][2] > candidates[0][2]:
            out["old_price"] = neg[0][2]

    # --- specifikációs tábla / definíciós lista
    specs = read_spec_pairs(soup)
    if specs:
        out["specs"] = specs
        for key, labels in LABELS.items():
            for label, value in specs.items():
                if any(lb in label for lb in labels):
                    if key == "ean":
                        cand = find_ean(value)
                        if cand:
                            out.setdefault("ean", cand)
                    elif key == "size":
                        out.setdefault("size_text", value)
                    elif key == "unit_price":
                        out.setdefault("unit_price", value)
                    elif key == "brand":
                        out.setdefault("brand_raw", value)
                    break

    if out:
        out["strategy"] = "dom"
    return out


def read_spec_pairs(soup: BeautifulSoup) -> Dict[str, str]:
    """Címke -> érték párok táblákból, dl-ekből és két-cellás div-ekből."""
    pairs: Dict[str, str] = {}

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) == 2:
            k = normalize(cells[0].get_text(" "))
            v = clean_text(cells[1].get_text(" "))
            if k and v:
                pairs.setdefault(k, v)

    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            k = normalize(dt.get_text(" "))
            v = clean_text(dd.get_text(" "))
            if k and v:
                pairs.setdefault(k, v)

    # két gyerekes div/li párok (gyakori modern webshopokon)
    for el in soup.find_all(["li", "div"]):
        kids = [c for c in el.find_all(recursive=False) if c.name in ("span", "div", "p", "strong", "b")]
        if len(kids) == 2:
            k = normalize(kids[0].get_text(" "))
            v = clean_text(kids[1].get_text(" "))
            if k and v and len(k) < 40 and len(v) < 120:
                pairs.setdefault(k, v)

    return pairs


# ------------------------------------------------------------------- összefűzés

def extract_product(html: str, url: str = "") -> Dict[str, Any]:
    """Minden stratégia futtatása és az eredmények egyesítése."""
    soup = soup_of(html)
    blocks = json_blocks(html)

    layers = [
        from_jsonld(blocks),
        from_embedded_json(blocks, hint=url),
        from_dom(soup),
        from_meta(soup),
    ]

    merged: Dict[str, Any] = {}
    used: List[str] = []
    for layer in layers:
        if not layer:
            continue
        strat = layer.pop("strategy", "")
        contributed = False
        for k, v in layer.items():
            if v in (None, "", {}, []):
                continue
            if k not in merged:
                merged[k] = v
                contributed = True
        if contributed and strat:
            used.append(strat)

    # EAN utolsó esély: a nyers HTML-ben, címke közelében
    if not merged.get("ean"):
        cand = find_ean(soup.get_text(" "))
        if cand:
            merged["ean"] = cand
            used.append("ean-regex")

    merged["strategy"] = "+".join(dict.fromkeys(used)) or "nincs"
    merged["url"] = url
    return merged


def to_dict_from_json_text(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None
