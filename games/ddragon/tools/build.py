"""Build DDRAGON.PRG (run/ddragon/) for a 4 MB STE, or the simulator variant (--sim: run/ddragon_sim/, the tests)."""
from pathlib import Path
import argparse
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import gen
from machine import load
from paths import build_dir, ROOT, EXTRACTED
from toolchain import assemble_link


def prepare():
    if not (EXTRACTED / "ddragon" / "21j-1-5.26").exists():
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "prepare.py")], check=True)


def write_sound(build):
    """the ADPCM player's data (src/sound.s): both sample ROMs, the driver's command table ($8966 of 21j-0-1: 27 x 3
    bytes), MAME's msm5205 diff_lookup (49 steps x 16 nibbles, words)"""
    import math
    import struct
    (build / "adpcm.bin").write_bytes(load("21j-6") + load("21j-7"))
    snd = load("21j-0-1")
    (build / "adpcm_table.bin").write_bytes(snd[0x0966:0x0966 + 27 * 3] + b"\0")
    nbl = [[1 - 2 * (n >> 3), (n >> 2) & 1, (n >> 1) & 1, n & 1] for n in range(16)]
    diff = []
    for step in range(49):
        sv = math.floor(16.0 * pow(11.0 / 10.0, step))
        for n in range(16):
            sign, b2, b1, b0 = nbl[n]
            diff.append(sign * (sv * b2 + sv // 2 * b1 + sv // 4 * b0 + sv // 8))
    (build / "msm_diff.bin").write_bytes(struct.pack(">784h", *diff))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    prepare()
    build = build_dir("ddragon")
    mcu = load("21jm-0.ic55")
    (build / "mcu.rom").write_bytes(mcu)
    (build / "mcu_info.s").write_text("MCU_SUM equ $%02X\t\t; the MCU ROM's byte sum (its first job)\n" % (sum(mcu) & 0xFF))
    import assets
    assets.build()
    write_sound(build)
    report = gen.generate()
    print("translation: %d instructions, %d unsupported, %d missing, %s" % (
        report["instructions"], len(report["unsupported"]), len(report["missing"]), report["stats"]))
    if report["unsupported"]:
        raise RuntimeError("unsupported translated instructions: %s" % report["unsupported"][:5])
    tag = "ddragon_sim" if args.sim else "ddragon"
    out = ROOT / "run" / tag / "DDRAGON.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines)
    if args.sim:
        defs.append("SIM=1")
    if args.debug:
        defs.append("DEBUG=1")
    if args.frames:
        defs.append("FRAMES=%d" % args.frames)
    assemble_link("ddragon", "ddragon.s", tag, str(out), defs)
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
