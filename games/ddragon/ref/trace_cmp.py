"""Double Dragon: one CPU of the reference board against MAME's debugger trace, instruction for instruction.

    python games/ddragon/ref/trace_cmp.py main|sub|sound FRAME_FROM FRAME_TO [--keep DIR]

MAME (`ddragonj`, -debug) traces the CPU from the end of frame FRAME_FROM to the end of FRAME_TO with its total
cycles and registers; the board runs to the same frames recording the same at each instruction start.  Prints the
first instruction where the address, the registers or the cycle count (relative to the window's first instruction)
part, with the instructions before it.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import DDragon
from paths import ROMS

TAGS = {"main": "maincpu", "sub": "sub", "sound": "soundcpu"}
LOG6809 = '{tracelog "T=%d A=%02X B=%02X X=%04X Y=%04X U=%04X S=%04X CC=%02X ",totalcycles,a,b,x,y,u,s,cc}'
LOG6801 = '{tracelog "T=%d A=%02X B=%02X X=%04X S=%04X CC=%02X ",totalcycles,a,b,x,s,cc}'
LINE = re.compile(r"T=(\d+) (.*?) ?([0-9A-F]{4}): ")


def mame_trace(tag, f0, f1, out):
    log = LOG6801 if tag == "sub" else LOG6809
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
    subprocess.run(["mame", "ddragonj", "-rompath", str(ROMS), "-debug", "-debugger", "none", "-autoboot_script",
                    "t.lua", "-window", "-video", "none", "-sound", "none", "-nothrottle", "-seconds_to_run", "300",
                    "-skip_gameinfo"], cwd=out, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3600)
    rows = []
    with open(out / "t.txt") as f:
        for l in f:
            m = LINE.match(l)
            if m:
                rows.append((int(m.group(1)), int(m.group(3), 16), m.group(2), l.rstrip()))
    return rows


def board_trace(which, f0, f1):
    m = DDragon()
    while m.frame < f0:
        m.run_frame()
    c = m.cpus[{"main": 0, "sub": 1, "sound": 2}[which]]
    rows = []
    if which == "sub":
        def hook(cpu):
            rows.append((cpu.cycles, cpu.pc, "A=%02X B=%02X X=%04X S=%04X CC=%02X" % (
                cpu.a, cpu.b, cpu.x, cpu.sp, cpu.cc)))
        c.hook = hook
    else:
        rd_op = c.rd_op
        last = [None]

        def rec(a):
            if c.cycles != last[0]:
                last[0] = c.cycles
                rows.append((c.cycles, a, "A=%02X B=%02X X=%04X Y=%04X U=%04X S=%04X CC=%02X" % (
                    c.a, c.b, c.x, c.y, c.u, c.s, c.cc)))
            return rd_op(a)
        c.rd_op = rec
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
    out = keep or Path(tempfile.mkdtemp(prefix="ddtrace_"))
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
        if po != pm or ro != rm or to - t0o != tm - t0m:
            print("first difference at instruction %d:" % i)
            for k in range(max(0, i - 12), i + 1):
                print("  MAME ", mame[k][3])
            for k in range(max(0, i - 12), min(len(ours), i + 3)):
                print("  board T=%d %s %04X" % (ours[k][0] - t0o + t0m, ours[k][2], ours[k][1]))
            break
    else:
        print("identical")
    if not keep:
        shutil.rmtree(out)


if __name__ == "__main__":
    main()
