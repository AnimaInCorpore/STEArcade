"""Build RTHUNDER.PRG (--sim: the Musashi build the logic test runs).

    python games/rthunder/tools/build.py [--sim] [-D NAME=VALUE ...]

Only the sim build exists: the translated CPUs (tools/gen.py) and the runtime (src/core.s).
"""
from pathlib import Path
import argparse
import subprocess
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import gen
from paths import ROOT, build_dir
from toolchain import assemble_link


def snapshot(path, force):
    """the reference's state at its port start (arcade frame 200, both CPUs at their idle points): the tile RAMs, the shared
    RAM with the sprite RAM, the MCU's mailbox, the scroll registers and the CPUs' registers (src/ste.s load_snapshot)"""
    if path.exists() and not force:
        return
    import struct
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ref"))
    from machine import RthunderRule
    m = RthunderRule()
    m.boot()
    hw = bytearray(0x40)
    for dev in (0, 1):
        for layer in (0, 1):
            x = m.xscroll[dev][layer]
            b = dev * 16 + layer * 4
            hw[b], hw[b + 1], hw[b + 2] = x >> 8, x & 0xFF, m.yscroll[dev][layer]
    hw[0x20], hw[0x30] = m.backcolor, m.tilebank
    out = bytes(m.vram[0]) + bytes(m.vram[1]) + bytes(m.shared) + bytes(m.spriteram) + bytes(m.cus30) + bytes(hw)
    for i, bank in ((0, m.bank1), (1, m.bank2)):
        c = m.cpus[i]
        out += struct.pack(">6HBBH", c.a, c.b, c.x, c.y, c.u, c.s, c.cc, bank, 0)
    path.write_bytes(out)
    print("snapshot %s: %d bytes" % (path, len(out)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="the Musashi build the tests drive")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--frames", type=int, default=0, help="VBLs after which the program quits (with --debug: COUNTERS.BIN)")
    ap.add_argument("--tag", help="another run/<tag> folder (default rthunder / rthunder_sim)")
    ap.add_argument("--snap", action="store_true", help="make the start snapshot again")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    if not (ROOT / "assets" / "roms" / "extracted" / "rthunder").is_dir():
        subprocess.run([sys.executable, str(Path(__file__).with_name("prepare.py"))], check=True)
    import assets
    assets.build()
    import parts
    parts.build()
    import json, struct
    dur = build_dir("rthunder") / "snd_dur.json"
    d = {int(k): v for k, v in json.loads(dur.read_text()).items()} if dur.exists() else {}
    (build_dir("rthunder") / "ren_snddur.bin").write_bytes(b"".join(struct.pack(">H", d.get(c, 0)) for c in range(256)))
    report = gen.generate()
    for name in ("main", "sub"):
        r = report[name]
        print("%s: %d instructions, %d unsupported, %d missing targets, %s" % (
            name, r["instructions"], len(r["unsupported"]), len(r["missing"]), r["stats"]))
    tag = args.tag or ("rthunder_sim" if args.sim else "rthunder")
    out = ROOT / "run" / tag / "RTHUNDER.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (["SIM=1"] if args.sim else []) + (["DEBUG=1"] if args.debug else [])
    if args.frames:
        defs.append("FRAMES=%d" % args.frames)
    if not args.sim:
        snapshot(build_dir("rthunder") / "snap.bin", args.snap)
    assemble_link("rthunder", "rthunder.s", tag, str(out), defs)
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
