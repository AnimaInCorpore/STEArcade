"""Where does the ISR time go?  Samples the PC every few instructions during the VBL handler."""
import os, sys, random, bisect, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Sim, RUN, STE
frames = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
s = Sim(RUN / "DKSIM.PRG")
syms = s.symbols(STE / "build" / "dkong.map")
base = s.base; blk = base + syms["z80_block"]
names = sorted((v + base, k) for k, v in syms.items() if not re.fullmatch(r"Z[0-9A-F]{4}(_r)?|spr_\d+_[0-9a-f]", k))
addrs = [a for a, _ in names]
zl = sorted((v + base) for k, v in syms.items() if re.fullmatch(r"Z[0-9A-F]{4}", k))
zmin, zmax = zl[0], zl[-1] + 64
sprmin = min(v + base for k, v in syms.items() if re.fullmatch(r"spr_\d+_[0-9a-f]", k))
sprmax = max(v + base for k, v in syms.items() if re.fullmatch(r"spr_\d+_[0-9a-f]", k)) + 4000
rnd = random.Random(3); joy = 0
acc = collections.Counter()
while s.frames < frames:
    f = s.frames
    s.mem.w8(base + syms["in2_kbd"], 0x80 if 40 <= f < 50 else (0x04 if 80 <= f < 90 else 0))
    if f % 12 == 0: joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18])
    s.mem.w8(base + syms["in0_kbd"], joy)
    s.run_frames(1)
    r = s.cpu.execute(60); s._total += r.cycles
    guard = 0
    while s.mem.r8(base + syms["vbl_busy"]) and guard < 200000:
        pc = s.cpu.r_pc()
        r = s.cpu.execute(30)
        c = r.cycles + s.blitter.cycles
        s.blitter.cycles = 0
        s._total += c
        if zmin <= pc < zmax: key = "z80 (NMI code)"
        elif sprmin <= pc < sprmax: key = "sprite chain routines"
        else:
            i = bisect.bisect_right(addrs, pc) - 1
            key = names[i][1] if i >= 0 else "?"
        acc[key] += c
        guard += 1
tot = sum(acc.values())
for k, v in acc.most_common(14):
    print("%-26s %5.1f%%  %8.0f cycles/frame" % (k, 100 * v / tot, v / frames))
print("total per frame: %.0f" % (tot / frames))
