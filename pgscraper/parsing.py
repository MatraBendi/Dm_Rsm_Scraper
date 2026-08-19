"""Szöveg-feldolgozó segédfüggvények: ár, kiszerelés, EAN, normalizálás.

Ez a modul szándékosan nem függ a konkrét weboldalak HTML-szerkezetétől,
így önmagában is tesztelhető (lásd tests/test_parsing.py).
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------- normalizálás

_WS = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize(text: Optional[str]) -> str:
    """Kisbetűs, ékezet nélküli, egyszeres szóközös változat – kereséshez."""
    if not text:
        return ""
    t = strip_accents(str(text)).lower()
    t = t.replace("&", " and ").replace("+", " plus ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return _WS.sub(" ", t).strip()


def slugify(text: str) -> str:
    t = strip_accents(str(text)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


# ------------------------------------------------------------------------- ár

_PRICE_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[   .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(?:Ft|HUF|ft)\b"
)


def parse_price_hu(text: Optional[str]) -> Optional[float]:
    """Magyar formátumú ár szövegből float.

    Kezeli: "2 354 Ft", "2.354 Ft", "2,354 Ft", "1 995,50 Ft", "1995 Ft".
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).replace(" ", " ").replace(" ", " ")
    m = _PRICE_RE.search(s)
    raw = m.group(1) if m else None
    if raw is None:
        # "Ft" nélküli, csak szám (pl. JSON mező)
        m2 = re.search(r"(?<![\d.,])(\d{1,3}(?:[ .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d])", s)
        if not m2:
            return None
        raw = m2.group(1)
    return _to_float(raw)


def _to_float(raw: str) -> Optional[float]:
    raw = raw.strip().replace(" ", "")
    # tisztán ezres elválasztók: 2.354 / 2,354 / 1.234.567
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        return float(re.sub(r"[.,]", "", raw))
    # ezres + tizedes: 1.234,56 vagy 1,234.56
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)([.,])(\d{1,2})", raw)
    if m:
        return float(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(3))
    # egyszerű tizedes: 1995,5 / 1995.5
    if re.fullmatch(r"\d+[.,]\d{1,2}", raw):
        return float(raw.replace(",", "."))
    if re.fullmatch(r"\d+", raw):
        return float(raw)
    try:
        return float(re.sub(r"[^0-9.]", "", raw.replace(",", ".")))
    except ValueError:
        return None


# ----------------------------------------------------------------- kiszerelés

_UNIT_ALIASES = {
    "ml": "ml", "milliliter": "ml", "mL": "ml",
    "l": "l", "liter": "l", "litre": "l",
    "g": "g", "gr": "g", "gramm": "g",
    "kg": "kg", "kilogramm": "kg",
    "db": "db", "darab": "db", "pcs": "db", "x": "db",
    "par": "pár", "pár": "pár",
    "mosas": "mosás", "mosás": "mosás",
}

# "3 x 400 ml", "2x90 db", "400 ml", "0,4 l", "50 g", "16 db", "36 mosás"
_SIZE_RE = re.compile(
    r"(?:(?P<pack>\d{1,2})\s*[x×]\s*)?"
    r"(?P<value>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>ml|milliliter|l\b|liter|litre|kg|g\b|gr\b|gramm|db\b|darab|pcs|par\b|pár|mosás|mosas)",
    re.IGNORECASE,
)


def parse_size(text: Optional[str]) -> Tuple[Optional[float], Optional[str], Optional[int], str]:
    """(érték, egység, csomagdarab, címke) a terméknévből / kiszerelés mezőből.

    A *legutolsó* egyértelmű találatot részesíti előnyben, mert a magyar
    terméknevekben a kiszerelés jellemzően a név végén áll
    (pl. "Head & Shoulders Classic Clean 2az1-ben sampon - 625 ml").
    """
    if not text:
        return None, None, None, ""
    s = str(text).replace(" ", " ")
    matches = list(_SIZE_RE.finditer(s))
    if not matches:
        return None, None, None, ""

    def score(m: "re.Match[str]") -> Tuple[int, int]:
        unit = _norm_unit(m.group("unit"))
        # a térfogat/tömeg egységek erősebb jelöltek, mint a "db"
        prio = 2 if unit in ("ml", "l", "g", "kg") else 1
        return (prio, m.start())

    best = sorted(matches, key=score)[-1]
    value = _to_float(best.group("value"))
    unit = _norm_unit(best.group("unit"))
    pack = int(best.group("pack")) if best.group("pack") else None

    # 0,4 l -> 400 ml ; 1,5 kg -> 1500 g  (egységesítés az összehasonlításhoz)
    if unit == "l" and value is not None:
        value, unit = value * 1000, "ml"
    elif unit == "kg" and value is not None:
        value, unit = value * 1000, "g"

    label = format_size(value, unit, pack)
    return value, unit, pack, label


