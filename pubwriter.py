"""Microsoft Publisher (.pub, Publisher 2002+ format) writer.

Reverse-engineered from real Publisher files. It starts from a small
Publisher-made template (template.pub) and regenerates the parts that hold
pages, shapes, pictures and text.
"""
import hashlib
import json
import os
import struct

import olefile

from pubblocks import (Block, Raw, parse_record, parse_blocks, ser_record,
                       ser_blocks, u32, u16, flag, cont, ustr)
import escher
import quill
import fkp
from cfb import CFBWriter, property_set_stream
from pubmodel import Document, Item, Para, Run, EMU_PER_PT

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template.pub")
SHAPE_TPL = json.load(open(os.path.join(HERE, "shape_templates.json")))

CHUNK_SHAPE, CHUNK_ALTSHAPE, CHUNK_PAGE, CHUNK_DOC = 0x01, 0x20, 0x43, 0x44

# template seqnums (template.pub)
SEQ_DOC = 0x100
SEQ_MASTER = 0x107
SEQ_PAGE1 = 0x10A
SEQ_PAGE1_A, SEQ_PAGE1_B = 0x10B, 0x10C
SEQ_TEMPLATE_SHAPES = (0x125, 0x126)
SEQ_STORYMAP = 0x11B   # type 0x61
SEQ_STORYLIST = 0x11C  # type 0x65
SEQ_MARGINS = 0x121    # type 0x4c
SEQ_PAGESETUP = 0x124  # type 0x8a
DUMMY_PAGES = (0x10D, 0x110, 0x113, 0x117)

FONT_SLOTS = (0x00, 0x01, 0x02, 0x03, 0x04, 0x06, 0x07, 0x2C)


def emu(pt):
    return int(round(pt * EMU_PER_PT))


def s32(v):
    return v & 0xFFFFFFFF


def rgb_ref(c):
    r, g, b = c
    return (b << 16) | (g << 8) | r


# ---------------------------------------------------------------------------
# Contents stream
# ---------------------------------------------------------------------------
class ContentsModel:
    def __init__(self, data):
        self.data = data
        self.trailer_off = struct.unpack_from("<I", data, 0x1A)[0]
        tblocks, _ = parse_record(data, self.trailer_off)
        self.trailer = tblocks
        self.directory = [b for b in tblocks if b.type == 0x90][0]
        self.chunks = {}  # seq -> blocks
        for seq, entry in enumerate(self.directory.value):
            if entry.type == 0x88 and entry.get(0x04) is not None:
                blocks, _ = parse_record(data, entry.get(0x04))
                self.chunks[seq] = blocks
        self.recA, _ = parse_record(data, 0x2C)
        self.recB_off = struct.unpack_from("<I", data, 0x1E)[0]
        self.recB_raw = data[self.recB_off:self.recB_off + struct.unpack_from("<I", data, self.recB_off)[0]]
        self.fixed_head = bytearray(data[:0x2C])

    def entry(self, seq):
        return self.directory.value[seq]

    def new_seq(self):
        self.directory.value.append(Block(0x00, 0x78, 0))
        return len(self.directory.value) - 1

    def add_chunk(self, ctype, parent, blocks, entry_extra=(0x0B, 1), with_flag8=False):
        seq = self.new_seq()
        e = [Block(0x02, 0x18, ctype), Block(0x04, 0xB8, 0)]
        if parent is not None:
            e.append(Block(0x05, 0x68, parent))
        e.append(Block(0x06, 0x10, 0))
        if with_flag8:
            e.append(Block(0x08, 0x08, 0))
        if entry_extra:
            e.append(Block(entry_extra[0], 0x18, entry_extra[1]))
        self.directory.value[seq] = Block(0x00, 0x88, e)
        self.chunks[seq] = blocks
        return seq

    def drop(self, seq):
        self.directory.value[seq] = Block(0x00, 0x78, 0)
        self.chunks.pop(seq, None)

    def serialize(self):
        # header region: fixed 0x2c bytes, record A, record B, chunks, trailer
        recA_len = len(ser_record(self.recA))
        recB_off = 0x2C + recA_len
        pos = recB_off + len(self.recB_raw)
        body = bytearray()
        offsets = {}
        for seq in sorted(self.chunks):
            rec = ser_record(self.chunks[seq])
            offsets[seq] = pos + len(body)
            body += rec
        trailer_off = pos + len(body)
        for seq, off in offsets.items():
            e = self.directory.value[seq]
            e.set(0x04, 0xB8, off)
            e.set(0x06, 0x10, ((off >> 8) << 8 | 0x02) & 0xFFFF)
        # trailer counts
        n = len(self.directory.value)
        for b in self.trailer:
            if b.id == 0x01:
                b.value = n
            elif b.id == 0x02:
                b.value = max(self.chunks)
        trailer = ser_record(self.trailer)
        total = trailer_off + len(trailer)
        # record A self references
        for b in self.recA:
            if b.id == 0x08:
                b.value = total
            elif b.id == 0x0A:
                b.value = trailer_off
            elif b.id == 0x0B:
                b.value = recB_off
        recA = ser_record(self.recA)
        assert len(recA) == recA_len
        head = bytearray(self.fixed_head)
        struct.pack_into("<I", head, 0x08, total)
        struct.pack_into("<I", head, 0x1A, trailer_off)
        struct.pack_into("<I", head, 0x1E, recB_off)
        out = bytes(head) + recA + self.recB_raw + bytes(body) + trailer
        assert len(out) == total
        return out


