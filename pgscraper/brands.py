"""P&G márkakatalógus – magyar piac (dm.hu / Rossmann).

Bővítés: vegyél fel egy új Brand sort. A `slug_tokens` a termék-URL-ekben
keresett darabok, az `aliases` pedig a terméknévben keresett változatok.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .parsing import normalize


@dataclass
class Brand:
    key: str
    display: str
    group: str
    aliases: List[str] = field(default_factory=list)
    slug_tokens: List[str] = field(default_factory=list)
    rossmann_slug: Optional[str] = None
    default_on: bool = True

    def matches_name(self, name: str) -> bool:
        n = " {} ".format(normalize(name))
        for a in [self.display] + self.aliases:
            if " {} ".format(normalize(a)) in n:
                return True
        return False

    def matches_url(self, url: str) -> bool:
        u = url.lower()
        for tok in self.slug_tokens or [self.key]:
            if "/{}".format(tok) in u or "-{}-".format(tok) in u or "/{}-".format(tok) in u:
                return True
        return False


GROUPS = [
    "Hajápolás",
    "Borotválkozás & testápolás",
    "Szájápolás",
    "Mosás & háztartás",
    "Női higiénia & baba",
]


BRANDS: List[Brand] = [
    # ------------------------------------------------------------- Hajápolás
    Brand("head-shoulders", "Head & Shoulders", "Hajápolás",
          aliases=["head and shoulders", "head&shoulders", "h&s", "head shoulders"],
          slug_tokens=["head-shoulders", "head-and-shoulders"],
          rossmann_slug="head-shoulders"),
    Brand("pantene", "Pantene", "Hajápolás",
          aliases=["pantene pro-v", "pantene pro v"],
          slug_tokens=["pantene"], rossmann_slug="pantene"),
    Brand("herbal-essences", "Herbal Essences", "Hajápolás",
          aliases=["herbal essences bio renew"],
          slug_tokens=["herbal-essences"], rossmann_slug="herbal-essences"),
    Brand("aussie", "Aussie", "Hajápolás",
          slug_tokens=["aussie"], rossmann_slug="aussie"),

    # ------------------------------------------- Borotválkozás & testápolás
    Brand("gillette", "Gillette", "Borotválkozás & testápolás",
          aliases=["gillette fusion", "gillette mach3", "gillette skinguard", "gillette labs"],
          slug_tokens=["gillette"], rossmann_slug="gillette"),
    Brand("venus", "Gillette Venus", "Borotválkozás & testápolás",
          aliases=["venus"], slug_tokens=["venus", "gillette-venus"], rossmann_slug="venus"),
    Brand("braun", "Braun", "Borotválkozás & testápolás",
          slug_tokens=["braun"], rossmann_slug="braun"),
    Brand("old-spice", "Old Spice", "Borotválkozás & testápolás",
          slug_tokens=["old-spice"], rossmann_slug="old-spice"),

    # ------------------------------------------------------------ Szájápolás
    Brand("oral-b", "Oral-B", "Szájápolás",
          aliases=["oral b", "oralb"], slug_tokens=["oral-b", "oralb"], rossmann_slug="oral-b"),
    Brand("blend-a-med", "Blend-a-med", "Szájápolás",
          aliases=["blend a med", "blendamed"], slug_tokens=["blend-a-med"], rossmann_slug="blend-a-med"),
    Brand("blend-a-dent", "Blend-a-dent", "Szájápolás",
          aliases=["blend a dent", "blendadent"], slug_tokens=["blend-a-dent"], rossmann_slug="blend-a-dent"),

    # ------------------------------------------------------ Mosás & háztartás
    Brand("ariel", "Ariel", "Mosás & háztartás",
          slug_tokens=["ariel"], rossmann_slug="ariel"),
    Brand("lenor", "Lenor", "Mosás & háztartás",
          aliases=["lenor unstoppables"], slug_tokens=["lenor"], rossmann_slug="lenor"),
    Brand("fairy", "Fairy", "Mosás & háztartás",
          slug_tokens=["fairy"], rossmann_slug="fairy"),
    Brand("mr-proper", "Mr. Proper", "Mosás & háztartás",
          aliases=["mr proper", "mrproper"], slug_tokens=["mr-proper"], rossmann_slug="mr-proper",
          default_on=False),
    Brand("ambi-pur", "Ambi Pur", "Mosás & háztartás",
          aliases=["ambipur"], slug_tokens=["ambi-pur"], rossmann_slug="ambi-pur", default_on=False),
    Brand("bonux", "Bonux", "Mosás & háztartás",
          slug_tokens=["bonux"], rossmann_slug="bonux", default_on=False),

    # ------------------------------------------------- Női higiénia & baba
    Brand("always", "Always", "Női higiénia & baba",
          aliases=["always discreet", "always ultra"], slug_tokens=["always"], rossmann_slug="always"),
    Brand("tampax", "Tampax", "Női higiénia & baba",
          slug_tokens=["tampax"], rossmann_slug="tampax"),
    Brand("discreet", "Discreet", "Női higiénia & baba",
          slug_tokens=["discreet"], rossmann_slug="discreet"),
    Brand("naturella", "Naturella", "Női higiénia & baba",
          slug_tokens=["naturella"], rossmann_slug="naturella", default_on=False),
    Brand("pampers", "Pampers", "Női higiénia & baba",
          slug_tokens=["pampers"], rossmann_slug="pampers"),
]


BY_KEY: Dict[str, Brand] = {b.key: b for b in BRANDS}


def get_brands(keys: Optional[List[str]] = None) -> List[Brand]:
    if not keys:
        return [b for b in BRANDS if b.default_on]
    return [BY_KEY[k] for k in keys if k in BY_KEY]


def match_brand(text: str, candidates: Optional[List[Brand]] = None) -> Optional[Brand]:
    """A terméknévhez tartozó márka; a leghosszabb egyezés nyer (Venus > Gillette)."""
    cands = candidates or BRANDS
    hits = [b for b in cands if b.matches_name(text)]
    if not hits:
        return None
    return sorted(hits, key=lambda b: len(normalize(b.display)), reverse=True)[0]


def grouped() -> Dict[str, List[Brand]]:
    out: Dict[str, List[Brand]] = {g: [] for g in GROUPS}
    for b in BRANDS:
        out.setdefault(b.group, []).append(b)
    return out
