"""ROM provenance for the Bubble Bobble port: extract + verify both supported sets.

usage: python bbrom.py            (verify; extract if the extracted dirs are missing/incomplete)
       python bbrom.py --manifest (print the markdown manifest table)

Checks every zip entry against its stored CRC32 and against the expected-CRC table below
(values recorded from the shipped archives on 2026-10-08), refuses anything else.
"""
import hashlib
import os
import sys
import zipfile
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROMS = os.path.join(ROOT, "assets", "roms")

# name -> (size, crc32, role)
COMMON = {
    "a78-01.17": (4096, 0xB1BFB53D, "MC6801 MCU mask ROM ($F000-$FFFF)"),
    "a78-07.46": (32768, 0x4F9A26E8, "sound Z80"),
    "a78-08.37": (32768, 0xAE11A07B, "sub Z80"),
    "a71-25.41": (256, 0x2D0F8545, "sprite strip PROM"),
    "a78-09.12": (32768, 0x20358C22, "gfx plane 0/1"),
    "a78-10.13": (32768, 0x930168A9, "gfx plane 0/1"),
    "a78-11.14": (32768, 0x9773E512, "gfx plane 0/1"),
    "a78-12.15": (32768, 0xD045549B, "gfx plane 0/1"),
    "a78-13.16": (32768, 0xD0AF35C5, "gfx plane 0/1"),
    "a78-14.17": (32768, 0x7B5369A8, "gfx plane 0/1"),
    "a78-15.30": (32768, 0x6B61A413, "gfx plane 2/3"),
    "a78-16.31": (32768, 0xB5492D97, "gfx plane 2/3"),
    "a78-17.32": (32768, 0xD69762D5, "gfx plane 2/3"),
    "a78-18.33": (32768, 0x9F243B68, "gfx plane 2/3"),
    "a78-19.34": (32768, 0x66E9438C, "gfx plane 2/3"),
    "a78-20.35": (32768, 0x9EF863AD, "gfx plane 2/3"),
}
SETS = {
    "bublbobl": ("Japan (Taito, '(c) TAITO CORPORATION 1986')", {
        "a78-06-1.51": (32768, 0x567934B6, "main Z80 $0000-$7FFF"),
        "a78-05-1.52": (65536, 0x9F8EE242, "main Z80 banked ROM, 4 x 16 KiB at $8000"),
    }),
    "bublboblr": ("US (Taito America / Romstar, '(c) 1986 TAITO AMERICA CORP.')", {
        "a78-25.51": (32768, 0x2D901C9D, "main Z80 $0000-$7FFF"),
        "a78-24.52": (65536, 0xB7AFEDC4, "main Z80 banked ROM, 4 x 16 KiB at $8000"),
    }),
}


def expected(setname):
    d = dict(COMMON)
    d.update(SETS[setname][1])
    return d


def verify_zip(setname):
    zp = os.path.join(ROMS, setname + ".zip")
    out = os.path.join(ROMS, "extracted_" + setname)
    exp = expected(setname)
    z = zipfile.ZipFile(zp)
    names = {i.filename for i in z.infolist()}
    if names != set(exp):
        raise SystemExit("%s: entry set mismatch: extra=%s missing=%s" %
                         (setname, sorted(names - set(exp)), sorted(set(exp) - names)))
    os.makedirs(out, exist_ok=True)
    rows = []
    for n, (size, crc, role) in sorted(exp.items()):
        d = z.read(n)
        if len(d) != size or zlib.crc32(d) != crc:
            raise SystemExit("%s/%s: size/CRC mismatch" % (setname, n))
        p = os.path.join(out, n)
        if not os.path.exists(p) or open(p, "rb").read() != d:
            open(p, "wb").write(d)
        rows.append((n, size, crc, hashlib.sha1(d).hexdigest(), role))
    return rows


def main():
    for s in SETS:
        rows = verify_zip(s)
        print("%s: %d files OK -- %s" % (s, len(rows), SETS[s][0]))
        if "--manifest" in sys.argv:
            print("| file | bytes | crc32 | sha1 | role |\n|---|---:|---|---|---|")
            for n, size, crc, sha, role in rows:
                print("| %s | %d | %08x | %s | %s |" % (n, size, crc, sha, role))


if __name__ == "__main__":
    main()
