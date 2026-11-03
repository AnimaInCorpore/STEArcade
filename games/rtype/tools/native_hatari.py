"""Compare the pre-integration baseline and production natives in pinned Hatari.

Uses a private seed-4 replay (ticks 600–3600); canonical fixtures are untouched.
The production renderer and scheduler are used by both builds. --later compares
the new later-stage prototype with current production; --checkpoint accepts a
compressed port state in place of recapturing a reference snapshot.
"""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

from native_audit import BUILD, ROOT, build
import play_inputs
import snapshot
import toolchain


def main():
    global BUILD, build
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", choices=["production", "combined"], default="production")
    ap.add_argument("--later", action="store_true", help="current production versus the later-stage combined prototype")
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--start", type=int, default=600)
    ap.add_argument("--frames", type=int, default=3000, help="logic ticks after the replay start")
    ap.add_argument("--checkpoint", default="", help="compressed port checkpoint instead of recapturing the reference")
    args = ap.parse_args()
    if args.later:
        import later_native_audit as later
        BUILD, build = later.BUILD, later.build
        args.candidate = "combined"
    label = ("later_%d" % args.start) if args.later else args.candidate
    replay = BUILD / ("hatari_replay_%d_%d" % (args.seed, args.start))
    replay.mkdir(parents=True, exist_ok=True)
    os.environ["REPLAY"] = "%d:%d" % (args.seed, args.start)
    if args.checkpoint:
        import pickle
        state = pickle.loads(gzip.decompress(Path(args.checkpoint).read_bytes()))
        assert state["frame"] == args.start
        ctx = state["symbols"]["ctx_main"]
        words = [int.from_bytes(ctx[i:i + 2], "big") for i in range(0, 8, 2)]
        words += list(ctx[8:12])
        words += [int.from_bytes(ctx[i:i + 4], "big") & 65535 for i in range(16, 44, 4)]
        words += [(int.from_bytes(ctx[56:60], "big") - int.from_bytes(ctx[52:56], "big")) & 65535,
                  int.from_bytes(ctx[60:62], "big")]
        data = b"".join(state["memory"][str(base)] for base in
                        (0x40000, 0xC0000, 0xC8000, 0xCC000, 0xD0000, 0xD8000))
        data += state["symbols"]["m72_spritebuf"]
        data += struct.pack(">%dH" % len(words), *words)
        data += state["symbols"]["m72_scroll"] + state["symbols"]["m72_raster"] + state["symbols"]["m72_port02"]
        assert len(data) == 57390, len(data)
        (replay / "snapshot.bin").write_bytes(data)
    else:
        snapshot.write(replay)
    play_inputs.build_dir = lambda game: replay
    sys.argv = ["play_inputs.py", "--seed", str(args.seed), "--start", str(args.start),
                "--frames", str(args.start + args.frames)]
    play_inputs.main()
    reports = {}
    for variant in ("base", args.candidate):
        prg, _ = build(variant)
        assets = prg.parent
        for name in ("snapshot.bin", "play_inputs.bin"):
            p = assets / name
            p.unlink(missing_ok=True)
            shutil.copy2(replay / name, p)
        out = ROOT / ("run/rtype_native_" + label + "_" + variant)
        out.mkdir(parents=True, exist_ok=True)
        for name in ("COUNTERS.BIN", "BORDERS.BIN", "CRASH.TXT", "cmd.fifo"):
            (out / name).unlink(missing_ok=True)
        executable = out / "RTYPE.PRG"
        defines = ["STAGE=1", "DEBUG=1", "PLAYBACK=1"] + (["INVULN=1"] if args.seed >= 8 else [])
        toolchain.assemble_link("rtype", "rtype.s", "native_hw", str(executable), defines)
        hatari = Path.home() / "Work/F030Arcade/third_party/hatari/build/src/hatari"
        tos = Path.home() / "Work/F030Arcade/third_party/tos/tos206de.img"
        command = [str(hatari), "--machine", "ste", "--memsize", "14", "--tos", str(tos),
                   "--fast-boot", "true", "--cpu-exact", "true", "--compatible", "true",
                   "--sound", "off", "--fast-forward", "true", "--confirm-quit", "off",
                   "--statusbar", "false", "--cmd-fifo", "cmd.fifo", "--log-file", "hatari.log", "RTYPE.PRG"]
        print("Hatari", variant, flush=True)
        with (out / "hatari.out").open("w") as log:
            proc = subprocess.Popen(command, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy"))
            try:
                started = time.monotonic()
                while proc.poll() is None and not any((out / name).exists()
                                                       for name in ("COUNTERS.BIN", "CRASH.TXT")):
                    if time.monotonic() - started > 400:
                        raise RuntimeError("Hatari timeout")
                    time.sleep(1)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                proc.wait(timeout=15)
                executable.unlink(missing_ok=True)
        if (out / "CRASH.TXT").exists():
            raise RuntimeError((out / "CRASH.TXT").read_text())
        raw = (out / "COUNTERS.BIN").read_bytes()
        vbl, logic, pictures, dropped, skipped, late = struct.unpack(">6I", raw[:24])
        borders = struct.unpack(">5H", (out / "BORDERS.BIN").read_bytes()[:10])
        reports[variant] = dict(vbl=vbl, logic=logic, pictures=pictures, dropped=dropped,
                                skipped=skipped, late=late, logic_per_s=logic * 50 / vbl,
                                pictures_per_s=pictures * 50 / vbl, borders=list(borders))
        assert logic == args.frames + 1, reports[variant]
        if not args.later:
            assert borders[1:] == (0, 0, 0, 0), reports[variant]
        print(json.dumps(reports[variant]), flush=True)
        (BUILD / (label + "_hatari_comparison.json")).write_text(json.dumps(reports, indent=2) + "\n")
    snap = replay / "snapshot.bin"
    (replay / "snapshot.bin.gz").write_bytes(gzip.compress(snap.read_bytes(), mtime=0))
    snap.unlink()


if __name__ == "__main__":
    main()