def _norm_unit(u: str) -> str:
    key = strip_accents(u.lower().strip())
    return _UNIT_ALIASES.get(key, _UNIT_ALIASES.get(u.lower().strip(), u.lower().strip()))


def format_size(value: Optional[float], unit: Optional[str], pack: Optional[int] = None) -> str:
    if value is None or not unit:
        return ""
    num = int(value) if float(value).is_integer() else round(float(value), 2)
    base = "{} {}".format(num, unit)
    return "{}x{}".format(pack, base) if pack and pack > 1 else base


# ------------------------------------------------------------------ EAN/GTIN

_DIGITS_RE = re.compile(r"(?<!\d)(\d{8}|\d{12,14})(?!\d)")


def gtin_is_valid(code: str) -> bool:
    """GS1 ellenőrző összeg (EAN-8/12/13/14)."""
    if not code or not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    check = digits[-1]
    body = digits[:-1][::-1]
    total = 0
    for i, d in enumerate(body):
        total += d * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10 == check


def find_ean(text: Optional[str], prefer_labels: Iterable[str] = ("ean", "cikkszam", "vonalkod", "gtin")) -> Optional[str]:
    """Első érvényes GTIN a szövegből; a címkék közelében találtakat előnyben részesíti."""
    if not text:
        return None
    s = str(text)
    norm = normalize(s)

    # 1) címke közelében
    for label in prefer_labels:
        for m in re.finditer(re.escape(label), norm):
            window = s[max(0, _approx_index(s, norm, m.start()) - 5): _approx_index(s, norm, m.start()) + 120]
            for cand in _DIGITS_RE.findall(window):
                if gtin_is_valid(cand):
                    return cand.zfill(13) if len(cand) == 12 else cand

    # 2) bárhol a szövegben
    for cand in _DIGITS_RE.findall(s):
        if gtin_is_valid(cand):
            return cand.zfill(13) if len(cand) == 12 else cand
    return None


def _approx_index(original: str, normalized: str, norm_pos: int) -> int:
    """Durva pozíció-visszaképzés normalizált -> eredeti szövegre."""
    if not normalized:
        return 0
    ratio = norm_pos / max(1, len(normalized))
    return min(len(original) - 1, max(0, int(ratio * len(original))))


# ------------------------------------------------- általános JSON bejárás

def walk_json(obj: Any, path: str = "$") -> Iterable[Tuple[str, Any]]:
    """Minden (útvonal, érték) pár a JSON-fában."""
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_json(v, "{}.{}".format(path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_json(v, "{}[{}]".format(path, i))


_NAME_KEYS = ("name", "title", "productname", "product_name", "displayname", "headline")
_PRICE_KEYS = ("price", "grossprice", "currentprice", "sellingprice", "value", "amount", "formattedvalue")
_EAN_KEYS = ("gtin", "gtin13", "ean", "eancode", "barcode", "vonalkod")


def looks_like_product(d: Any) -> bool:
    """Heurisztika: ez a dict egy termék?"""
    if not isinstance(d, dict):
        return False
    keys = {str(k).lower().replace("-", "").replace("_", "") for k in d.keys()}
    has_name = any(k in keys for k in _NAME_KEYS)
    has_price = any(k in keys for k in _PRICE_KEYS) or "price" in " ".join(keys)
    has_id = any(k in keys for k in _EAN_KEYS) or "dan" in keys or "sku" in keys or "productid" in keys
    return has_name and (has_price or has_id)


def get_first(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    lowered = {str(k).lower().replace("-", "").replace("_", ""): v for k, v in d.items()}
    for k in keys:
        if k in lowered and lowered[k] not in (None, "", []):
            return lowered[k]
    return None


def deep_price(value: Any) -> Optional[float]:
    """Ár kinyerése számból, stringből vagy beágyazott dict-ből."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # néhány API fillérben/centben adja meg
        return v
    if isinstance(value, str):
        return parse_price_hu(value)
    if isinstance(value, dict):
        for key in ("value", "amount", "gross", "grossValue", "formattedValue", "formatted", "price"):
            if key in value:
                got = deep_price(value[key])
                if got is not None:
                    return got
    return None


def json_blocks(html: str) -> List[Any]:
    """Beágyazott JSON blokkok kinyerése HTML-ből (JSON-LD, __NEXT_DATA__, __NUXT__...)."""
    out: List[Any] = []
    patterns = [
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        r'<script[^>]*>\s*window\.__NUXT__\s*=\s*(\{.*?\})\s*;?\s*</script>',
        r'<script[^>]*>\s*window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>',
        r'<script[^>]*>\s*window\.__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL | re.IGNORECASE):
            raw = m.group(1).strip()
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
    return out


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return _WS.sub(" ", str(text).replace(" ", " ")).strip()
