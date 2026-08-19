"""Közös adatmodellek a P&G ár-scraperhez."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class Product:
    """Egy bolti termék egy adott időpontban."""

    store: str = ""                     # "dm" vagy "Rossmann"
    brand: str = ""                     # kanonikus márkanév (pl. "Head & Shoulders")
    brand_group: str = ""               # kategória (pl. "Hajápolás")
    name: str = ""                      # teljes terméknév a boltban
    size_value: Optional[float] = None  # 400
    size_unit: Optional[str] = None     # "ml"
    pack_count: Optional[int] = None    # 3 (pl. "3 x 400 ml")
    size_label: str = ""                # "400 ml" / "3x400 ml"
    variant_group: str = ""             # "Head & Shoulders 400 ml"
    price: Optional[float] = None       # 2354.0 (Ft)
    currency: str = "HUF"
    unit_price: Optional[str] = None    # "5 885 Ft/l"
    old_price: Optional[float] = None   # akciós esetén az eredeti ár
    ean: Optional[str] = None           # 13 jegyű GTIN
    sku: Optional[str] = None           # bolti cikkszám (dm: DAN)
    availability: Optional[str] = None
    url: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    scraped_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    extraction: str = ""                # melyik stratégia adta az adatot (diagnosztika)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunStats:
    """Egy futás összegzése."""

    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: Optional[str] = None
    stores: List[str] = field(default_factory=list)
    brands: List[str] = field(default_factory=list)
    total_found: int = 0
    with_price: int = 0
    with_ean: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
