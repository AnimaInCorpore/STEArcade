"""Where the 68000's time goes (Musashi, CPU cycles plus the Blitter model's bus cycles): the --sim build plays the
scripted game of render_test (coin, start, moves) and the program counter is sampled every SAMPLE cycles; the samples are
charged to the nearest symbol of the map (a label before the pc), summed per symbol and per group.

    python profile.py [first_frame] [last_frame]      (default 1800 4200: the game, not the boot and the attract mode)

Prints the cycles a frame on average per symbol (top 40) and per group, and the share of the frame's 160,000 cycles.
Sampling, not stepping: the figures carry a statistical error (a few %) and Musashi's cycles are instruction counts.
"""
import bisect, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import sim as simmod
from sim import Sim
from paths import ROOT, build_dir
import render_test as rt

first = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
last = int(sys.argv[2]) if len(sys.argv) > 2 else 4200
ONLY = os.environ.get("ONLY")                 # a flag symbol (in_game, in_render): sample only while it is set
SAMPLE = 97                                 # (prime: no beat with loops)
RUN = ROOT / "run" / "digdug_sim"
s = Sim(str(RUN / "DIGDUG.PRG"), ram_kib=16384, run_dir=RUN)
syms = s.symbols(build_dir("digdug") / "digdug.map")
SYM = {k: v + s.base for k, v in syms.items()}
items = sorted((v + s.base, k) for k, v in syms.items())
addrs = [a for a, _ in items]
names = [k for _, k in items]
hist = {}
ctx = [0, 0, 0]                                # cycles: the game's interrupts / the renderer / the rest (the main thread between VBLs, the VBL's own work)
frames_seen = [0]


def charge(pc, c):
    i = bisect.bisect_right(addrs, pc) - 1
    k = names[i] if i >= 0 else "?"
    hist[k] = hist.get(k, 0) + c


def autoplay(f):
    """digdug.s's AUTOPLAY=1400 script (active-low bytes like render_test.script)"""
    in0 = in1 = 0xff
    g = f - 1400
    if g < 0:
        return in0, in1
    if g < 6: in1 &= ~0x10
    if 40 <= g < 46: in1 &= ~0x04
    if g >= 400:
        in0 &= ~(0x02, 0x04, 0x08, 0x01)[(g // 32) % 4]
        if g % 16 < 4: in1 &= ~0x01
    return in0, in1


SCRIPT = autoplay if os.environ.get("AUTOPLAY") else rt.script


def on_frame(sim):
    in0, in1 = SCRIPT(sim.frames)
    sim.mem.w8(syms["in0_kbd"] + s.base, (~in0) & 0xff)
    sim.mem.w8(syms["in1_kbd"] + s.base, (~in1) & 0xff)


def run(n):
    end = s.frames + n
    next_vbl = getattr(s, "_next_vbl", simmod.FRAME_CYCLES)
    total = getattr(s, "_total", 0)
    sample = first <= s.frames < last
    while s.frames < end and not s.terminated:
        r = s.cpu.execute(SAMPLE)
        c = r.cycles
        if s.blitter.cycles:
            c += s.blitter.cycles
            s.blitter.cycles = 0
        total += c
        pc = s.cpu.r_pc()
        if sample:
            if not ONLY or s.mem.r8(SYM[ONLY]):
                charge(pc, c)
            ctx[0 if s.mem.r8(SYM["in_game"]) else 1 if s.mem.r8(SYM["in_render"]) else 2] += c
        if pc == simmod.TRAP1:
            s.gemdos()
        elif pc == 0x600:
            break
        if total >= next_vbl:
            if s.irq(4, 28):
                next_vbl += simmod.FRAME_CYCLES
                s.frames += 1
                on_frame(s)
                sample = first <= s.frames < last
    s._next_vbl = next_vbl
    s._total = total


run(last)
n = last - first
tot = sum(hist.values())
print("frames %d-%d, %d cycles a frame sampled (the frame is %d)" % (first, last, tot // n, simmod.FRAME_CYCLES))
for k, v in sorted(hist.items(), key=lambda kv: -kv[1])[:40]:
    print("  %-24s %8d  %4.1f%%" % (k, v // n, 100.0 * v / tot))


def group(k):
    if k.startswith("Z") and k[1:2].isdigit() or k.startswith("Z_"):
        return "CPU1 translated"
    if k.startswith("Y") and k[1:2].isdigit():
        return "CPU2 translated"
    if k.startswith("X") and k[1:2].isdigit():
        return "CPU3 translated"
    if k.startswith("N5") or k.startswith("n5"):
        return "51XX/53XX"
    return k


g = {}
for k, v in hist.items():
    g[group(k)] = g.get(group(k), 0) + v
print("groups:")
for k, v in sorted(g.items(), key=lambda kv: -kv[1])[:14]:
    print("  %-24s %8d  %4.1f%%" % (k, v // n, 100.0 * v / tot))
print("a frame: the game's interrupts (in_game) %d, the renderer (in_render) %d, the rest (the main thread, the VBL's own code) %d cycles" % (ctx[0] // n, ctx[1] // n, ctx[2] // n))

import re
reg = {}
for k, v in hist.items():
    m = re.fullmatch(r"([ZYX])([0-9A-F]{4})", k)
    if m:
        key = "%s%04X" % (m.group(1), int(m.group(2), 16) & ~0x3F)
        reg[key] = reg.get(key, 0) + v
print("Z80 regions of 64 bytes:")
for k, v in sorted(reg.items(), key=lambda kv: -kv[1])[:24]:
    print("  %-8s %8d  %4.1f%%" % (k, v // n, 100.0 * v / tot))
