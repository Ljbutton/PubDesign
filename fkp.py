"""FDPP / FDPC formatted-disk-page (FKP) handling for the Quill stream."""
import struct

from pubblocks import parse_blocks, ser_blocks


def parse_fkp(d):
    n, unk1, unk2 = struct.unpack_from("<HHI", d, 0)
    ends = list(struct.unpack_from(f"<{n}I", d, 8))
    poffs = list(struct.unpack_from(f"<{n}H", d, 8 + 4 * n))
    runs = []
    for e, po in zip(ends, poffs):
        ln = struct.unpack_from("<I", d, po)[0]
        props = parse_blocks(d, po + 4, po + ln)
        runs.append((e, po, props))
    return (unk1, unk2), runs


def build_fkp(runs, unk1=1, unk2=0):
    """runs: list of (end_stream_offset, prop_blocks). Identical props share storage."""
    n = len(runs)
    out = bytearray(0x200)
    struct.pack_into("<HHI", out, 0, n, unk1, unk2)
    pos = 0x200
    cache = {}
    poffs = []
    for end, props in runs:
        body = ser_blocks(props)
        rec = struct.pack("<I", len(body) + 4) + body
        if rec in cache:
            poffs.append(cache[rec])
            continue
        pos -= len(rec)
        if pos & 1:
            pos -= 1
        out[pos:pos + len(rec)] = rec
        cache[rec] = pos
        poffs.append(pos)
    head_end = 8 + 4 * n + 2 * n
    if head_end > pos:
        raise ValueError("FKP overflow")
    for i, (end, _) in enumerate(runs):
        struct.pack_into("<I", out, 8 + 4 * i, end)
        struct.pack_into("<H", out, 8 + 4 * n + 2 * i, poffs[i])
    return bytes(out)


def fkp_capacity_ok(runs):
    try:
        build_fkp(runs)
        return True
    except ValueError:
        return False
