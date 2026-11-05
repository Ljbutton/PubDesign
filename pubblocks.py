"""Generic TLV block grammar used by the Publisher 2002+ 'Contents' stream
and by the Quill paragraph/character property records.

A block is: id (u8), type (u8), then data whose size depends on type.
Variable-length types start their data with a u32 length that includes
the length field itself. All variable-length types except strings (0xC0)
hold a list of child blocks.
"""
import struct

FIXED_LEN = {
    0x78: 0, 0x05: 0, 0x08: 0, 0x0a: 0, 0x00: 0, 0x02: 0,
    0x10: 2, 0x12: 2, 0x18: 2, 0x1a: 2, 0x07: 2,
    0x20: 4, 0x22: 4, 0x58: 4, 0x68: 4, 0x70: 4, 0xb8: 4,
    0x28: 8, 0x38: 16, 0x48: 24,
}
VAR_TYPES = {0xc0, 0x80, 0x82, 0x88, 0x8a, 0x90, 0x98, 0xa0}
STRING = 0xc0


class BlockError(Exception):
    pass


class Raw(bytes):
    """Opaque payload of a variable-length block that is not a block list."""


class Block:
    __slots__ = ("id", "type", "value")

    def __init__(self, id, type, value=None):
        self.id = id
        self.type = type
        if value is None:
            value = [] if (type in VAR_TYPES and type != STRING) else (b"" if type == STRING else 0)
        self.value = value

    # ---- convenience -------------------------------------------------
    @property
    def is_container(self):
        return isinstance(self.value, list)

    def find(self, id, type=None):
        if not self.is_container:
            return None
        for b in self.value:
            if b.id == id and (type is None or b.type == type):
                return b
        return None

    def find_all(self, id, type=None):
        if not self.is_container:
            return []
        return [b for b in self.value if b.id == id and (type is None or b.type == type)]

    def get(self, id, default=None):
        b = self.find(id)
        return default if b is None else b.value

    def set(self, id, type, value):
        b = self.find(id)
        if b is None:
            b = Block(id, type, value)
            self.value.append(b)
        else:
            b.type = type
            b.value = value
        return b

    def __repr__(self):
        if self.is_container:
            return f"Block({self.id:#x},{self.type:#x},[{len(self.value)}])"
        if isinstance(self.value, bytes):
            return f"Block({self.id:#x},{self.type:#x},{self.value[:16].hex()})"
        return f"Block({self.id:#x},{self.type:#x},{self.value:#x})"

    def dump(self, indent=0, out=None):
        lines = out if out is not None else []
        pad = "  " * indent
        if self.is_container:
            lines.append(f"{pad}[{self.id:#04x} t{self.type:#04x}] ({len(self.value)} children)")
            for c in self.value:
                c.dump(indent + 1, lines)
        elif isinstance(self.value, bytes):
            txt = ""
            if self.type == STRING:
                try:
                    txt = " " + repr(self.value.decode("utf-16-le"))
                except Exception:
                    pass
            hx = self.value.hex()
            if len(hx) > 160:
                hx = hx[:160] + f"...({len(self.value)} bytes)"
            lines.append(f"{pad}[{self.id:#04x} t{self.type:#04x}] {'raw' if isinstance(self.value, Raw) else 'bytes'} {hx}{txt}")
        else:
            lines.append(f"{pad}[{self.id:#04x} t{self.type:#04x}] {self.value:#x}")
        if out is None:
            return "\n".join(lines)


def parse_block(buf, pos, end):
    if pos + 2 > end:
        raise BlockError(f"truncated block header at {pos:#x}")
    bid, btype = buf[pos], buf[pos + 1]
    pos += 2
    if btype in FIXED_LEN:
        n = FIXED_LEN[btype]
        if pos + n > end:
            raise BlockError(f"truncated fixed data at {pos:#x}")
        if n == 0:
            val = 0
        elif n == 2:
            val = struct.unpack_from("<H", buf, pos)[0]
        elif n == 4:
            val = struct.unpack_from("<I", buf, pos)[0]
        else:
            val = bytes(buf[pos:pos + n])
        return Block(bid, btype, val), pos + n
    if btype in VAR_TYPES:
        if pos + 4 > end:
            raise BlockError(f"truncated var length at {pos:#x}")
        ln = struct.unpack_from("<I", buf, pos)[0]
        if ln < 4 or pos + ln > end:
            raise BlockError(f"bad var length {ln:#x} at {pos:#x}")
        if btype == STRING:
            return Block(bid, btype, bytes(buf[pos + 4:pos + ln])), pos + ln
        try:
            children = parse_blocks(buf, pos + 4, pos + ln)
        except BlockError:
            return Block(bid, btype, Raw(buf[pos + 4:pos + ln])), pos + ln
        return Block(bid, btype, children), pos + ln
    raise BlockError(f"unknown block type {btype:#x} at {pos - 2:#x}")


def parse_blocks(buf, pos, end):
    out = []
    while pos < end:
        b, pos = parse_block(buf, pos, end)
        out.append(b)
    return out


def ser_block(b):
    head = bytes([b.id, b.type])
    if b.type in FIXED_LEN:
        n = FIXED_LEN[b.type]
        if n == 0:
            return head
        if n == 2:
            return head + struct.pack("<H", b.value & 0xFFFF)
        if n == 4:
            return head + struct.pack("<I", b.value & 0xFFFFFFFF)
        assert len(b.value) == n, (b, n)
        return head + b.value
    if b.type == STRING or isinstance(b.value, (bytes, Raw)):
        return head + struct.pack("<I", len(b.value) + 4) + bytes(b.value)
    body = ser_blocks(b.value)
    return head + struct.pack("<I", len(body) + 4) + body


def ser_blocks(blocks):
    return b"".join(ser_block(b) for b in blocks)


def parse_record(buf, pos):
    """A 'record' = u32 length (inclusive) followed by blocks."""
    ln = struct.unpack_from("<I", buf, pos)[0]
    return parse_blocks(buf, pos + 4, pos + ln), ln


def ser_record(blocks):
    body = ser_blocks(blocks)
    return struct.pack("<I", len(body) + 4) + body


# helpers -----------------------------------------------------------------
def B(id, type, value=None):
    return Block(id, type, value)


def u32(id, v):
    return Block(id, 0x20, v)


def u16(id, v):
    return Block(id, 0x10, v)


def flag(id):
    return Block(id, 0x78, 0)


def cont(id, children, type=0x88):
    return Block(id, type, list(children))


def ustr(id, s, nul=True):
    data = s.encode("utf-16-le") + (b"\x00\x00" if nul else b"")
    return Block(id, STRING, data)
