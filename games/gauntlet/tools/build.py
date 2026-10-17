"""Build GAUNTLET.PRG (run/gauntlet/) for a 4 MB STE, or the simulator variant (--sim: run/gauntlet_sim/).

    venv/bin/python games/gauntlet/tools/build.py [--sim] [-D NAME=VALUE ...]

Steps: tools/patch.py (the program image), tools/boot.py (the BIOS's hand-off, once), the data the runtime embeds
(build/gauntlet/: boot_ste.bin relocated, slapstic_banks.bin, chars_2p.bin), src/gauntlet.s linked at RT_BASE as a
raw image (runtime.bin), src/loader.s around it (the .PRG).
"""
import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from paths import build_dir, ROOT, EXTRACTED, VASM, VLINK, RT_INCLUDE, src_dir

RUNTIME_LIMIT = 0x200000                  # (render.s's fixed buffers begin here: the runtime must end below)


def prepare():
    if not (EXTRACTED / "gauntlet" / "136037-1307.9a").exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "prepare.py")], check=True)


def boot_ste(build):
    """boot.bin with the windows' pointers and the registers relocated (as tools/stemodel.py load_boot)"""
    from patch import ste_addr
    if not (build / "boot.bin").exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "boot.py")], check=True)
    d = bytearray((build / "boot.bin").read_bytes())
    for o in range(0x4000, 0x5000 - 3, 2):                 # $904000-$904FFF: the BIOS's variables and stack
        v = struct.unpack(">I", d[o:o + 4])[0]
        if ste_addr(v) is not None:
            d[o:o + 4] = struct.pack(">I", ste_addr(v))
    k = 0x6000 + 0x800 + 0x2000 + 0x400
    regs = list(struct.unpack(">16I", d[k:k + 64]))
    regs = [ste_addr(v) if ste_addr(v) is not None else v for v in regs]
    d[k:k + 64] = struct.pack(">16I", *regs)
    (build / "boot_ste.bin").write_bytes(bytes(d))


def data_files(build):
    from machine import main_rom
    from video import Video
    (build / "slapstic_banks.bin").write_bytes(main_rom()[0x38000:0x40000])
    v = Video()
    out = bytearray()
    for c in range(1024):
        for y in range(8):
            row = v.chars[c, y]
            p0 = sum((int(row[x]) & 1) << (7 - x) for x in range(8))
            p1 = sum(((int(row[x]) >> 1) & 1) << (7 - x) for x in range(8))
            out += bytes((p0, p1))
    (build / "chars_2p.bin").write_bytes(bytes(out))


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(r.returncode)


def assemble(tag, defines):
    build = build_dir("gauntlet")
    src = src_dir("gauntlet")
    inc = ["-I", str(build), "-I", str(RT_INCLUDE)]
    defs = ["-D" + d for d in defines]
    obj = build / (tag + "_rt.o")
    run([VASM, "-Fvobj", "-quiet", "-nowarn=2047"] + inc + defs + ["-o", str(obj), "gauntlet.s"], src)
    rt = build / "runtime.bin"
    mp = build / (tag + "_rt.map")
    run([VLINK, "-b", "rawbin1", "-Ttext", "0x50000", "-M" + str(mp), "-o", str(rt), str(obj)], src)
    data = rt.read_bytes()
    data += bytes(-len(data) % 4)
    rt.write_bytes(data)
    end = None
    for line in mp.read_text().splitlines():
        m = re.match(r"\s+([0-9a-f]{8}) \.bss\s+\(size ([0-9a-f]+)", line)
        if m:
            end = int(m.group(1), 16) + int(m.group(2), 16)
    if end is None or end > RUNTIME_LIMIT:
        sys.exit("the runtime ends at %s, beyond $%06X (render.s's buffers)" % (end and hex(end), RUNTIME_LIMIT))
    (build / "runtime_len.i").write_text("RUNTIME_LEN = %d\n" % len(data))
    out = ROOT / "run" / tag / "GAUNTLET.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    lobj = build / (tag + "_loader.o")
    run([VASM, "-Fvobj", "-quiet", "-nowarn=2047"] + inc + defs + ["-o", str(lobj), "loader.s"], src)
    run([VLINK, "-b", "ataritos", "-s", "-o", str(out), str(lobj)], src)
    return out, end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    prepare()
    build = build_dir("gauntlet")
    import patch
    patch.build()
    boot_ste(build)
    data_files(build)
    import assets
    assets.build()                        # (src/render.s's data: tools/assets.py)
    import sound                          # build/gauntlet/sound_data.s, gauntlet_speech/_adpcm.bin (src/sound_out.s)
    sound.build(build)
    defs = list(args.defines) + (["SIM=1"] if args.sim else [])
    out, end = assemble("gauntlet_sim" if args.sim else "gauntlet", defs)
    print("built %s, %d bytes; the runtime $%06X-$%06X" % (out, out.stat().st_size, 0x50000, end))


if __name__ == "__main__":
    main()
