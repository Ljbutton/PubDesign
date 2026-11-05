"""Quill (CHNKINK) text stream: Quill/QuillSub/CONTENTS"""
import struct


class QChunk:
    __slots__ = ("u0", "name", "id", "mid", "name2", "data")

    def __init__(self, name, id, data, name2=None, u0=0x18, mid=b"\x01\x00\x00\x00"):
        self.u0, self.name, self.id, self.mid = u0, name, id, mid
        self.name2 = name2 if name2 is not None else name
        self.data = data

    def __repr__(self):
        return f"QChunk({self.name!r},{self.id},{len(self.data)}b)"


def parse(q):
    header = q[:0x18]
    chunks = []
    lists = []
    off = 0x18
    seen = set()
    while off != 0xFFFFFFFF and off not in seen:
        seen.add(off)
        a, n, nxt = struct.unpack_from("<HHI", q, off)
        lists.append((off, a, n, nxt))
        p = off + 8
        for _ in range(n):
            u0 = struct.unpack_from("<H", q, p)[0]
            name = q[p + 2:p + 6].decode("latin1")
            cid = struct.unpack_from("<H", q, p + 6)[0]
            mid = q[p + 8:p + 12]
            name2 = q[p + 12:p + 16].decode("latin1")
            co, cl = struct.unpack_from("<II", q, p + 16)
            chunks.append((QChunk(name, cid, q[co:co + cl], name2, u0, mid), co))
            p += 24
        off = nxt
    return header, lists, chunks


def chunk_map(chunks):
    m = {}
    for c, _ in chunks:
        m.setdefault(c.name, []).append(c)
    return m
