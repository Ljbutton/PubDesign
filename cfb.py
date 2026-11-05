"""Minimal Compound File Binary (OLE2 / MS-CFB v3) writer.

Usage:
    w = CFBWriter(root_clsid=...)
    w.add_stream("Contents", data)
    w.add_storage("Quill/QuillSub", clsid=...)
    w.add_stream("Quill/QuillSub/CONTENTS", data)
    open(path, "wb").write(w.build())
"""
import struct
import uuid

SECTOR = 512
MINI = 64
CUTOFF = 4096
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF


def clsid_bytes(s):
    if not s:
        return b"\x00" * 16
    return uuid.UUID(s).bytes_le


class _Node:
    def __init__(self, name, kind, data=b"", clsid=None):
        self.name = name
        self.kind = kind  # 1 storage, 2 stream, 5 root
        self.data = data
        self.clsid = clsid
        self.children = {}
        self.sid = None
        self.left = self.right = self.child = NOSTREAM
        self.start = ENDOFCHAIN
        self.size = 0


def _cmp_key(name):
    return (len(name), name.upper())


class CFBWriter:
    def __init__(self, root_clsid=None):
        self.root = _Node("Root Entry", 5, clsid=root_clsid)

    def _storage(self, parts, create=True, clsid=None):
        node = self.root
        for p in parts:
            if p not in node.children:
                if not create:
                    raise KeyError(p)
                node.children[p] = _Node(p, 1)
            node = node.children[p]
            if node.kind == 2:
                raise ValueError(f"{p} is a stream")
        if clsid:
            node.clsid = clsid
        return node

    def add_storage(self, path, clsid=None):
        self._storage([p for p in path.split("/") if p], clsid=clsid)

    def add_stream(self, path, data):
        parts = [p for p in path.split("/") if p]
        parent = self._storage(parts[:-1])
        parent.children[parts[-1]] = _Node(parts[-1], 2, bytes(data))

    # ------------------------------------------------------------------
    def build(self):
        nodes = []

        def collect(n):
            n.sid = len(nodes)
            nodes.append(n)
            for c in sorted(n.children.values(), key=lambda x: _cmp_key(x.name)):
                collect(c)

        collect(self.root)

        # sibling trees: balanced BST of each storage's children
        def build_tree(items):
            if not items:
                return NOSTREAM
            mid = len(items) // 2
            node = items[mid]
            node.left = build_tree(items[:mid])
            node.right = build_tree(items[mid + 1:])
            return node.sid

        for n in nodes:
            if n.kind in (1, 5):
                kids = sorted(n.children.values(), key=lambda x: _cmp_key(x.name))
                n.child = build_tree(kids)

        # mini stream
        mini = bytearray()
        minifat = []
        big_streams = []
        for n in nodes:
            if n.kind != 2:
                continue
            n.size = len(n.data)
            if n.size == 0:
                n.start = ENDOFCHAIN
            elif n.size < CUTOFF:
                first = len(minifat)
                count = (n.size + MINI - 1) // MINI
                for i in range(count):
                    minifat.append(first + i + 1 if i < count - 1 else ENDOFCHAIN)
                n.start = first
                mini += n.data + b"\x00" * (count * MINI - n.size)
            else:
                big_streams.append(n)

        # sector allocation plan: [directory][minifat][ministream][big streams][fat][difat]
        sectors = []  # list of bytes (each 512)
        fat = []

        def alloc_chain(data):
            if not data:
                return ENDOFCHAIN
            count = (len(data) + SECTOR - 1) // SECTOR
            first = len(sectors)
            padded = data + b"\x00" * (count * SECTOR - len(data))
            for i in range(count):
                sectors.append(padded[i * SECTOR:(i + 1) * SECTOR])
                fat.append(first + i + 1 if i < count - 1 else ENDOFCHAIN)
            return first

        # directory entries
        dir_count = len(nodes)
        dir_sectors = (dir_count * 128 + SECTOR - 1) // SECTOR
        # reserve directory sectors first (fill later)
        dir_first = len(sectors)
        for i in range(dir_sectors):
            sectors.append(b"")
            fat.append(dir_first + i + 1 if i < dir_sectors - 1 else ENDOFCHAIN)

        minifat_bytes = b"".join(struct.pack("<I", v) for v in minifat)
        minifat_first = alloc_chain(minifat_bytes) if minifat else ENDOFCHAIN
        minifat_count = (len(minifat_bytes) + SECTOR - 1) // SECTOR if minifat else 0

        self.root.start = alloc_chain(bytes(mini)) if mini else ENDOFCHAIN
        self.root.size = len(mini)

        for n in big_streams:
            n.start = alloc_chain(n.data)

        # FAT sectors: need enough to cover all sectors including themselves and DIFAT
        n_data = len(sectors)
        fat_secs = 0
        difat_secs = 0
        while True:
            total = n_data + fat_secs + difat_secs
            need_fat = (total + 127) // 128
            need_difat = 0 if need_fat <= 109 else (need_fat - 109 + 126) // 127
            if need_fat == fat_secs and need_difat == difat_secs:
                break
            fat_secs, difat_secs = need_fat, need_difat
        fat_first = len(sectors)
        fat_ids = list(range(fat_first, fat_first + fat_secs))
        for _ in range(fat_secs):
            fat.append(FATSECT)
            sectors.append(b"")
        difat_first = len(sectors)
        difat_ids = list(range(difat_first, difat_first + difat_secs))
        for _ in range(difat_secs):
            fat.append(DIFSECT)
            sectors.append(b"")
        fat += [FREESECT] * (fat_secs * 128 - len(fat))
        fat_bytes = b"".join(struct.pack("<I", v) for v in fat)
        for i, sid in enumerate(fat_ids):
            sectors[sid] = fat_bytes[i * SECTOR:(i + 1) * SECTOR]

        # DIFAT sectors
        extra = fat_ids[109:]
        for i, sid in enumerate(difat_ids):
            chunk = extra[i * 127:(i + 1) * 127]
            vals = chunk + [FREESECT] * (127 - len(chunk))
            nxt = difat_ids[i + 1] if i + 1 < len(difat_ids) else ENDOFCHAIN
            sectors[sid] = b"".join(struct.pack("<I", v) for v in vals) + struct.pack("<I", nxt)

        # directory
        def entry(n):
            name = n.name.encode("utf-16-le") + b"\x00\x00"
            e = bytearray(128)
            e[0:len(name)] = name
            struct.pack_into("<H", e, 64, len(name))
            e[66] = n.kind
            e[67] = 1  # black
            struct.pack_into("<III", e, 68, n.left, n.right, n.child)
            e[80:96] = clsid_bytes(n.clsid)
            struct.pack_into("<I", e, 116, n.start)
            struct.pack_into("<I", e, 120, n.size)
            return bytes(e)

        def empty_entry():
            e = bytearray(128)
            struct.pack_into("<III", e, 68, NOSTREAM, NOSTREAM, NOSTREAM)
            return bytes(e)

        dirdata = b"".join(entry(n) for n in nodes)
        dirdata += empty_entry() * ((dir_sectors * SECTOR - len(dirdata)) // 128)
        for i in range(dir_sectors):
            sectors[dir_first + i] = dirdata[i * SECTOR:(i + 1) * SECTOR]

        # header
        h = bytearray(512)
        h[0:8] = bytes.fromhex("D0CF11E0A1B11AE1")
        struct.pack_into("<HHHHH", h, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
        struct.pack_into("<I", h, 0x2C, fat_secs)
        struct.pack_into("<I", h, 0x30, dir_first)
        struct.pack_into("<I", h, 0x38, CUTOFF)
        struct.pack_into("<I", h, 0x3C, minifat_first)
        struct.pack_into("<I", h, 0x40, minifat_count)
        struct.pack_into("<I", h, 0x44, difat_ids[0] if difat_ids else ENDOFCHAIN)
        struct.pack_into("<I", h, 0x48, difat_secs)
        for i in range(109):
            struct.pack_into("<I", h, 0x4C + 4 * i, fat_ids[i] if i < len(fat_ids) else FREESECT)
        return bytes(h) + b"".join(sectors)


def property_set_stream(fmtid, props, codepage=1252):
    """Build a simple OLE property set stream.
    props: list of (pid, vt, value) with vt in {2:I2, 3:I4, 0x1E:LPSTR, 0xB:BOOL}"""
    entries = []
    for pid, vt, val in props:
        if vt == 2:
            body = struct.pack("<Ihh", 2, val, 0)
        elif vt == 3:
            body = struct.pack("<Ii", 3, val)
        elif vt == 0xB:
            body = struct.pack("<Ihh", 0xB, -1 if val else 0, 0)
        elif vt == 0x1E:
            s = val.encode("cp1252", "replace") + b"\x00"
            s += b"\x00" * ((4 - len(s) % 4) % 4)
            body = struct.pack("<II", 0x1E, len(val) + 1) + s
        else:
            raise ValueError(vt)
        entries.append((pid, body))
    n = len(entries)
    sec_hdr = 8 + 8 * n
    offs = []
    pos = sec_hdr
    for pid, body in entries:
        offs.append((pid, pos))
        pos += len(body)
    section = struct.pack("<II", pos, n)
    for pid, off in offs:
        section += struct.pack("<II", pid, off)
    for pid, body in entries:
        section += body
    head = struct.pack("<HHIi", 0xFFFE, 0, 0x00020006 & 0xFFFF | (2 << 16), 0)
    # byte order, version 0, OS (Win32 = 0x0002 high word), clsid
    head = struct.pack("<HH", 0xFFFE, 0) + struct.pack("<HH", 0x0A00, 0x0002) + b"\x00" * 16
    head += struct.pack("<I", 1) + uuid.UUID(fmtid).bytes_le + struct.pack("<I", 48)
    return head + section
