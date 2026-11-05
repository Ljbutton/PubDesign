"""Missing fonts: fetch free Google Fonts so publications look the way they were designed.

Publisher files often use fonts that aren't on this computer (e.g. "Rubik Medium"). Windows then
substitutes a font with different widths, so lines wrap differently and text can spill out of its
box. If the font is a free Google Font, PubDesign downloads it once from the official
google/fonts repository, makes a copy named exactly as the publication asks for it (regular, bold,
italic, bold italic), and loads it for PubDesign only. Nothing is installed into Windows.
"""
import json
import os
import re
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal

RAW = "https://raw.githubusercontent.com/google/fonts/main"
UA = {"User-Agent": "PubDesign-Fonts"}
WEIGHT_WORDS = {
    "thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "regular": 400,
    "book": 400, "normal": 400, "medium": 500, "semibold": 600, "demibold": 600, "bold": 700,
    "extrabold": 800, "ultrabold": 800, "black": 900, "heavy": 900,
}
_lock = threading.Lock()
_tried = set()          # families looked up this session (found or not)


def font_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, "PubDesign", "fonts")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path():
    return os.path.join(font_dir(), "index.json")


def _load_index():
    try:
        with open(_index_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_index(idx):
    try:
        with open(_index_path(), "w", encoding="utf-8") as f:
            json.dump(idx, f, indent=1)
    except OSError:
        pass


def split_family(name):
    """'Rubik Medium' -> ('Rubik', 500); 'Open Sans Extra Bold' -> ('Open Sans', 800)."""
    words = name.split()
    weight = 400
    while len(words) > 1:
        last = words[-1].lower()
        two = (words[-2] + words[-1]).lower() if len(words) > 2 else None
        if two in WEIGHT_WORDS:
            weight = WEIGHT_WORDS[two]
            words = words[:-2]
        elif last in WEIGHT_WORDS:
            weight = WEIGHT_WORDS[last]
            words = words[:-1]
        elif last in ("italic", "oblique"):
            words = words[:-1]
        else:
            break
    return " ".join(words), weight


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _metadata(base):
    slug = re.sub(r"[^a-z0-9]", "", base.lower())
    for lic in ("ofl", "apache", "ufl"):
        try:
            text = _get(f"{RAW}/{lic}/{slug}/METADATA.pb").decode("utf-8", "replace")
        except Exception:
            continue
        fonts = []
        for block in re.findall(r"fonts\s*\{(.*?)\}", text, re.S):
            def field(k):
                m = re.search(rf'{k}:\s*"?([^"\n]+)"?', block)
                return m.group(1).strip() if m else ""
            fonts.append({"style": field("style") or "normal", "weight": int(field("weight") or 400),
                          "filename": field("filename")})
        if fonts:
            return f"{RAW}/{lic}/{slug}", fonts
    return None, []


def _pick(fonts, style, weight):
    """Best file for a style/weight: exact static file, else the variable font, else nearest weight."""
    same = [f for f in fonts if f["style"] == style] or [f for f in fonts if f["style"] == "normal"]
    if not same:
        return None
    exact = [f for f in same if f["weight"] == weight and "[" not in f["filename"]]
    if exact:
        return exact[0]
    var = [f for f in same if "[" in f["filename"]]
    if var:
        return var[0]
    return min(same, key=lambda f: abs(f["weight"] - weight))


def _make_static(src_bytes, family, style_name, weight, bold, italic, out_path):
    import io
    from fontTools.ttLib import TTFont
    font = TTFont(io.BytesIO(src_bytes))
    if "fvar" in font:
        from fontTools.varLib import instancer
        loc = {}
        for ax in font["fvar"].axes:   # pin every axis so the result is a plain static font
            if ax.axisTag == "wght":
                loc["wght"] = max(ax.minValue, min(ax.maxValue, weight))
            elif ax.axisTag == "ital":
                loc["ital"] = max(ax.minValue, min(ax.maxValue, 1 if italic else 0))
            else:
                loc[ax.axisTag] = ax.defaultValue
        font = instancer.instantiateVariableFont(font, loc, inplace=False)
        for t in ("STAT", "fvar", "avar", "gvar", "HVAR", "MVAR"):
            if t in font:
                del font[t]
    name = font["name"]
    for nid in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
        name.removeNames(nameID=nid)
    ps = re.sub(r"[^A-Za-z0-9-]", "", f"{family}-{style_name}")[:60] or "PubDesignFont"
    for (pid, eid, lid) in ((3, 1, 0x409), (1, 0, 0)):
        name.setName(family, 1, pid, eid, lid)
        name.setName(style_name, 2, pid, eid, lid)
        name.setName(f"PubDesign:{ps}", 3, pid, eid, lid)
        name.setName(f"{family} {style_name}" if style_name != "Regular" else family, 4, pid, eid, lid)
        name.setName(ps, 6, pid, eid, lid)
    if "OS/2" in font:
        os2 = font["OS/2"]
        os2.usWeightClass = 700 if bold else 400
        sel = os2.fsSelection & ~(1 | (1 << 5) | (1 << 6))
        if bold:
            sel |= 1 << 5
        if italic:
            sel |= 1
        if not bold and not italic:
            sel |= 1 << 6
        os2.fsSelection = sel
    if "head" in font:
        font["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)
    font.save(out_path)


def fetch(family):
    """Download/build the font files for `family`. Returns a list of .ttf paths ([] if not a Google Font).
    Runs without Qt, so it is safe in a background thread."""
    base, weight = split_family(family)
    url, fonts = _metadata(base)
    if not fonts:
        return []
    safe = re.sub(r"[^A-Za-z0-9]+", "_", family).strip("_")
    bold_w = 700 if weight < 600 else 900
    out = []
    cache = {}
    for style_name, w, bold, italic in (("Regular", weight, False, False), ("Bold", bold_w, True, False),
                                        ("Italic", weight, False, True), ("Bold Italic", bold_w, True, True)):
        f = _pick(fonts, "italic" if italic else "normal", w)
        if f is None or (italic and f["style"] != "italic"):
            continue
        try:
            if f["filename"] not in cache:
                cache[f["filename"]] = _get(f"{url}/{urllib.request.quote(f['filename'])}", timeout=60)
            path = os.path.join(font_dir(), f"{safe}-{style_name.replace(' ', '')}.ttf")
            _make_static(cache[f["filename"]], family, style_name, w, bold, italic, path)
            out.append(path)
        except Exception:
            continue
    return out


def load_cached():
    """Load fonts PubDesign downloaded before (call once after QApplication exists)."""
    from PySide6.QtGui import QFontDatabase
    for fam, paths in _load_index().items():
        for p in paths:
            if os.path.exists(p):
                QFontDatabase.addApplicationFont(p)


def installed_families():
    from PySide6.QtGui import QFontDatabase
    return {f.lower() for f in QFontDatabase.families()}


class FontFetcher(QObject):
    """Looks up missing fonts in a background thread. `ready` fires (on the UI thread) with
    {family: [paths]} for the fonts that were found."""
    ready = Signal(dict)
    status = Signal(str)

    def fetch_missing(self, families):
        have = installed_families()
        todo = []
        with _lock:
            for fam in families:
                if not fam or fam.lower() in have or fam in _tried:
                    continue
                _tried.add(fam)
                todo.append(fam)
        if not todo:
            return
        self.status.emit("Getting the free font" + ("s " if len(todo) > 1 else " ") +
                         ", ".join(todo) + " from Google Fonts…")

        def run():
            found = {}
            for fam in todo:
                try:
                    paths = fetch(fam)
                except Exception:
                    paths = []
                if paths:
                    found[fam] = paths
            if found:
                with _lock:
                    idx = _load_index()
                    idx.update(found)
                    _save_index(idx)
            self.ready.emit(found)
        threading.Thread(target=run, daemon=True).start()