# ---------------------------------------------------------------------------
# Quill text stream
# ---------------------------------------------------------------------------
class TextBuilder:
    def __init__(self, tpl_chunks):
        self.tpl = quill.chunk_map(tpl_chunks)
        self.fonts = self._read_fonts(self.tpl["FONT"][0].data)
        self.font_hdr = self.tpl["FONT"][0].data[:20]
        self.colors_raw = self.tpl["PL  "][0].data
        self.colors = self._read_colors(self.colors_raw)
        self.stories = []  # (text_id, paras, item)

    # ---- fonts ----
    @staticmethod
    def _read_fonts(d):
        n = struct.unpack_from("<I", d, 4)[0]
        offs = struct.unpack_from(f"<{n}I", d, 20)
        out = []
        for o in offs:
            p = 20 + o
            nl = struct.unpack_from("<H", d, p)[0]
            nm = d[p + 2:p + 2 + nl * 2].decode("utf-16-le")
            v = struct.unpack_from("<I", d, p + 2 + nl * 2)[0]
            out.append([nm, v])
        return out

    def font_index(self, name):
        for i, (nm, v) in enumerate(self.fonts):
            if nm.lower() == name.lower():
                return i
        nxt = max(v for _, v in self.fonts) + 1
        self.fonts.append([name, nxt])
        return len(self.fonts) - 1

    def font_chunk(self):
        n = len(self.fonts)
        entries = []
        for nm, v in self.fonts:
            enc = nm.encode("utf-16-le")
            entries.append(struct.pack("<H", len(nm)) + enc + struct.pack("<I", v))
        table_start = 4 * n
        offs = []
        pos = table_start
        for e in entries:
            offs.append(pos)
            pos += len(e)
        body = b"".join(struct.pack("<I", o) for o in offs) + b"".join(entries)
        hdr = bytearray(self.font_hdr)
        struct.pack_into("<I", hdr, 0, len(body))
        struct.pack_into("<I", hdr, 4, n)
        return bytes(hdr) + body

    # ---- colours ----
    @staticmethod
    def _read_colors(d):
        n = struct.unpack_from("<I", d, 0)[0]
        pos = 12
        out = []
        for _ in range(n):
            ln = struct.unpack_from("<I", d, pos)[0]
            out.append(d[pos:pos + ln])
            pos += ln
        return out

    def color_index(self, rgb):
        if tuple(rgb) == (0, 0, 0):
            return None
        rec = ser_record([Block(0x01, 0x22, rgb_ref(rgb)), Block(0x06, 0x82, [])])
        for i, r in enumerate(self.colors):
            if r == rec:
                return i
        self.colors.append(rec)
        return len(self.colors) - 1

    def color_chunk(self):
        hdr = bytearray(self.colors_raw[:12])
        struct.pack_into("<I", hdr, 0, len(self.colors))
        return bytes(hdr) + b"".join(self.colors)

    # ---- properties ----
    def char_props(self, run):
        size = emu(run.size)
        props = []
        if run.bold:
            props.append(Block(0x02, 0x0A, 0))
        if run.italic:
            props.append(Block(0x03, 0x0A, 0))
        props.append(Block(0x0C, 0x22, size))
        props.append(Block(0x12, 0x22, 0x409))
        if run.underline:
            props.append(Block(0x1E, 0x12, 0x1))
        fi = self.font_index(run.font)
        props.append(Block(0x24, 0x8A, [Block(s, 0x88, [Block(0x00, 0x18, fi)]) for s in FONT_SLOTS]))
        if run.bold:
            props.append(Block(0x37, 0x0A, 0))
        if run.italic:
            props.append(Block(0x38, 0x0A, 0))
        props.append(Block(0x39, 0x22, size))
        props.append(Block(0x3E, 0x22, 0x409))
        ci = self.color_index(run.color)
        if ci is not None:
            props.append(Block(0x44, 0x8A, [Block(0x00, 0x22, ci)]))
        return props

    @staticmethod
    def para_props(para):
        a = {"left": 0, "right": 1, "center": 2, "justify": 6}.get(para.align, 0)
        return [Block(0x04, 0x12, a)] if a else []

    # ---- build ----
    def build(self, stories):
        """stories: list of (text_id, item). returns the Quill stream bytes"""
        TEXT_START = 0x200
        text = []
        char_runs = []  # (end_char_index, props)
        para_runs = []
        lengths = []
        for tid, item in stories:
            paras = item.paras or [Para([Run("")])]
            start_len = len(text)
            for para in paras:
                runs = [r for r in para.runs if r.text] or [para.runs[0] if para.runs else Run("")]
                for r in runs:
                    t = r.text.replace("\r\n", "\v").replace("\n", "\v")
                    text.extend(t)
                    if t:
                        char_runs.append((len(text), self.char_props(r)))
                text.append("\r")
                last = runs[-1]
                char_runs.append((len(text), self.char_props(last)))
                para_runs.append((len(text), self.para_props(para)))
            lengths.append(len(text) - start_len)
        text_bytes = "".join(text).replace("\v", "\n").encode("utf-16-le")

        def abs_off(ci):
            return TEXT_START + 2 * ci

        # merge identical adjacent char runs
        merged = []
        for end, props in char_runs:
            if merged and ser_blocks(merged[-1][1]) == ser_blocks(props):
                merged[-1] = (end, props)
            else:
                merged.append((end, props))

        def paginate(runs):
            pages = []
            cur = []
            for end, props in runs:
                trial = cur + [(abs_off(end), props)]
                if fkp.fkp_capacity_ok(trial):
                    cur = trial
                else:
                    pages.append(cur)
                    cur = [(abs_off(end), props)]
            if cur:
                pages.append(cur)
            return pages

        cpages = paginate(merged) or [[]]
        ppages = paginate(para_runs) or [[]]

        def fkp_bytes(pages):
            out = []
            start = 0
            for i, p in enumerate(pages):
                out.append(fkp.build_fkp(p, 1, start))
                start = p[-1][0] if p else start
            return out

        fdpc = fkp_bytes(cpages)
        fdpp = fkp_bytes(ppages)

        def bte(pages, first_page_off):
            n = len(pages)
            poss = [0] + [(p[-1][0] if p else TEXT_START) for p in pages]
            data = [first_page_off + 0x200 * i for i in range(n)]
            return struct.pack("<III", n, 4, 0) + b"".join(struct.pack("<I", x) for x in poss) + \
                b"".join(struct.pack("<I", x) for x in data)

        nst = len(stories)
        strs = struct.pack("<III", nst, 8, 0xFF) + b"".join(struct.pack("<I", l) for l in lengths) + \
            struct.pack("<I", 0)
        for i in range(nst):
            strs += ser_record([Block(0x00, 0x22, 5)]) if i == 0 else struct.pack("<I", 4)
        ids = [tid for tid, _ in stories]
        syid = struct.pack("<II", max(ids) if ids else 0, nst) + b"".join(struct.pack("<I", i) for i in ids)

        mcld = self.build_mcld(stories)

        # ---- layout -----------------------------------------------------
        t = self.tpl
        layout = []  # (name, id, data, name2)
        layout.append(("TEXT", 0, text_bytes, "TEXT"))
        for c in t["STSH"]:
            layout.append(("STSH", c.id, c.data, c.name2))
        # aligned FKP pages after
        fixed = []
        for i, d in enumerate(fdpp):
            fixed.append(("FDPP", i, d, "FDPP"))
        for i, d in enumerate(fdpc):
            fixed.append(("FDPC", i, d, "FDPC"))
        tail = [("SYID", 0, syid, "SYID"),
                ("SGP ", 0, t["SGP "][0].data, "SGP "),
                ("INK ", 0, t["INK "][0].data, "INK "),
                ("BTEP", 0, None, "PLC "),
                ("BTEC", 0, None, "PLC "),
                ("FONT", 0, self.font_chunk(), "FONT"),
                ("STRS", 0, strs, "PLC "),
                ("MCLD", 0, mcld, "MCLD"),
                ("PL  ", 0, self.color_chunk(), "PL  ")]
        chunks = layout + fixed + tail
        nchunks = len(chunks)
        per_list = 20
        nlists = (nchunks + per_list - 1) // per_list
        # first list lives at 0x18 and must end before 0x200
        if nlists > 1:
            pass  # extra lists are placed after the data (see below)
        pos = TEXT_START
        offsets = {}
        for name, cid, data, _ in layout:
            offsets[(name, cid)] = pos
            pos += len(data)
        pos = (pos + 0x1FF) & ~0x1FF
        for name, cid, data, _ in fixed:
            offsets[(name, cid)] = pos
            pos += 0x200
        fdpp_off = offsets[("FDPP", 0)]
        fdpc_off = offsets[("FDPC", 0)]
        btep = bte(ppages, fdpp_off)
        btec = bte(cpages, fdpc_off)
        final_tail = []
        for name, cid, data, n2 in tail:
            if name == "BTEP":
                data = btep
            elif name == "BTEC":
                data = btec
            final_tail.append((name, cid, data, n2))
            offsets[(name, cid)] = pos
            pos += len(data)
        chunks = layout + fixed + final_tail
        # extra directory lists (if any) after data
        list_offsets = [0x18]
        for i in range(1, nlists):
            pos = (pos + 0x1FF) & ~0x1FF
            list_offsets.append(pos)
            pos += 0x200
        total = (pos + 0x1FF) & ~0x1FF

        out = bytearray(total)
        hdr = bytearray(b"CHNKINK " + bytes.fromhex("04000700") + b"\x00\x00" + bytes.fromhex("0003") +
                        struct.pack("<I", 0x200) + struct.pack("<I", total))
        struct.pack_into("<H", hdr, 0x0C, nchunks)
        struct.pack_into("<I", hdr, 0x10, 0x200 * nlists)
        out[0:0x18] = hdr
        for li in range(nlists):
            part = chunks[li * per_list:(li + 1) * per_list]
            lo = list_offsets[li]
            nxt = list_offsets[li + 1] if li + 1 < nlists else 0xFFFFFFFF
            struct.pack_into("<HHI", out, lo, 0x1F8, len(part), nxt)
            p = lo + 8
            for name, cid, data, n2 in part:
                struct.pack_into("<H", out, p, 0x18)
                out[p + 2:p + 6] = name.encode("latin1")
                struct.pack_into("<H", out, p + 6, cid)
                out[p + 8:p + 12] = b"\x01\x00\x00\x00"
                out[p + 12:p + 16] = n2.encode("latin1")
                struct.pack_into("<II", out, p + 16, offsets[(name, cid)], len(data))
                p += 24
        for name, cid, data, _ in chunks:
            o = offsets[(name, cid)]
            out[o:o + len(data)] = data
        return bytes(out)

    def build_mcld(self, stories):
        tpl = self.tpl["MCLD"][0].data
        n0 = struct.unpack_from("<I", tpl, 0)[0]
        pos = 8 + 4 * n0
        recA_len = struct.unpack_from("<I", tpl, pos)[0]
        recA = tpl[pos:pos + recA_len]
        pos += recA_len
        pos += 4  # frame count
        recB_blocks, recB_len = parse_record(tpl, pos)
        n = len(stories)
        out = struct.pack("<II", n, n) + b"".join(struct.pack("<I", i + 1) for i in range(n))
        for tid, item in stories:
            blocks = parse_blocks(ser_blocks(recB_blocks), 0, len(ser_blocks(recB_blocks)))
            for b in blocks:
                if b.id == 0x04:
                    b.value = emu(item.w)
                elif b.id == 0x05:
                    b.value = emu(item.h)
            out += recA + struct.pack("<I", 1) + ser_record(blocks)
        return out


