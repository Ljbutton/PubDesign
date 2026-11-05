"""Simple document model shared by the editor and the .pub writer.
All geometry is in points (1/72 inch) relative to the page's top-left corner."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

RGB = Tuple[int, int, int]


@dataclass
class Run:
    text: str
    font: str = "Calibri"
    size: float = 12.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: RGB = (0, 0, 0)


@dataclass
class Para:
    runs: List[Run] = field(default_factory=list)
    align: str = "left"  # left, center, right, justify

    @property
    def text(self):
        return "".join(r.text for r in self.runs)


@dataclass
class Item:
    kind: str  # text, rect, ellipse, line, image
    x: float = 0
    y: float = 0
    w: float = 100
    h: float = 50
    rotation: float = 0
    fill: Optional[RGB] = None
    stroke: Optional[RGB] = None
    stroke_width: float = 1.0
    paras: List[Para] = field(default_factory=list)  # text
    valign: str = "top"
    image: bytes = b""  # image (png or jpeg bytes)
    image_name: str = "picture.png"
    path_d: Optional[str] = None  # kind == "path": SVG path data in view coordinates
    view: Tuple[float, float, float, float] = (0, 0, 1, 1)
    spt: int = 0  # kind == "auto": Publisher AutoShape type id (see autoshapes.py)
    # line endpoints are (x, y) -> (x + w, y + h); w/h may be negative


@dataclass
class Page:
    items: List[Item] = field(default_factory=list)


@dataclass
class Document:
    width: float = 612  # points (Letter)
    height: float = 792
    pages: List[Page] = field(default_factory=lambda: [Page()])


EMU_PER_PT = 12700
