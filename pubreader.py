"""Native reader for Publisher 2002+ (.pub) files.

Reads pages, text boxes (with character and paragraph formatting), AutoShapes,
lines and pictures straight from the file. Used for files PubDesign wrote;
other Publisher files can also be read, with LibreOffice as the fallback for
features this reader does not cover (tables, groups, WordArt...).
"""
import struct

import olefile

from pubblocks import parse_record, Block
import escher
import quill
import fkp
from pubmodel import Document, Page, Item, Para, Run, EMU_PER_PT

DUMMY_PAGE_SEQS = {0x10D, 0x110, 0x113, 0x117}


class Unsupported(Exception):
    """The file uses things this reader does not handle; use the LibreOffice path."""


def s32(v):
    return v - (1 << 32) if v >= (1 << 31) else v


def is_own_file(path):
    try:
        o = olefile.OleFileIO(path)
        try:
            props = o.getproperties("\x05SummaryInformation", convert_time=True)
        finally:
            o.close()
        app = props.get(18)
        if isinstance(app, bytes):
            app = app.decode("cp1252", "replace")
        return isinstance(app, str) and app.startswith(("PubDesign", "Page" "craft"))
    except Exception:
        return False


class PubReader:
    def __init__(self, path):
        self.ole = olefile.OleFileIO(path)
        c = self.ole.openstream("Contents").read()
        if c[:2] != b"\xe8\xac" or c[2] != 0x2C:
            raise Unsupported("not a Publisher 2002+ file")
        self.contents = c
        toff = struct.unpack_from("<I", c, 0x1A)[0]
        tblocks, _ = parse_record(c, toff)
        directory = [b for b in tblocks if b.type == 0x90][0]
        self.chunks = {}
        for seq, e in enumerate(directory.value):
            if e.type == 0x88 and e.get(0x04) is not None:
                try:
                    blocks, _ = parse_record(c, e.get(0x04))
                except Exception:
                    blocks = []
                self.chunks[seq] = (e.get(0x02), e.get(0x05), blocks)
        self.palette = self._palette()

    def close(self):
        self.ole.close()

    # ---------------------------------------------------------------- colours
    def _palette(self):
        out = []
        for seq, (t, parent, blocks) in sorted(self.chunks.items()):
            if t != 0x5C:
                continue
            for b in blocks:
                if b.type == 0xA0:
                    for sub in b.value:
                        if sub.type == 0x88:
                            v = sub.get(0x01, 0)
                            out.append((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))
                        elif sub.type == 0x78:
                            out.append((0, 0, 0))
        return out

    def color(self, v):
        if v is None:
            return None
        v &= 0xFFFFFFFF
        kind = v >> 24
        if kind == 0x08:
            i = v & 0xFFFFFF
            if i < len(self.palette):
                return self.palette[i]
            return (0, 0, 0)
        if kind == 0:
            return (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
        return (128, 128, 128)

    # ---------------------------------------------------------------- text
    def stories(self):
        if not self.ole.exists("Quill/QuillSub/CONTENTS"):
            return {}
        q = self.ole.openstream("Quill/QuillSub/CONTENTS").read()
        _, _, chunks = quill.parse(q)
        m = {}
        for c, off in chunks:
            m.setdefault(c.name, []).append((c, off))
        text_chunk, text_off = m["TEXT"][0]
        text = text_chunk.data.decode("utf-16-le", "replace")
        d = m["STRS"][0][0].data
        n = struct.unpack_from("<I", d, 0)[0]
        hdr = struct.unpack_from("<I", d, 4)[0]
        lengths = list(struct.unpack_from(f"<{n}I", d, 4 + hdr))
        sy = m["SYID"][0][0].data
        ns = struct.unpack_from("<I", sy, 4)[0]
        ids = list(struct.unpack_from(f"<{ns}I", sy, 8))
        fonts = self._fonts(m["FONT"][0][0].data) if "FONT" in m else []
        colors = self._quill_colors(m["PL  "][0][0].data) if "PL  " in m else []

        def runs_of(name):
            out = []
            for c, _ in sorted(m.get(name, []), key=lambda x: x[0].id):
                _, runs = fkp.parse_fkp(c.data)
                for end, _, props in runs:
                    out.append(((end - text_off) // 2, props))
            return out

        cruns = runs_of("FDPC")
        pruns = runs_of("FDPP")

        def props_at(runs, i):
            for end, props in runs:
                if i < end:
                    return props
            return runs[-1][1] if runs else []

        result = {}
        pos = 0
        for tid, ln in zip(ids, lengths):
            seg = text[pos:pos + ln]
            paras = []
            cur_runs = []
            start = pos
            k = 0
            while k < len(seg):
                ch = seg[k]
                gi = pos + k
                if ch == "\r":
                    pprops = props_at(pruns, gi)
                    if not cur_runs:
                        cur_runs = [self._run("", props_at(cruns, gi), fonts, colors)]
                    paras.append(Para(cur_runs, self._align(pprops)))
                    cur_runs = []
                    k += 1
                    continue
                cprops = props_at(cruns, gi)
                r = self._run(ch.replace("\x0b", "\n"), cprops, fonts, colors)
                if cur_runs and _same_fmt(cur_runs[-1], r):
                    cur_runs[-1].text += r.text
                else:
                    cur_runs.append(r)
                k += 1
            if cur_runs:
                paras.append(Para(cur_runs, self._align(props_at(pruns, pos + len(seg) - 1))))
            result[tid] = paras or [Para([Run("")])]
            pos += ln
        return result

    @staticmethod
    def _fonts(d):
        n = struct.unpack_from("<I", d, 4)[0]
        offs = struct.unpack_from(f"<{n}I", d, 20)
        out = []
        for o in offs:
            p = 20 + o
            nl = struct.unpack_from("<H", d, p)[0]
            out.append(d[p + 2:p + 2 + nl * 2].decode("utf-16-le", "replace"))
        return out

    def _quill_colors(self, d):
        n = struct.unpack_from("<I", d, 0)[0]
        pos = 12
        out = []
        for _ in range(n):
            ln = struct.unpack_from("<I", d, pos)[0]
            blocks, _ = parse_record(d, pos)
            v = None
            for b in blocks:
                if b.id == 0x01:
                    v = b.value
            out.append(self.color(v) if v is not None else (0, 0, 0))
            pos += ln
        return out

    def _run(self, text, props, fonts, colors):
        r = Run(text, font="Times New Roman", size=10.0)
        for b in props:
            if b.id == 0x02:
                r.bold = True
            elif b.id == 0x03:
                r.italic = True
            elif b.id == 0x0C and isinstance(b.value, int):
                r.size = round(b.value / EMU_PER_PT, 2)
            elif b.id == 0x1E and isinstance(b.value, int):
                r.underline = (b.value & 0xFF) != 0
            elif b.id == 0x24 and b.is_container:
                for slot in b.value:
                    if slot.id == 0x00 and slot.is_container and slot.value:
                        fi = slot.value[0].value
                        if isinstance(fi, int) and fi < len(fonts):
                            r.font = fonts[fi]
            elif b.id == 0x44 and b.is_container:
                for sub in b.value:
                    if sub.id == 0x00 and isinstance(sub.value, int) and sub.value < len(colors):
                        r.color = colors[sub.value]
            elif b.id == 0x2E and isinstance(b.value, int) and b.value < len(colors):
                r.color = colors[b.value]
        return r

    @staticmethod
    def _align(props):
        for b in props:
            if b.id == 0x04 and isinstance(b.value, int):
                return {0: "left", 1: "right", 2: "center", 6: "justify"}.get(b.value & 0xFF, "left")
        return "left"

    # ---------------------------------------------------------------- shapes
    def escher_shapes(self):
        recs = escher.parse(self.ole.openstream("Escher/EscherStm").read())
        blips = self._blips(recs)
        out = {}

        def walk(x, depth):
            for ch in x.children or []:
                if ch.type == 0xF003 and depth > 1:
                    raise Unsupported("grouped shapes")
                if ch.type == 0xF004:
                    cd = ch.find(0xF011)
                    if cd is None:
                        continue
                    seq = dict(escher.client_values(cd)).get(0x6801)
                    fsp = ch.find(0xF00A)
                    fo = ch.find(0xF00B)
                    anchor = ch.find(0xF010)
                    if anchor is None:
                        if ch.find(0xF00F) is not None:
                            raise Unsupported("grouped shapes")
                        continue
                    props = dict(escher.fopt_props(fo)[0]) if fo else {}
                    av = dict(escher.client_values(anchor))
                    flags = struct.unpack_from("<I", fsp.data, 4)[0] if fsp else 0
                    out[seq] = dict(spt=fsp.inst if fsp else 1, flags=flags, props=props,
                                    anchor=(s32(av.get(0x2001, 0)), s32(av.get(0x2002, 0)),
                                            s32(av.get(0x2003, 0)), s32(av.get(0x2004, 0))),
                                    blips=blips)
                if ch.is_container:
                    walk(ch, depth + (1 if ch.type == 0xF003 else 0))

        for r in recs:
            if r.type == 0xF002:
                walk(r, 0)
        return out

    def _blips(self, recs):
        dgg = recs[0] if recs and recs[0].type == 0xF000 else None
        bs = dgg.find(0xF001) if dgg else None
        delay = self.ole.openstream("Escher/EscherDelayStm").read() if self.ole.exists("Escher/EscherDelayStm") else b""
        out = []
        for f in (bs.children if bs else []):
            fo = struct.unpack_from("<I", f.data, 28)[0]
            size = struct.unpack_from("<I", f.data, 20)[0]
            data = None
            if fo + 8 <= len(delay):
                vi, typ, ln = struct.unpack_from("<HHI", delay, fo)
                inst = vi >> 4
                body = delay[fo + 8:fo + 8 + ln]
                one_uid = {0xF01E: 0x6E0, 0xF01D: 0x46A, 0xF02A: 0x46A}.get(typ)
                if typ in (0xF01E, 0xF01D, 0xF02A, 0xF01F, 0xF029):
                    skip = 17 if inst in (0x6E0, 0x46A, 0x6E2, 0x7A8, 0x6E4) else 33
                    data = body[skip:]
            out.append(data)
        return out

    # ---------------------------------------------------------------- document
    def document(self):
        doc_chunk = next((b for t, p, b in self.chunks.values() if t == 0x44), None)
        if doc_chunk is None:
            raise Unsupported("no document chunk")
        W = H = None
        page_seqs = []
        for b in doc_chunk:
            if b.id == 0x12 and b.is_container:
                W = b.get(0x01)
                H = b.get(0x02)
            elif b.id == 0x02 and b.type == 0xA0:
                page_seqs = [x.value for x in b.value]
        if not W or not H:
            raise Unsupported("no page size")
        doc = Document(width=W / EMU_PER_PT, height=H / EMU_PER_PT, pages=[])
        doc.unit = "in"
        doc.margin = 36
        for t, parent, blocks in self.chunks.values():
            if t == 0x4C:
                for b in blocks:
                    if b.id == 0x02 and b.type == 0xA0 and b.value and b.value[0].is_container:
                        v = b.value[0].get(0x01)
                        if isinstance(v, int) and 0 <= v < W / 2:
                            doc.margin = round(v / EMU_PER_PT, 2)
                break
        stories = self.stories()
        shapes = self.escher_shapes()
        cx, cy = W / 2, H / 2
        for ps in page_seqs:
            if ps in DUMMY_PAGE_SEQS or ps not in self.chunks:
                continue
            t, parent, pblocks = self.chunks[ps]
            master = False
            shape_list = []
            for b in pblocks:
                if b.id == 0x0E and b.type == 0xC0 and any(b.value[:-2]):
                    master = True
                if b.id == 0x02 and b.type == 0xA0:
                    shape_list = [x.value for x in b.value]
            if master:
                continue
            items = []
            for sseq in shape_list:
                if sseq not in self.chunks:
                    continue
                ctype, _, cblocks = self.chunks[sseq]
                if ctype in (0x10, 0x30, 0x31):
                    raise Unsupported("tables or groups")
                es = shapes.get(sseq)
                if es is None:
                    continue
                items.extend(self._item(es, cblocks, stories, cx, cy))
            doc.pages.append(Page(items=items))
        if not doc.pages:
            doc.pages.append(Page())
        return doc

    def _item(self, es, cblocks, stories, cx, cy):
        p = es["props"]
        spt = es["spt"]
        xs, ys, xe, ye = es["anchor"]
        rot = 0.0
        if 0x0004 in p:
            rot = (s32(p[0x0004]) / 65536.0) % 360
        x, y, w, h = (xs + cx) / EMU_PER_PT, (ys + cy) / EMU_PER_PT, (xe - xs) / EMU_PER_PT, (ye - ys) / EMU_PER_PT
        if (45 <= rot < 135) or (225 <= rot < 315):
            # Publisher stores the rotated bounding box for steep rotations
            mx, my = x + w / 2, y + h / 2
            w, h = h, w
            x, y = mx - w / 2, my - h / 2
        fill = None
        fb = p.get(0x01BF)
        filled = True if fb is None else bool((fb & 0x10) or not (fb & 0x100000))
        if filled and 0x0181 in p:
            fill = self.color(p[0x0181])
        if spt == 202 and fb is None:
            fill = None
        lb = p.get(0x01FF)
        has_line = True if lb is None else not ((lb & 0x80000) and not (lb & 0x8))
        stroke = self.color(p.get(0x01C0, 0x08000000 if spt != 202 else None)) if has_line and (0x01C0 in p or spt != 202) else None
        sw = p.get(0x01CB, 9525) / EMU_PER_PT
        if stroke is None:
            sw = 1.0
        valign = "top"
        tid = None
        for b in cblocks:
            if b.id == 0x35 and isinstance(b.value, int):
                valign = {1: "middle", 2: "bottom"}.get(b.value, "top")
            if b.id == 0x27 and isinstance(b.value, int):
                tid = b.value
        if tid is None and 0x0080 in p:
            tid = p[0x0080]
        out = []
        if spt == 20:
            flags = es["flags"]
            x1, x2 = (x + w, x) if flags & 0x40 else (x, x + w)
            y1, y2 = (y + h, y) if flags & 0x80 else (y, y + h)
            out.append(Item(kind="line", x=x1, y=y1, w=x2 - x1, h=y2 - y1, stroke=stroke or (0, 0, 0), stroke_width=sw))
            return out
        if 0x4104 in p or 0x0104 in p:
            idx = p.get(0x4104, p.get(0x0104))
            blips = es["blips"]
            data = blips[idx - 1] if 0 < idx <= len(blips) else None
            if data:
                out.append(Item(kind="image", x=x, y=y, w=w, h=h, rotation=rot, image=data,
                                image_name="picture.png" if data[:4] == b"\x89PNG" else "picture.jpg",
                                stroke=stroke, stroke_width=sw))
            return out
        if spt == 202:
            out.append(Item(kind="text", x=x, y=y, w=w, h=h, rotation=rot, fill=fill, stroke=stroke, stroke_width=sw,
                            paras=stories.get(tid, [Para([Run("")])]), valign=valign))
            return out
        kind, s = ("rect", 0) if spt == 1 else ("ellipse", 0) if spt == 3 else ("auto", spt)
        it = Item(kind=kind, x=x, y=y, w=w, h=h, rotation=rot, fill=fill, stroke=stroke, stroke_width=sw)
        it.spt = s
        out.append(it)
        if tid is not None and tid in stories:
            out.append(Item(kind="text", x=x, y=y, w=w, h=h, rotation=rot, paras=stories[tid], valign=valign))
        return out


def _same_fmt(a, b):
    return (a.font, a.size, a.bold, a.italic, a.underline, a.color) == (b.font, b.size, b.bold, b.italic, b.underline, b.color)


def read_pub(path):
    r = PubReader(path)
    try:
        return r.document()
    finally:
        r.close()