# ---------------------------------------------------------------------------
# Escher helpers
# ---------------------------------------------------------------------------
def fopt_from_template(name):
    ver, inst, hexdata = SHAPE_TPL[name]["fopt"]
    rec = escher.Rec(ver, inst, 0xF00B, data=bytes.fromhex(hexdata))
    props, cplx = escher.fopt_props(rec)
    return [(pid, val) for pid, val in props if not (pid & 0x8000)]


def tert_from_template(name):
    t = SHAPE_TPL[name]["tert"]
    if not t:
        return None
    ver, inst, hexdata = t
    return escher.Rec(ver, inst, 0xF122, data=bytes.fromhex(hexdata))


def set_prop(props, pid, val):
    for i, (p, v) in enumerate(props):
        if p == pid:
            props[i] = (pid, val)
            return
    props.append((pid, val))
    props.sort(key=lambda x: x[0] & 0x3FFF)


def del_prop(props, pid):
    props[:] = [(p, v) for p, v in props if p != pid]


def apply_fill_line(props, item, default_line):
    if item.fill is not None:
        set_prop(props, 0x0181, rgb_ref(item.fill))
        set_prop(props, 0x01BF, 0x1F001C)
    else:
        set_prop(props, 0x01BF, 0x100000)
    if item.stroke is not None:
        set_prop(props, 0x01C0, rgb_ref(item.stroke))
        set_prop(props, 0x01CB, emu(max(item.stroke_width, 0.25)))
        set_prop(props, 0x01FF, 0xF000E if default_line == "pen" else 0x80008)
    else:
        set_prop(props, 0x01FF, 0xF0006 if default_line == "pen" else 0x80000)
    if item.rotation:
        set_prop(props, 0x0004, int(round((item.rotation % 360) * 65536)) & 0xFFFFFFFF)


