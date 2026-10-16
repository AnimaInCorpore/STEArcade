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


# the YM2151 commands the game sends (tools/sound.py records them on the reference board's sound part)
TUNES = [0x01, 0x03, 0x07, 0x09, 0x0A, 0x0C, 0x0E]
EFFECTS = [0x02, 0x04, 0x0F, 0x10, 0x11, 0x12]


def write_sound(build):
    """the ADPCM player's data (src/sound.s): each sample command's stream decoded here (tools/sound.py: MAME's
    MSM5205 at 6258 Hz, a signed byte a sample) in adpcm_pcm.bin (equal ranges once), and adpcm_index.bin: per command
    $80-$9A its chip (word), its stream's offset and length (longs)"""
    import struct
    import sound
    rom = load("21j-6") + load("21j-7")
    diff = sound.msm_diff()
    pcm, where, index = bytearray(), {}, bytearray()
    for chip, a, b in sound.adpcm_commands():
        if (a, b) not in where:
            data = bytes(v & 0xFF for v in sound.adpcm_stream(chip, a, b, rom, diff))
            where[(a, b)] = (len(pcm), len(data))
            pcm += data
        off, n = where[(a, b)]
        index += struct.pack(">HLL", chip, off, n)
    (build / "adpcm_pcm.bin").write_bytes(bytes(pcm) + b"\0" * (len(pcm) & 1))
    (build / "adpcm_index.bin").write_bytes(bytes(index))
    return len(pcm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--sound", action="store_true", help="record the tunes and effects again")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    prepare()
    build = build_dir("ddragon")
    mcu = load("21jm-0.ic55")
    (build / "mcu.rom").write_bytes(mcu)
    (build / "mcu_info.s").write_text("MCU_SUM equ $%02X\t\t; the MCU ROM's byte sum (its first job)\n" % (sum(mcu) & 0xFF))
    import assets
    assets.build()
    print("ADPCM: %d bytes of decoded samples" % write_sound(build))
    import sound
    print("music_data.s: %d bytes of streams" % sound.build_music(build, TUNES, EFFECTS, again=args.sound))
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
