#!/usr/bin/env python3
"""Make a bootable Atari ST floppy image (.ST) that starts one program from its AUTO folder.

    python tools/stdisk.py GAME.PRG GAME.ST         (or: stdisk.disk(name, data, date_time) -> bytes or None)

The program lands in \\AUTO\\: booting the disk (a real drive, a Gotek / GoEX, an emulator) starts it.  The
smallest of the usual formats that holds it is used; the image size tells floppy emulators the geometry:
    720 KB  80 tracks, 2 sides,  9 sectors (737,280 bytes)
    800 KB  80 tracks, 2 sides, 10 sectors (819,200 bytes)
A FAT12 file system as TOS formats it: 512-byte sectors, 2-sector clusters, 2 FATs of 5 sectors, 112 root
entries, media byte F9; the boot sector is not executable (its checksum is not $1234).
"""
import struct
import sys
from pathlib import Path

FORMATS = [(80, 9), (80, 10)]          # (tracks, sectors a track), 2 sides
SPC, RES, NFATS, SPF, NDIRS = 2, 1, 2, 5, 112
CLUSTER = 512 * SPC


def dos_time(dt):
    y, mo, d, h, mi, s = dt
    return (h << 11) | (mi << 5) | (s // 2), ((y - 1980) << 9) | (mo << 5) | d


def entry(name, ext, attr, cluster, size, dt):
    t, d = dos_time(dt)
    return struct.pack("<8s3sB10sHHHI", name.ljust(8).encode(), ext.ljust(3).encode(), attr, bytes(10), t, d,
                       cluster, size)


def capacity(tracks, spt):
    sectors = tracks * 2 * spt
    data = sectors - RES - NFATS * SPF - NDIRS * 32 // 512
    return (data // SPC - 1) * CLUSTER          # (one cluster for the AUTO folder)


def disk(filename, data, dt=(2026, 1, 1, 0, 0, 0)):
    """The image, or None if the program fits no format."""
    for tracks, spt in FORMATS:
        if len(data) <= capacity(tracks, spt):
            break
    else:
        return None
    sectors = tracks * 2 * spt
    img = bytearray(sectors * 512)
    boot = bytearray(512)
    boot[0:2] = b"\x60\x38"                      # (bra: the usual start, never run: the sector is not executable)
    boot[2:8] = b"STEARC"
    boot[8:11] = b"\x5a\x31\x07"                 # serial number
    struct.pack_into("<HBHBHHBHHHH", boot, 11, 512, SPC, RES, NFATS, NDIRS, sectors, 0xF9, SPF, spt, 2, 0)
    if sum(struct.unpack(">256H", boot)) & 0xFFFF == 0x1234:
        boot[10] ^= 1
    img[0:512] = boot

    root = (RES + NFATS * SPF) * 512
    data0 = root + NDIRS * 32
    fat = bytearray(SPF * 512)
    fat[0:3] = b"\xf9\xff\xff"

    def set_fat(n, v):
        o = n * 3 // 2
        if n & 1:
            fat[o] = (fat[o] & 0x0F) | ((v << 4) & 0xF0)
            fat[o + 1] = v >> 4
        else:
            fat[o] = v & 0xFF
            fat[o + 1] = (fat[o + 1] & 0xF0) | (v >> 8)

    name, ext = filename.upper().split(".")
    auto = 2                                     # the AUTO folder: cluster 2; the program from cluster 3 on
    set_fat(auto, 0xFFF)
    first = 3
    n = max(1, (len(data) + CLUSTER - 1) // CLUSTER)
    for i in range(n):
        set_fat(first + i, first + i + 1 if i < n - 1 else 0xFFF)
    for f in range(NFATS):
        img[(RES + f * SPF) * 512:(RES + (f + 1) * SPF) * 512] = fat

    img[root:root + 32] = entry("AUTO", "", 0x10, auto, 0, dt)
    a = data0 + (auto - 2) * CLUSTER
    img[a:a + 32] = entry(".", "", 0x10, auto, 0, dt)
    img[a + 32:a + 64] = entry("..", "", 0x10, 0, 0, dt)
    img[a + 64:a + 96] = entry(name, ext, 0x00, first, len(data), dt)
    o = data0 + (first - 2) * CLUSTER
    img[o:o + len(data)] = data
    return bytes(img)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    img = disk(src.name, src.read_bytes())
    if img is None:
        sys.exit("%s: %d bytes, more than an 800 KB disk holds (%d)" % (src, src.stat().st_size, capacity(80, 10)))
    Path(sys.argv[2]).write_bytes(img)
    print("%s: %d bytes" % (sys.argv[2], len(img)))


if __name__ == "__main__":
    main()