def blip_record(img):
    if img[:8] == b"\x89PNG\r\n\x1a\n":
        bt, typ, inst = 6, 0xF01E, 0x6E0
    elif img[:2] == b"\xff\xd8":
        bt, typ, inst = 5, 0xF01D, 0x46A
    else:
        raise ValueError("only PNG and JPEG pictures can be stored in .pub files")
    uid = hashlib.md5(img).digest()
    rec = struct.pack("<HHI", inst << 4, typ, 17 + len(img)) + uid + b"\xff" + img
    return bt, uid, rec


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def write_pub(doc: Document, path, title=""):
    src = olefile.OleFileIO(TEMPLATE)
    cm = ContentsModel(src.openstream("Contents").read())
    esc = escher.parse(src.openstream("Escher/EscherStm").read())
    qhead, qlists, qchunks = quill.parse(src.openstream("Quill/QuillSub/CONTENTS").read())
    tb = TextBuilder(qchunks)

    W, H = emu(doc.width), emu(doc.height)

    # ---- document size, margins, page setup ---------------------------
    docb = cm.chunks[SEQ_DOC]
    size = [b for b in docb if b.id == 0x12][0]
    size.set(0x01, 0x20, W)
    size.set(0x02, 0x20, H)
    margins = cm.chunks[SEQ_MARGINS]
    m = int(round(getattr(doc, "margin", 36) * EMU_PER_PT))  # margin guides
    guides = [b for b in margins if b.id == 0x02][0].value
    gvals = [m, W - m, m, H - m]
    for g, v in zip(guides, gvals):
        g.set(0x01, 0x20, v)
    msize = [b for b in margins if b.id == 0x03][0]
    msize.set(0x01, 0x20, W)
    msize.set(0x02, 0x20, H)
    is_a4 = abs(W - 7560000) < 20000 and abs(H - 10692000) < 20000
    if not is_a4:
        cm.drop(SEQ_PAGESETUP)
        docb[:] = [b for b in docb if b.id != 0x44]

    # ---- drop template shapes -----------------------------------------
    for s in SEQ_TEMPLATE_SHAPES:
        cm.drop(s)

    # ---- pages --------------------------------------------------------
    page_seqs = []
    tpl_page = ser_record(cm.chunks[SEQ_PAGE1])
    tpl_a = ser_record(cm.chunks[SEQ_PAGE1_A])
    tpl_b = ser_record(cm.chunks[SEQ_PAGE1_B])
    for i, page in enumerate(doc.pages):
        if i == 0:
            pseq = SEQ_PAGE1
        else:
            pblocks, _ = parse_record(tpl_page, 0)
            pseq = cm.add_chunk(CHUNK_PAGE, SEQ_DOC, pblocks, with_flag8=True)
            aseq = cm.add_chunk(0x60, pseq, parse_record(tpl_a, 0)[0], entry_extra=None)
            bseq = cm.add_chunk(0x77, pseq, parse_record(tpl_b, 0)[0])
            for b in pblocks:
                if b.id == 0x09:
                    b.value = aseq
                elif b.id == 0x0B:
                    b.value = bseq
        pb = cm.chunks[pseq]
        for b in pb:
            if b.id == 0x06 and b.type == 0x28:
                b.value = struct.pack("<II", 1, i)
        page_seqs.append(pseq)
    plist = [b for b in docb if b.id == 0x02][0]
    plist.value = [Block(0x00, 0x70, s) for s in [SEQ_MASTER] + page_seqs + list(DUMMY_PAGES)]
    docb_count = [b for b in docb if b.id == 0x01][0]
    docb_count.value = len(plist.value)

    # ---- shapes -------------------------------------------------------
    dg = [r for r in esc if r.type == 0xF002 and r.find(0xF008).inst == 1][0]
    spgr = dg.find(0xF003)
    root_sp = spgr.children[0]
    spgr.children = [root_sp]
    next_spid = 0x401
    text_id = 0
    stories = []
    story_map = []
    blips = []  # (bt, uid, rec)
    cx, cy = W // 2, H // 2

    for pi, page in enumerate(doc.pages):
        pseq = page_seqs[pi]
        shape_seqs = []
        for item in page.items:
            kind = item.kind
            x0, y0 = emu(item.x), emu(item.y)
            x1, y1 = emu(item.x + item.w), emu(item.y + item.h)
            flags = 0x0A00
            if kind == "line":
                if x1 < x0:
                    flags |= 0x40
                if y1 < y0:
                    flags |= 0x80
            xs, xe = sorted((x0, x1))
            ys, ye = sorted((y0, y1))
            wE, hE = max(xe - xs, 1), max(ye - ys, 1)
            rot = (item.rotation or 0) % 360
            axs, ays, axe, aye = xs, ys, xe, ye
            if kind != "line" and ((45 <= rot < 135) or (225 <= rot < 315)):
                # Publisher stores the rotated bounding box for steep rotations
                mx, my = (xs + xe) // 2, (ys + ye) // 2
                axs, axe = mx - hE // 2, mx - hE // 2 + hE
                ays, aye = my - wE // 2, my - wE // 2 + wE
            anchor = [(0x2001, s32(axs - cx)), (0x2002, s32(ays - cy)),
                      (0x2003, s32(axe - cx)), (0x2004, s32(aye - cy))]
            spid = next_spid
            next_spid += 1
            children = []
            if kind == "text":
                text_id += 1
                props = fopt_from_template("text")
                set_prop(props, 0x0080, text_id)
                apply_fill_line(props, item, "simple")
                fsp_type, tpl_name = 202, "text"
                ctype = CHUNK_SHAPE
                cblocks = [Block(0x02, 0x08, 0), Block(0x03, 0x08, 0), Block(0x04, 0x10, 3),
                           Block(0x0C, 0x28, bytes(8)), Block(0x0D, 0x28, bytes(8)),
                           Block(0x27, 0x20, text_id), Block(0x2B, 0x08, 0), Block(0x2C, 0x08, 0)]
                if item.valign in ("middle", "bottom"):
                    cblocks.append(Block(0x35, 0x20, 1 if item.valign == "middle" else 2))
                cblocks += [Block(0xAA, 0x20, wE), Block(0xAB, 0x20, hE)]
            elif kind in ("rect", "ellipse", "auto"):
                props = fopt_from_template("ellipse" if kind == "ellipse" else "rect")
                apply_fill_line(props, item, "pen")
                fsp_type = {"rect": 1, "ellipse": 3}.get(kind) or (item.spt or 1)
                tpl_name = "ellipse" if kind == "ellipse" else "rect"
                ctype = CHUNK_SHAPE
                cblocks = [Block(0x01, 0x08, 0), Block(0x04, 0x10, 0x3000),
                           Block(0x0C, 0x28, bytes(8)), Block(0x0D, 0x28, bytes(8)),
                           Block(0x34, 0x20, 0), Block(0xAA, 0x20, wE), Block(0xAB, 0x20, hE)]
            elif kind == "line":
                props = fopt_from_template("line")
                item_l = Item(kind="line", stroke=item.stroke or (0, 0, 0), stroke_width=item.stroke_width)
                apply_fill_line(props, item_l, "pen")
                del_prop(props, 0x01BF)
                fsp_type, tpl_name = 20, "line"
                ctype = CHUNK_ALTSHAPE
                cblocks = [Block(0x01, 0x08, 0), Block(0x02, 0x08, 0), Block(0x04, 0x10, 0x3000),
                           Block(0x0C, 0x28, bytes(8)), Block(0x0D, 0x28, bytes(8))]
            elif kind == "image":
                props = fopt_from_template("picture")
                bt, uid, rec = blip_record(item.image)
                idx = None
                for k, (_, u, _) in enumerate(blips):
                    if u == uid:
                        idx = k + 1
                if idx is None:
                    blips.append((bt, uid, rec))
                    idx = len(blips)
                set_prop(props, 0x4104, idx)
                del_prop(props, 0xC105)
                apply_fill_line(props, Item(kind="image", stroke=item.stroke, stroke_width=item.stroke_width,
                                            rotation=item.rotation), "pen")
                set_prop(props, 0x01BF, 0x1F000C)
                fsp_type, tpl_name = 1, "picture"
                ctype = CHUNK_SHAPE
                cblocks = None  # filled below (needs name chunk)
            else:
                continue

            seq = cm.add_chunk(ctype, pseq, [])
            if kind == "image":
                name_seq = cm.add_chunk(0x66, seq, [ustr(0x03, item.image_name or "picture.png")])
                cblocks = [Block(0x01, 0x08, 0), Block(0x0C, 0x28, bytes(8)), Block(0x0D, 0x28, bytes(8)),
                           Block(0x34, 0x20, 0), Block(0x3A, 0x70, name_seq), Block(0x40, 0x08, 0),
                           Block(0xAA, 0x20, wE), Block(0xAB, 0x20, hE)]
            cm.chunks[seq] = cblocks
            shape_seqs.append(seq)
            if kind == "text":
                stories.append((text_id, item))
                story_map.append((text_id, seq))

            fsp = escher.Rec(2, fsp_type, 0xF00A, data=struct.pack("<II", spid, flags))
            fopt = escher.make_fopt(props)
            sp_children = [fsp, fopt]
            tert = tert_from_template(tpl_name)
            if tert:
                sp_children.append(tert)
            ver_inst = SHAPE_TPL["text"]["anchor"][0]
            sp_children.append(escher.make_client(0xF010, anchor, ver=ver_inst[0], inst=ver_inst[1]))
            sp_children.append(escher.make_client(0xF011, [(0x6801, seq)], ver=ver_inst[0], inst=ver_inst[1]))
            if kind == "text":
                sp_children.append(escher.make_client(0xF00D, [(0x2001, text_id)], ver=ver_inst[0], inst=ver_inst[1]))
            spgr.children.append(escher.Rec(0xF, 0, 0xF004, children=sp_children))

        pb = cm.chunks[pseq]
        pb[:] = [b for b in pb if not (b.id in (0x01, 0x02) and b.type in (0x20, 0xA0))]
        if shape_seqs:
            pb[0:0] = [Block(0x01, 0x20, len(shape_seqs)),
                       Block(0x02, 0xA0, [Block(0x00, 0x70, s) for s in shape_seqs])]

    # FDG / FDGG bookkeeping
    csp = next_spid - 0x400
    fdg = dg.find(0xF008)
    fdg.data = struct.pack("<II", csp, next_spid - 1)
    dgg = esc[0]
    fdgg = dgg.find(0xF006)
    vals = list(struct.unpack(f"<{len(fdgg.data) // 4}I", fdgg.data))
    curs = {}
    total_csp = 0
    for r in esc:
        if r.type == 0xF002:
            f = r.find(0xF008)
            c, cur = struct.unpack("<II", f.data)
            curs[f.inst] = cur
            total_csp += c
    clusters = vals[4:]
    for i in range(0, len(clusters), 2):
        d = clusters[i]
        if d in curs:
            clusters[i + 1] = (curs[d] & 0x3FF) + 1
    vals = [max(curs.values()) + 1, vals[1], total_csp, vals[3]] + clusters
    fdgg.data = struct.pack(f"<{len(vals)}I", *vals)

    # pictures: BStore in DGG + delay stream
    delay = bytearray()
    if blips:
        fbses = []
        for bt, uid, rec in blips:
            fo = len(delay)
            delay += rec
            data = struct.pack("<BB", bt, bt) + uid + struct.pack("<HIII", 0xFF, len(rec), 1, fo) + bytes(4)
            fbses.append(escher.Rec(2, bt, 0xF007, data=data))
        bstore = escher.Rec(0xF, len(fbses), 0xF001, children=fbses)
        dgg.children = [c for c in dgg.children if c.type != 0xF001]
        dgg.children.insert(1, bstore)

    # story tables in Contents
    smap = cm.chunks[SEQ_STORYMAP]
    slist = cm.chunks[SEQ_STORYLIST]
    smap[:] = [Block(0x01, 0x20, len(story_map)),
               Block(0x02, 0xA0, [Block(0x00, 0x88, [Block(0x01, 0x20, t), Block(0x03, 0x68, s)])
                                  for t, s in story_map])]
    slist[:] = [Block(0x01, 0x20, len(story_map)),
                Block(0x02, 0xA0, [Block(0x00, 0x88, [Block(0x01, 0x20, t), Block(0x07, 0x20, i + 1),
                                                      Block(0x08, 0x58, 0xCB18967C), Block(0x09, 0x58, 0xCB18967C)])
                                   for i, (t, s) in enumerate(story_map)])]
    if not story_map:
        # Publisher always has at least one story; keep an empty off-page one is not needed for readers
        pass

    contents = cm.serialize()
    escher_stm = escher.ser(esc)
    quill_stm = tb.build(stories)

    # ---- OLE container --------------------------------------------------
    w = CFBWriter(root_clsid=str(src.root.clsid))
    w.add_stream("\x01CompObj", src.openstream("\x01CompObj").read())
    w.add_stream("\x03Internal", src.openstream("\x03Internal").read())
    w.add_stream("\x05DocumentSummaryInformation", src.openstream("\x05DocumentSummaryInformation").read())
    w.add_stream("\x05SummaryInformation", property_set_stream(
        "F29F85E0-4FF9-1068-AB91-08002B27B3D9",
        [(1, 2, 1252)] + ([(2, 0x1E, title)] if title else []) + [(18, 0x1E, "PubDesign")]))
    w.add_stream("Contents", contents)
    w.add_stream("Envelope", b"")
    w.add_storage("Escher")
    w.add_stream("Escher/EscherDelayStm", bytes(delay))
    w.add_stream("Escher/EscherStm", escher_stm)
    w.add_storage("Quill")
    w.add_storage("Quill/QuillSub", clsid=src.getclsid("Quill/QuillSub"))
    w.add_stream("Quill/QuillSub/\x01CompObj", src.openstream("Quill/QuillSub/\x01CompObj").read())
    w.add_stream("Quill/QuillSub/CONTENTS", quill_stm)
    data = w.build()
    with open(path, "wb") as f:
        f.write(data)
    return path
