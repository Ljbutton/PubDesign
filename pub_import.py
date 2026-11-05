"""Import Microsoft Publisher (.pub) files.

Publisher files are read through LibreOffice (free), which converts the .pub
into a flat ODF drawing that this module turns into an editable Document.
"""
import base64
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from pubmodel import Document, Page, Item, Para, Run

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "loext": "urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0",
}


def q(tag):
    p, t = tag.split(":")
    return "{%s}%s" % (NS[p], t)


class ImportError_(Exception):
    pass


# ---------------------------------------------------------------------------
# bundled Publisher reader (pubconv: libmspub + libodfgen, built in tools/pubconv)
# ---------------------------------------------------------------------------
def _app_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [getattr(sys, "_MEIPASS", None), os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else None, here]
    return [d for d in dirs if d]


def find_pubconv():
    exe = "pubconv.exe" if os.name == "nt" else "pubconv"
    for d in _app_dirs():
        for sub in ("pubconv", os.path.join("tools", "pubconv", "build"), os.path.join("tools", "pubconv")):
            p = os.path.join(d, sub, exe)
            if os.path.isfile(p):
                return p
    return shutil.which(exe)


def _run_tool(cmd, timeout):
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, **kw)


last_pubconv_error = ""


def pubconv_to_fodg(src, outdir):
    """Publisher file -> flat ODG with the bundled reader. Returns the path or None."""
    tool = find_pubconv()
    if not tool:
        return None
    out = os.path.join(outdir, "pubconv.fodg")
    global last_pubconv_error
    try:
        r = _run_tool([tool, src, out], timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        last_pubconv_error = repr(e)
        return None
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 200:
        last_pubconv_error = f"exit {r.returncode}: {r.stderr.decode(errors='replace').strip()[:300]}"
        return None
    last_pubconv_error = ""
    return out


def wmf_placeable(data):
    """Plain WMF -> placeable WMF (adds the header GDI+ needs to know the picture's size)."""
    import struct
    if data[:4] == b"\xd7\xcd\xc6\x9a" or len(data) < 18:
        return data
    org, ext = (0, 0), None
    pos = struct.unpack_from("<H", data, 2)[0] * 2  # header size in words
    while pos + 6 <= len(data):
        size, func = struct.unpack_from("<IH", data, pos)
        if size < 3:
            break
        if func == 0x020B and pos + 10 <= len(data):      # SetWindowOrg(y, x)
            y, x = struct.unpack_from("<hh", data, pos + 6)
            org = (x, y)
        elif func == 0x020C and pos + 10 <= len(data):    # SetWindowExt(y, x)
            y, x = struct.unpack_from("<hh", data, pos + 6)
            ext = (x, y)
        if func == 0:
            break
        pos += size * 2
    if not ext or ext[0] == 0 or ext[1] == 0:
        ext = (1000, 1000)
    xs = (org[0], org[0] + ext[0])
    ys = (org[1], org[1] + ext[1])
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    head = struct.pack("<IHhhhhHI", 0x9AC6CDD7, 0, left, top, right, bottom, 1440, 0)
    chk = 0
    for (w,) in struct.iter_unpack("<H", head):
        chk ^= w
    return head + struct.pack("<H", chk) + data


def metafile_to_png_native(data, kind, width, height, workdir):
    """WMF/EMF -> transparent PNG with Windows' own drawing engine (GDI+) through pubconv."""
    tool = find_pubconv()
    if not tool or os.name != "nt":
        return None
    src = os.path.join(workdir, f"m{abs(hash(data)) % 10**8}.{kind}")
    out = src + ".png"
    with open(src, "wb") as f:
        f.write(wmf_placeable(data) if kind == "wmf" else data)
    try:
        r = _run_tool([tool, "--meta", src, out, str(width), str(height)], timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not os.path.exists(out):
        return None
    with open(out, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# LibreOffice discovery / conversion (optional fallback)
# ---------------------------------------------------------------------------
def find_soffice():
    names = ["soffice.exe", "soffice.com"] if os.name == "nt" else ["soffice", "libreoffice"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    candidates = []
    if os.name == "nt":
        for base in [os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")]:
            if base:
                candidates.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for key in (r"SOFTWARE\LibreOffice\UNO\InstallPath", r"SOFTWARE\WOW6432Node\LibreOffice\UNO\InstallPath"):
                    try:
                        with winreg.OpenKey(root, key) as k:
                            v, _ = winreg.QueryValueEx(k, "")
                            candidates.append(os.path.join(v, "soffice.exe"))
                    except OSError:
                        pass
        except ImportError:
            pass
    else:
        candidates += ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                       "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def image_kind(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:2] == b"\xff\xd8":
        return "jpg"
    if b[:4] in (b"GIF8",) or b[:2] == b"BM" or b[:4] in (b"II*\x00", b"MM\x00*") or b[8:12] == b"WEBP":
        return "raster"
    if b[:4] == b"\xd7\xcd\xc6\x9a" or b[:4] in (b"\x01\x00\x09\x00", b"\x02\x00\x09\x00"):
        return "wmf"
    if len(b) > 44 and b[40:44] == b" EMF":
        return "emf"
    if b[:6] == b"VCLMTF":
        return "svm"
    return "unknown"


def rasterize_metafiles(doc, tmp):
    """WMF/EMF clip art (common in Publisher files) -> PNG via LibreOffice."""
    jobs = []
    for p in doc.pages:
        for it in p.items:
            if it.kind == "image":
                k = image_kind(it.image)
                if k in ("wmf", "emf", "svm"):
                    jobs.append((it, k))
    if not jobs:
        return
    mdir = os.path.join(tmp, "meta")
    os.makedirs(mdir, exist_ok=True)
    left = []
    for it, k in jobs:
        width = int(min(max(abs(it.w) * 4, 200), 2400))
        height = max(int(width * abs(it.h) / max(abs(it.w), 1)), 1)
        png = None
        if k in ("wmf", "emf"):
            png = metafile_to_png_native(it.image, k, width, height, mdir)
        if png:
            it.image = png
            it.image_name = "clipart.png"
        else:
            left.append((it, k))
    jobs = left
    if not jobs or not find_soffice():
        return
    srcs = []
    for n, (it, k) in enumerate(jobs):
        src = os.path.join(mdir, f"img{n}.{k}")
        with open(src, "wb") as f:
            f.write(it.image)
        srcs.append(src)
    # one LibreOffice start for every picture (each start takes several seconds on Windows)
    try:
        convert_many(srcs, "svg", mdir, timeout=180)
    except ImportError_:
        pass
    for n, (it, k) in enumerate(jobs):
        width = int(min(max(abs(it.w) * 4, 200), 2400))
        svg = os.path.splitext(srcs[n])[0] + ".svg"
        png = _render_svg(svg, width, abs(it.h) / max(abs(it.w), 1)) if os.path.exists(svg) else None
        if png is None:
            try:
                fmt = 'png:draw_png_Export:{"PixelWidth":{"type":"long","value":"%d"}}' % width
                out = convert(srcs[n], fmt, mdir, timeout=120)
                with open(out, "rb") as f:
                    png = f.read()
            except (ImportError_, OSError):
                png = None
        if png:
            it.image = png
            it.image_name = f"clipart{n + 1}.png"


def _render_svg(svg, width, aspect):
    """Render an SVG made from a metafile so transparency is kept. Returns PNG bytes or None."""
    try:
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice
    except ImportError:
        return None
    r = QSvgRenderer(svg)
    if not r.isValid():
        return None
    img = QImage(width, max(int(width * aspect), 1), QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def convert_many(srcs, fmt, outdir, timeout=240):
    """Convert several files in one LibreOffice run."""
    if not srcs:
        return
    soffice = find_soffice()
    if not soffice:
        raise ImportError_("LibreOffice was not found.")
    profile = tempfile.mkdtemp(prefix="pubdesign_lo_")
    try:
        import pathlib
        cmd = [soffice, f"-env:UserInstallation={pathlib.Path(profile).as_uri()}", "--headless", "--norestore",
               "--convert-to", fmt, "--outdir", outdir] + list(srcs)
        _run(cmd, timeout)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _run(cmd, timeout):
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        raise ImportError_("LibreOffice took too long to read this file. Try File ▸ Open ▸ Open a Publisher "
                           "file as pictures, or open it again.")


def convert(src, fmt, outdir, timeout=240):
    soffice = find_soffice()
    if not soffice:
        raise ImportError_("LibreOffice is needed to open Publisher files but was not found.\n"
                           "Install it free from https://www.libreoffice.org (or run install.bat again).")
    profile = tempfile.mkdtemp(prefix="pubdesign_lo_")
    try:
        import pathlib
        prof_url = pathlib.Path(profile).as_uri()
        cmd = [soffice, f"-env:UserInstallation={prof_url}", "--headless", "--norestore",
               "--convert-to", fmt, "--outdir", outdir, src]
        _run(cmd, timeout)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    base = os.path.splitext(os.path.basename(src))[0]
    ext = fmt.split(":")[0]
    out = os.path.join(outdir, base + "." + ext)
    if not os.path.exists(out):
        raise ImportError_("LibreOffice could not read this file. It may be damaged or from an unsupported Publisher version.")
    return out


# ---------------------------------------------------------------------------
# units / colours
# ---------------------------------------------------------------------------
_UNITS = {"cm": 72 / 2.54, "mm": 72 / 25.4, "in": 72.0, "pt": 1.0, "pc": 12.0, "px": 0.75}


def length(v, default=0.0):
    if v is None:
        return default
    m = re.match(r"\s*(-?[\d.]+(?:e-?\d+)?)\s*([a-z%]*)", v)
    if not m:
        return default
    num, unit = float(m.group(1)), m.group(2) or "pt"
    return num * _UNITS.get(unit, 1.0)


def color(v):
    if not v or not v.startswith("#") or len(v) != 7:
        return None
    return (int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16))


# ---------------------------------------------------------------------------
# SVG path helpers (for ellipse detection and path items)
# ---------------------------------------------------------------------------
_TOK = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def path_points(d, steps=8):
    """Approximate an SVG path with a list of polylines (list of (x,y) lists)."""
    toks = _TOK.findall(d or "")
    i = 0
    cmd = None
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    polys = []
    poly = []
    last_ctrl = None

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        t = toks[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if poly:
                    poly.append(start)
                    polys.append(poly)
                    poly = []
                cur = start
                continue
        if cmd is None:
            i += 1
            continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        try:
            if c == "M":
                x, y = num() + ox, num() + oy
                if poly:
                    polys.append(poly)
                poly = [(x, y)]
                cur = start = (x, y)
                cmd = "l" if rel else "L"
            elif c == "L":
                x, y = num() + ox, num() + oy
                poly.append((x, y))
                cur = (x, y)
            elif c == "H":
                x = num() + (cur[0] if rel else 0)
                cur = (x, cur[1])
                poly.append(cur)
            elif c == "V":
                y = num() + (cur[1] if rel else 0)
                cur = (cur[0], y)
                poly.append(cur)
            elif c in "CSQT":
                if c == "C":
                    p1 = (num() + ox, num() + oy)
                    p2 = (num() + ox, num() + oy)
                elif c == "S":
                    p1 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_ctrl else cur
                    p2 = (num() + ox, num() + oy)
                elif c == "Q":
                    p1 = p2 = (num() + ox, num() + oy)
                else:
                    p1 = p2 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_ctrl else cur
                end = (num() + ox, num() + oy)
                p0 = cur
                for k in range(1, steps + 1):
                    tt = k / steps
                    a = (1 - tt) ** 3
                    b = 3 * (1 - tt) ** 2 * tt
                    cc = 3 * (1 - tt) * tt ** 2
                    dd = tt ** 3
                    poly.append((a * p0[0] + b * p1[0] + cc * p2[0] + dd * end[0],
                                 a * p0[1] + b * p1[1] + cc * p2[1] + dd * end[1]))
                last_ctrl = p2
                cur = end
                continue
            elif c == "A":
                rx, ry, rot, large, sweep = num(), num(), num(), num(), num()
                end = (num() + ox, num() + oy)
                for k in range(1, steps + 1):
                    tt = k / steps
                    poly.append((cur[0] + (end[0] - cur[0]) * tt, cur[1] + (end[1] - cur[1]) * tt))
                cur = end
            else:
                i += 1
        except (IndexError, ValueError):
            break
        last_ctrl = None
    if poly:
        polys.append(poly)
    return polys


def looks_like_ellipse(polys, vw, vh):
    polys = [p for p in polys if len(p) > 2]
    pts = [p for poly in polys for p in poly]
    if len(polys) != 1 or len(pts) < 12 or vw <= 0 or vh <= 0:
        return False
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    if maxx - minx < vw * 0.9 or maxy - miny < vh * 0.9:
        return False
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    rx, ry = (maxx - minx) / 2, (maxy - miny) / 2
    for x, y in pts:
        r = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
        if abs(r - 1) > 0.08:
            return False
    return True


def is_axis_rect(points, vw, vh):
    if len(points) not in (4, 5):
        return False
    xs = sorted(set(round(p[0]) for p in points))
    ys = sorted(set(round(p[1]) for p in points))
    return len(xs) == 2 and len(ys) == 2


# ---------------------------------------------------------------------------
# FODG parser
# ---------------------------------------------------------------------------
class FodgReader:
    def __init__(self, path):
        self.tree = ET.parse(path)
        self.root = self.tree.getroot()
        self.styles = {}
        for container in (self.root.find(q("office:styles")), self.root.find(q("office:automatic-styles"))):
            if container is None:
                continue
            for st in container.findall(q("style:style")):
                self.styles[(st.get(q("style:family")), st.get(q("style:name")))] = st
        self.fill_images = {}
        offstyles = self.root.find(q("office:styles"))
        if offstyles is not None:
            for fi in offstyles.findall(q("draw:fill-image")):
                bd = fi.find(q("office:binary-data"))
                if bd is not None and bd.text:
                    self.fill_images[fi.get(q("draw:name"))] = base64.b64decode(bd.text)
        self.fonts = {}
        ffd = self.root.find(q("office:font-face-decls"))
        if ffd is not None:
            for ff in ffd.findall(q("style:font-face")):
                fam = (ff.get(q("svg:font-family")) or ff.get(q("style:name")) or "").strip("'\"")
                self.fonts[ff.get(q("style:name"))] = fam

    # ---- style lookup with inheritance ----
    def prop(self, family, name, element, attr, default=None):
        seen = 0
        while name and seen < 20:
            st = self.styles.get((family, name))
            if st is None:
                break
            el = st.find(q(element))
            if el is not None and el.get(q(attr)) is not None:
                return el.get(q(attr))
            name = st.get(q("style:parent-style-name"))
            seen += 1
        return default

    def page_size(self):
        ms = self.root.find(q("office:master-styles"))
        auto = self.root.find(q("office:automatic-styles"))
        for pl in auto.findall(q("style:page-layout")) if auto is not None else []:
            p = pl.find(q("style:page-layout-properties"))
            if p is not None and p.get(q("fo:page-width")):
                return length(p.get(q("fo:page-width"))), length(p.get(q("fo:page-height")))
        return 612.0, 792.0

    # ---- text ----
    def text_run_style(self, name, base):
        r = Run("", **base)
        fam = self.prop("text", name, "style:text-properties", "style:font-name")
        if fam:
            r.font = self.fonts.get(fam, fam)
        sz = self.prop("text", name, "style:text-properties", "fo:font-size")
        if sz and not sz.endswith("%"):
            r.size = round(length(sz), 1)
        if self.prop("text", name, "style:text-properties", "fo:font-weight") in ("bold", "700", "800", "900"):
            r.bold = True
        if self.prop("text", name, "style:text-properties", "fo:font-style") == "italic":
            r.italic = True
        ul = self.prop("text", name, "style:text-properties", "style:text-underline-style")
        if ul and ul != "none":
            r.underline = True
        c = color(self.prop("text", name, "style:text-properties", "fo:color"))
        if c:
            r.color = c
        return r

    def para_runs(self, p, base):
        runs = []

        def plain(t):
            # ODF: raw whitespace (spaces, tabs, line ends) in text collapses to one space;
            # real spaces, tabs and line breaks come as <text:s>, <text:tab>, <text:line-break>
            return re.sub(r"[ \t\r\n]+", " ", t)

        def walk(el, style_name):
            if el.text:
                add(plain(el.text), style_name)
            for ch in el:
                tag = ch.tag
                if tag == q("text:span"):
                    walk(ch, ch.get(q("text:style-name")) or style_name)
                elif tag == q("text:s"):
                    add(" " * int(ch.get(q("text:c")) or 1), style_name)
                elif tag == q("text:tab"):
                    add("\t", style_name)
                elif tag == q("text:line-break"):
                    add("\n", style_name)
                elif tag in (q("text:a"),):
                    walk(ch, style_name)
                else:
                    walk(ch, style_name)
                if ch.tail:
                    add(plain(ch.tail), style_name)

        def add(t, style_name):
            proto = self.text_run_style(style_name, base) if style_name else Run("", **base)
            if runs and (runs[-1].font, runs[-1].size, runs[-1].bold, runs[-1].italic, runs[-1].underline,
                         runs[-1].color) == (proto.font, proto.size, proto.bold, proto.italic, proto.underline, proto.color):
                runs[-1].text += t
            else:
                proto.text = t
                runs.append(proto)

        walk(p, None)
        # trailing space that LibreOffice/libmspub appends to each paragraph
        if runs and runs[-1].text.endswith(" "):
            runs[-1].text = runs[-1].text[:-1]
            if not runs[-1].text and len(runs) > 1:
                runs.pop()
        return runs

    def paragraphs(self, container):
        paras = []
        for p in container.iter():
            if p.tag not in (q("text:p"), q("text:h")):
                continue
            pst = p.get(q("text:style-name"))
            align = self.prop("paragraph", pst, "style:paragraph-properties", "fo:text-align") or "start"
            align = {"start": "left", "end": "right", "center": "center", "justify": "justify",
                     "left": "left", "right": "right"}.get(align, "left")
            base = {}
            tst = self.text_run_style(pst, {}) if pst else Run("")
            base = dict(font=tst.font, size=tst.size, bold=tst.bold, italic=tst.italic,
                        underline=tst.underline, color=tst.color)
            runs = self.para_runs(p, base)
            if not runs:
                runs = [Run("", **base)]
            paras.append(Para(runs, align))
        return paras

    # ---- graphics ----
    def gstyle(self, el):
        name = el.get(q("draw:style-name"))
        g = lambda a: self.prop("graphic", name, "style:graphic-properties", a)
        fill = None
        if g("draw:fill") == "solid":
            fill = color(g("draw:fill-color")) or (114, 159, 207)
        elif g("draw:fill") == "gradient":
            fill = (200, 200, 200)
        stroke = None
        sw = 1.0
        if (g("draw:stroke") or "solid") != "none":
            stroke = color(g("svg:stroke-color")) or (0, 0, 0)
            sw = max(length(g("svg:stroke-width")), 0.5)
        img = None
        if g("draw:fill") == "bitmap":
            img = self.fill_images.get(g("draw:fill-image-name"))
        valign = {"middle": "middle", "bottom": "bottom"}.get(g("draw:textarea-vertical-align") or "", "top")
        return fill, stroke, sw, img, valign

    def geom(self, el):
        x = length(el.get(q("svg:x")))
        y = length(el.get(q("svg:y")))
        w = length(el.get(q("svg:width")))
        h = length(el.get(q("svg:height")))
        rot = 0.0
        tr = el.get(q("draw:transform"))
        if tr:
            m = re.search(r"rotate\s*\(\s*(-?[\d.eE-]+)\s*\)", tr)
            t = re.search(r"translate\s*\(\s*(-?[\d.]+[a-z]*)\s+(-?[\d.]+[a-z]*)\s*\)", tr)
            a = float(m.group(1)) if m else 0.0
            tx, ty = (length(t.group(1)), length(t.group(2))) if t else (x, y)
            # ODF: rotate about the shape origin, then translate
            cxl, cyl = w / 2, h / 2
            rcx = cxl * math.cos(a) + cyl * math.sin(a)
            rcy = -cxl * math.sin(a) + cyl * math.cos(a)
            cx, cy = tx + rcx, ty + rcy
            x, y = cx - w / 2, cy - h / 2
            rot = -math.degrees(a)
        return x, y, w, h, rot

    def shape_text(self, el):
        paras = self.paragraphs(el)
        if any(p.text.strip() for p in paras):
            return paras
        return None

    def convert_element(self, el, out):
        tag = el.tag
        if tag == q("draw:g"):
            kids = []
            for ch in el:
                self.convert_element(ch, kids)
            out.extend(merge_fill_outline(kids))
            return
        if tag == q("draw:frame"):
            x, y, w, h, rot = self.geom(el)
            fill, stroke, sw, _, valign = self.gstyle(el)
            tb = el.find(q("draw:text-box"))
            im = el.find(q("draw:image"))
            tbl = el.find(q("table:table"))
            if tbl is not None:
                # a table frame also carries a preview picture of the table; use the real cells
                self.convert_table(tbl, x, y, w, h, out)
            elif tb is not None:
                out.append(Item(kind="text", x=x, y=y, w=w, h=h, rotation=rot, fill=fill, stroke=stroke,
                                stroke_width=sw, paras=self.paragraphs(tb), valign=valign))
            elif im is not None:
                data = None
                bd = im.find(q("office:binary-data"))
                if bd is not None and bd.text:
                    data = base64.b64decode(bd.text)
                if data:
                    out.append(Item(kind="image", x=x, y=y, w=w, h=h, rotation=rot, image=data, image_name="picture"))
            return
        if tag in (q("draw:polygon"), q("draw:polyline"), q("draw:path"), q("draw:rect"),
                   q("draw:ellipse"), q("draw:circle"), q("draw:custom-shape")):
            x, y, w, h, rot = self.geom(el)
            fill, stroke, sw, img, valign = self.gstyle(el)
            vb = (el.get(q("svg:viewBox")) or "0 0 1 1").split()
            vw, vh = float(vb[2]) or 1, float(vb[3]) or 1
            kind = "path"
            d = None
            if tag == q("draw:rect"):
                kind = "rect"
            elif tag in (q("draw:ellipse"), q("draw:circle")):
                kind = "ellipse"
            elif tag == q("draw:custom-shape"):
                eg = el.find(q("draw:enhanced-geometry"))
                t = eg.get(q("draw:type")) if eg is not None else ""
                kind = "ellipse" if t in ("ellipse", "circle") else "rect"
            elif tag in (q("draw:polygon"), q("draw:polyline")):
                pts = []
                for pair in (el.get(q("draw:points")) or "").split():
                    a, b = pair.split(",")
                    pts.append((float(a), float(b)))
                if tag == q("draw:polygon") and is_axis_rect(pts, vw, vh):
                    kind = "rect"
                else:
                    d = "M " + " L ".join(f"{a} {b}" for a, b in pts) + (" Z" if tag == q("draw:polygon") else "")
            else:
                d = el.get(q("svg:d"))
                if looks_like_ellipse(path_points(d), vw, vh):
                    kind = "ellipse"
            if img:
                out.append(Item(kind="image", x=x, y=y, w=w, h=h, rotation=rot, image=img, image_name="picture",
                                stroke=stroke, stroke_width=sw))
            else:
                it = Item(kind=kind, x=x, y=y, w=w, h=h, rotation=rot, fill=fill, stroke=stroke, stroke_width=sw)
                if kind == "path":
                    it.path_d = d
                    it.view = (0, 0, vw, vh)
                    if tag == q("draw:polyline"):
                        it.fill = None
                if fill is not None or stroke is not None:
                    out.append(it)
            paras = self.shape_text(el)
            if paras:
                out.append(Item(kind="text", x=x, y=y, w=w, h=h, rotation=rot, paras=paras, valign=valign))
            return
        if tag == q("draw:line"):
            x1, y1 = length(el.get(q("svg:x1"))), length(el.get(q("svg:y1")))
            x2, y2 = length(el.get(q("svg:x2"))), length(el.get(q("svg:y2")))
            _, stroke, sw, _, _ = self.gstyle(el)
            out.append(Item(kind="line", x=x1, y=y1, w=x2 - x1, h=y2 - y1, stroke=stroke or (0, 0, 0), stroke_width=sw))
            return

    def convert_table(self, tbl, x, y, w, h, out):
        cols = []
        for c in tbl.findall(q("table:table-column")):
            st = c.get(q("table:style-name"))
            cw = length(self.prop("table-column", st, "style:table-column-properties", "style:column-width"))
            rep = int(c.get(q("table:number-columns-repeated")) or 1)
            cols += [cw] * rep
        rows = tbl.findall(".//" + q("table:table-row"))
        if not rows:
            return
        if not cols or sum(cols) <= 0:
            n = max(len(r.findall(q("table:table-cell"))) for r in rows)
            cols = [w / max(n, 1)] * n
        heights = []
        for r in rows:
            st = r.get(q("table:style-name"))
            rh = length(self.prop("table-row", st, "style:table-row-properties", "style:row-height")) or \
                length(self.prop("table-row", st, "style:table-row-properties", "style:min-row-height"))
            heights.append(rh)
        known = sum(hh for hh in heights if hh)
        unknown = [i for i, hh in enumerate(heights) if not hh]
        for i in unknown:
            heights[i] = max((h - known) / len(unknown), 14)
        yy = y
        for r, rh in zip(rows, heights):
            xx = x
            ci = 0
            row_default = r.get(q("table:default-cell-style-name"))
            for cell in r:
                if cell.tag not in (q("table:table-cell"), q("table:covered-table-cell")):
                    continue
                span = int(cell.get(q("table:number-columns-spanned")) or 1)
                cw = sum(cols[ci:ci + span]) if ci < len(cols) else 50
                if cell.tag == q("table:table-cell"):
                    st = cell.get(q("table:style-name")) or row_default
                    bg, stroke, sw = self.cell_look(st)
                    out.append(Item(kind="text", x=xx, y=yy, w=cw, h=rh, fill=bg, stroke=stroke, stroke_width=sw,
                                    paras=self.paragraphs(cell) or [Para([Run("")])]))
                xx += cw
                ci += span
            yy += rh

    def cell_look(self, st):
        """Background and border of a table cell (no border unless the file has one)."""
        bg = None
        for el in ("style:table-cell-properties", "loext:graphic-properties"):
            fc = self.prop("table-cell", st, el, "fo:background-color")
            if fc and fc != "transparent":
                bg = color(fc)
                break
            if self.prop("table-cell", st, el, "draw:fill") == "solid":
                bg = color(self.prop("table-cell", st, el, "draw:fill-color"))
                break
        stroke, sw = None, 1.0
        for side in ("fo:border", "fo:border-top", "fo:border-left", "fo:border-bottom", "fo:border-right"):
            b = self.prop("table-cell", st, "style:table-cell-properties", side)
            if b and b != "none":
                parts = b.split()
                w = length(parts[0]) if parts else 0.75
                if w > 0:
                    stroke = color(parts[-1]) or (0, 0, 0)
                    sw = max(w, 0.5)
                    break
        return bg, stroke, sw

    def document(self):
        pw, ph = self.page_size()
        doc = Document(width=pw, height=ph, pages=[])
        body = self.root.find(q("office:body")).find(q("office:drawing"))
        for pg in body.findall(q("draw:page")):
            items = []
            for el in pg:
                self.convert_element(el, items)
            doc.pages.append(Page(items=items))
        if not doc.pages:
            doc.pages.append(Page())
        return doc


def _geom_key(it):
    return (it.kind, round(it.x, 1), round(it.y, 1), round(it.w, 1), round(it.h, 1), getattr(it, "path_d", None))


def merge_fill_outline(items):
    """libmspub draws a filled shape and its outline as two shapes; merge them."""
    out = []
    for it in items:
        if out and it.kind in ("rect", "ellipse", "path") and out[-1].kind == it.kind:
            prev = out[-1]
            close = abs(prev.x - it.x) < 1.5 and abs(prev.y - it.y) < 1.5 and abs(prev.w - it.w) < 3 and abs(prev.h - it.h) < 3
            if close and prev.stroke is None and it.fill is None and it.stroke is not None:
                prev.stroke, prev.stroke_width = it.stroke, it.stroke_width
                continue
        out.append(it)
    return out


def can_import():
    """True when a Publisher-made file can be opened (bundled reader or LibreOffice)."""
    return bool(find_pubconv() or find_soffice())


def import_pub(path, mode="editable"):
    tmp = tempfile.mkdtemp(prefix="pubdesign_imp_")
    try:
        # work on a copy with a plain name (odd characters in names upset the converters)
        src = os.path.join(tmp, "input" + os.path.splitext(path)[1].lower())
        shutil.copyfile(path, src)
        if mode == "pictures":
            if not find_soffice():
                raise ImportError_("Opening a Publisher file as pictures needs LibreOffice (free). Use File ▸ Open "
                                   "to open it normally, or install LibreOffice from https://www.libreoffice.org.")
            pdf = convert(src, "pdf", tmp)
            return pdf_to_picture_doc(pdf)
        fodg = pubconv_to_fodg(src, tmp)            # bundled Publisher reader
        if fodg is None:
            if not find_soffice():
                raise ImportError_("PubDesign couldn't read this Publisher file. It may be damaged or made in a "
                                   "very old version of Publisher (97 or earlier).")
            fodg = convert(src, "fodg", tmp)        # LibreOffice, if it happens to be installed
        doc = FodgReader(fodg).document()
        rasterize_metafiles(doc, tmp)
        return doc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pdf_to_picture_doc(pdf_path, dpi=200):
    """Each PDF page becomes a full-page picture (uses Qt's PDF module)."""
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtCore import QSize, QBuffer, QByteArray, QIODevice
    pdoc = QPdfDocument()
    pdoc.load(pdf_path)
    if pdoc.pageCount() == 0:
        raise ImportError_("Could not render this file.")
    sz = pdoc.pagePointSize(0)
    doc = Document(width=sz.width(), height=sz.height(), pages=[])
    for i in range(pdoc.pageCount()):
        ps = pdoc.pagePointSize(i)
        img = pdoc.render(i, QSize(int(ps.width() * dpi / 72), int(ps.height() * dpi / 72)))
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        doc.pages.append(Page(items=[Item(kind="image", x=0, y=0, w=ps.width(), h=ps.height(),
                                          image=bytes(ba), image_name=f"page{i + 1}.png")]))
    pdoc.close()
    return doc
