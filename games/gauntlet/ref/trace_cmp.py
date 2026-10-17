"""Gauntlet: one CPU of the reference board against MAME's debugger trace, instruction for instruction.

    python games/gauntlet/ref/trace_cmp.py main|sound FRAME_FROM FRAME_TO [--keep DIR]

MAME (`gauntlet`, -debug) traces the CPU from the end of frame FRAME_FROM to the end of FRAME_TO with its total
cycles and registers; the board runs to the same frames recording the same at each instruction start.  Prints the
first instruction where the address, the registers or the cycle count (relative to the window's first instruction)
part, with the instructions before it.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Gauntlet
from mame_roms import rompath

TAGS = {"main": "maincpu", "sound": "audiocpu"}
LOG68K = ('{tracelog "T=%d D=%08X,%08X,%08X,%08X,%08X,%08X,%08X,%08X A=%08X,%08X,%08X,%08X,%08X,%08X,%08X,%08X '
          'SR=%04X ",totalcycles,d0,d1,d2,d3,d4,d5,d6,d7,a0,a1,a2,a3,a4,a5,a6,a7,sr}')
LOG6502 = '{tracelog "T=%d A=%02X X=%02X Y=%02X P=%02X S=%02X ",totalcycles,a,x,y,p,sp}'
LINE = re.compile(r"T=(\d+) (.*?) ?([0-9A-F]{4,6}): ")


def mame_trace(tag, f0, f1, out):
    log = LOG68K if tag == "maincpu" else LOG6502
    lua = "\n".join([
        "local dbg = manager.machine.debugger", "local frame = 0",
        "local function on()", "  dbg:command('focus %s')" % tag,
        "  dbg.visible_cpu = manager.machine.devices[':%s']" % tag,
        "  dbg:command('trace t.txt,%s,noloop,%s')" % (tag, log.replace("'", "\\'")), "end",
        "sub = emu.register_frame_done(function()", "  frame = frame + 1",
        "  if frame == %d then on() end" % f0 if f0 else "",
        "  if frame == %d then dbg:command('trace off,%s'); manager.machine:exit() end" % (f1, tag), "end)",
        "on()" if f0 == 0 else "", "dbg:command('go')", ""])
    (out / "t.lua").write_text(lua)
    subprocess.run(["mame", "gauntlet", "-rompath", str(rompath()), "-debug", "-debugger", "none", "-autoboot_script",
                    "t.lua", "-window", "-video", "none", "-sound", "none", "-nothrottle", "-seconds_to_run",
                    str(f1 // 60 + 30), "-skip_gameinfo"], cwd=out, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=7200)
    rows = []
    with open(out / "t.txt") as f:
        for l in f:
            m = LINE.match(l)
            if m:
                rows.append((int(m.group(1)), int(m.group(3), 16), m.group(2), l.rstrip()))
    return rows


def board_trace(which, f0, f1):
    m = Gauntlet()
    while m.frame < f0:
        m.run_frame()
    rows = []
    if which == "main":
        c = m.cpu
        core = m.main.core
        run = core.run

        def traced(n):
            t0 = c.total
            r = run(n)
            for pc, cy in c.take_trace():
                rows.append((t0 + cy, pc, None))
            return r
        c.trace(True)
        core.run = traced
        while m.frame < f1:
            m.run_frame()
        c.trace(False)
        # the registers are not in the core's trace: compare addresses and cycles
        return rows
    c = m.snd_devices.cpu

    def hook():
        pc, a, x, y, p, sp = c.regs()
        rows.append((c.total_cycles(), pc, "A=%02X X=%02X Y=%02X P=%02X S=%02X" % (a, x, y, p, sp)))
    c.hook = hook
    while m.frame < f1:
        m.run_frame()
    return rows


def main():
    args = sys.argv[1:]
    keep = None
    if "--keep" in args:
        keep = Path(args[args.index("--keep") + 1])
        del args[args.index("--keep"):args.index("--keep") + 2]
    which, f0, f1 = args[0], int(args[1]), int(args[2])
    out = keep or Path(tempfile.mkdtemp(prefix="gtrace_"))
    out.mkdir(parents=True, exist_ok=True)
    mame = mame_trace(TAGS[which], f0, f1, out)
    ours = board_trace(which, f0, f1)
    print("MAME %d instructions, board %d" % (len(mame), len(ours)))
    t0m, t0o = mame[0][0], ours[0][0]
    for i, (tm, pm, rm, text) in enumerate(mame):
        if i >= len(ours):
            print("board trace ended at MAME's", text)
            break
        to, po, ro = ours[i]
        if i and tm < mame[i - 1][0]:          # (a reset: MAME's total cycles start again at 0)
            t0m, t0o = tm, to
        if po != pm or (ro is not None and ro != rm) or to - t0o != tm - t0m:
            print("first difference at instruction %d:" % i)
            for k in range(max(0, i - 12), i + 1):
                print("  MAME ", mame[k][3])
            for k in range(max(0, i - 12), min(len(ours), i + 3)):
                print("  board T=%d %s %06X" % (ours[k][0] - t0o + t0m, ours[k][2] or "", ours[k][1]))
            break
    else:
        print("identical")
    if not keep:
        shutil.rmtree(out)


if __name__ == "__main__":
    main()
