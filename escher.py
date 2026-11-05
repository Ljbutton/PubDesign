"""OfficeArt (Escher) record tree for Publisher's Escher/EscherStm stream.

Publisher quirks (from libmspub): DggContainer (0xF000) and DgContainer
(0xF002) are followed by 4 extra bytes not counted in their length.
"""
import struct

NAMES = {
    0xF000: "DggContainer", 0xF001: "BStoreContainer", 0xF002: "DgContainer",
    0xF003: "SpgrContainer", 0xF004: "SpContainer", 0xF006: "FDGG", 0xF007: "FBSE",
    0xF008: "FDG", 0xF009: "FSPGR", 0xF00A: "FSP", 0xF00B: "FOPT", 0xF00F: "ChildAnchor",
    0xF010: "ClientAnchor", 0xF011: "ClientData", 0xF11E: "SplitMenuColors",
    0xF122: "TertiaryFOPT", 0xF118: "ColorMRU", 0xF00D: "ClientTextbox",
}
TAIL4 = {0xF000, 0xF002}


class Rec:
    __slots__ = ("ver", "inst", "type", "data", "children", "tail")

    def __init__(self, ver, inst, type, data=b"", children=None, tail=b""):
        self.ver, self.inst, self.type = ver, inst, type
        self.data = data
        self.children = children
        self.tail = tail

    @property
    def is_container(self):
        return self.children is not None

    def find(self, type):
        for c in self.children or []:
            if c.type == type:
                return c
        return None

    def find_all(self, type):
        return [c for c in (self.children or []) if c.type == type]

    def dump(self, indent=0, lines=None):
        top = lines is None
        lines = [] if top else lines
        pad = "  " * indent
        nm = NAMES.get(self.type, hex(self.type))
        if self.is_container:
            lines.append(f"{pad}{nm} ver={self.ver:#x} inst={self.inst:#x} n={len(self.children)} tail={self.tail.hex()}")
            for c in self.children:
                c.dump(indent + 1, lines)
        else:
            extra = ""
            if self.type in (0xF00B, 0xF122):
                extra = " " + str({f"{k:#06x}": f"{v:#x}" for k, v in fopt_props(self)[0]})
            elif self.type in (0xF010, 0xF011):
                extra = " " + str({f"{k:#x}": f"{v:#x}" for k, v in client_values(self)})
            d = self.data.hex()
            if len(d) > 120:
                d = d[:120] + f"..({len(self.data)}b)"
            lines.append(f"{pad}{nm} ver={self.ver:#x} inst={self.inst:#x} data={d}{extra}")
        if top:
            return "\n".join(lines)


def parse(buf, pos=0, end=None):
    end = len(buf) if end is None else end
    out = []
    while pos + 8 <= end:
        vi, typ, ln = struct.unpack_from("<HHI", buf, pos)
        ver, inst = vi & 0xF, vi >> 4
        body_start = pos + 8
        body_end = body_start + ln
        if body_end > end:
            raise ValueError(f"escher record overruns at {pos:#x}")
        if ver == 0xF:
            rec = Rec(ver, inst, typ, children=parse(buf, body_start, body_end))
        else:
            rec = Rec(ver, inst, typ, data=bytes(buf[body_start:body_end]))
        pos = body_end
        if typ in TAIL4:
            rec.tail = bytes(buf[pos:pos + 4])
            pos += 4
        out.append(rec)
    if pos != end:
        # trailing bytes that do not form a record
        out.append(Rec(0, 0, 0xFFFF, data=bytes(buf[pos:end])))
    return out


def ser(recs):
    out = bytearray()
    for r in recs:
        if r.type == 0xFFFF:
            out += r.data
            continue
        body = ser(r.children) if r.is_container else r.data
        out += struct.pack("<HHI", (r.inst << 4) | r.ver, r.type, len(body)) + body
        out += r.tail
    return bytes(out)


def fopt_props(rec):
    """returns ([(id, value)], complex_blob)"""
    n = rec.inst
    props = []
    pos = 0
    for _ in range(n):
        pid, val = struct.unpack_from("<HI", rec.data, pos)
        props.append((pid, val))
        pos += 6
    return props, rec.data[pos:]


def make_fopt(props, complex_blob=b"", type=0xF00B, ver=3):
    data = b"".join(struct.pack("<HI", pid, val & 0xFFFFFFFF) for pid, val in props) + complex_blob
    return Rec(ver, len(props), type, data=data)


def client_values(rec):
    """ClientAnchor / ClientData: u32 length (repeat) then (u16 id, u32 value)*"""
    d = rec.data
    vals = []
    pos = 4
    while pos + 6 <= len(d):
        pid, val = struct.unpack_from("<HI", d, pos)
        vals.append((pid, val))
        pos += 6
    return vals


def make_client(type, values, ver=0, inst=0):
    body = b"".join(struct.pack("<HI", k, v & 0xFFFFFFFF) for k, v in values)
    data = struct.pack("<I", len(body) + 4) + body
    return Rec(ver, inst, type, data=data)
