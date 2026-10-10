"""Cost of a tick on Musashi (the sim build, the real schedule): game logic, render_frame and the Blitter model per tick,
with the scripted play of the AUTOPLAY build (coin, start, fire, joystick) and MAME's cheats for 1942b (lives E101,
invincibility E0A5, starting level E103).

    python perf_test.py [ticks] [finish] [first] [norender]   (finish: frames between "finish the level" cheats, 0 = off;
                                                              first: ticks not counted; norender: game logic alone;
                                                              profile: game logic alone, cycles by routine and by Z80 region)

Musashi counts the 68000's own cycles: Hatari takes about 1.3 to 1.7 times as many (bus alignment, interrupts, the Blitter's bus).
"""
import os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim
from machine68k import Register as R
import logic_test as lt

RUN, MAP = lt.RUN, lt.MAP
FINISH_AT = 1000          # (the AUTOPLAY build: not before)
AP_DIRS = (0xFF, 0xFE, 0xF7, 0xFD, 0xFA, 0xF6, 0xF9, 0xF5)


def autoplay(f):
    """(SYSTEM, P1) of the AUTOPLAY build at VBL f (period 3000)"""
    r = f % 3000
    sys_in, p1 = 0xFF, 0xFF
    if 700 <= r < 740:
        sys_in &= 0x7F
    if 760 <= r < 800:
        sys_in &= 0xFE
    if r >= 840:
        p1 = AP_DIRS[(r >> 5) & 7] & 0xEF
    return sys_in, p1


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    finish = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    first = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    prof = len(sys.argv) > 4 and sys.argv[4] == "profile"
    norender = len(sys.argv) > 4 and sys.argv[4] in ("norender", "profile")
    s = Sim(str(RUN / "1942.PRG"), ram_kib=16384, run_dir=RUN)      # (the Blitter reads its registers back)
    s.mem.set_trace_mode(not norender or prof)
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    wait, done = sym["sim_wait"], sym["sim_frame_done"]
    s.bad = sym["z80_badpc"]
    mem, cpu = s.mem, s.cpu
    block = sym["g_block"]
    if norender:
        s.mem.w16(sym["render_frame"], 0x4E75)

    def z80(addr):
        return block + addr - 0x8000

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    if lt.run_to(s, {wait}) is None:
        print("68000 stopped in the boot")
        return
    logic, blit, ticknr = [], [], []
    if prof:
        import bisect, collections, re
        names = sorted((v, k) for k, v in sym.items() if v >= sym["start"])
        addrs = [v for v, _ in names]
        zreg = re.compile(r"^Z([0-9A-F]{4})(_r)?$")
        by_name, by_region = collections.Counter(), collections.Counter()
        orig_exec = cpu.execute

        class Counting:                      # (every instruction of the logic frames attributed to the nearest symbol before it)
            counting = False

        def run_to_prof(pcs):
            while True:
                pc = cpu.r_pc()
                if pc in pcs:
                    return pc
                r = orig_exec(1)
                lt.CYCLES[0] += r.cycles
                if Counting.counting:
                    n = names[bisect.bisect_right(addrs, pc) - 1][1]
                    m = zreg.match(n)
                    by_name[n] += r.cycles
                    by_region["Z80 %04X-%04X" % (int(m.group(1), 16) & 0xFFC0, (int(m.group(1), 16) & 0xFFC0) + 63) if m else "runtime " + n] += r.cycles
                if pc == s.bad:
                    return None
    for f in range(ticks):
        sys_in, p1 = autoplay(f)
        mem.w8(z80(0xE101), 6)                              # cheats
        mem.w8(z80(0xE0A5), 2)
        if finish and f >= FINISH_AT and f % finish == 0:   # "Finish Current Level Now!"
            mem.w8(z80(0xEBD0), 7)
            mem.w8(z80(0xE099), 1)
            mem.w8(z80(0xE102), 0x43)
        mem.w8(z80(0xC000), sys_in)
        mem.w8(z80(0xC001), p1)
        mem.w8(z80(0xC002), 0xFF)
        mem.w8(sym["vbl_pending"], 1)
        c0, b0 = lt.CYCLES[0], s.blitter.cycles
        resume()
        if prof:
            Counting.counting = f >= first
        got = run_to_prof({done, wait}) if prof else lt.run_to(s, {done, wait})
        if got is None:
            print("68000 stopped in tick %d at %06X" % (f, cpu.r_pc()))
            return
        c1, b1 = lt.CYCLES[0], s.blitter.cycles
        if got == done:                                     # (the frame is drawn inside the hook: the cost is in c1)
            resume()
            if lt.run_to(s, {wait}) is None:
                print("68000 stopped after tick %d" % f)
                return
        b1 = s.blitter.cycles
        mem.w16(sym["prev_idx"], mem.r16(sym["shown_idx"]))      # the VBL shows the frame
        if mem.r8(sym["frame_ready"]):
            mem.w16(sym["shown_idx"], mem.r8(sym["frame_ready"]) - 1)
            mem.w8(sym["frame_ready"], 0)
        if f >= first:
            logic.append(c1 - c0)
            blit.append(b1 - b0)
            ticknr.append(f)
    n = len(logic)
    tot = sorted(a + b for a, b in zip(logic, blit))
    pct = lambda v, p: sorted(v)[len(v) * p // 100]
    print("%d ticks from %d, finish every %d frames (a 50 Hz frame is 160256 cycles)" % (n, first, finish))
    for name, v in ((("logic" if norender else "cpu"), logic), ("blitter", blit), ("total", tot)):
        print("  %-8s mean %7d  median %7d  90%% %7d  99%% %7d  max %8d" % (name, sum(v) // n, pct(v, 50), pct(v, 90), pct(v, 99), max(v)))
    worst = sorted(zip(logic, ticknr), reverse=True)[:12]
    print("  heaviest ticks (cpu cycles, tick): " + ", ".join("%d@%d" % w for w in worst))
    for limit in (100000, 120000, 140000, 160000):
        print("  ticks over %d: %.1f%%" % (limit, 100.0 * sum(1 for v in tot if v > limit) / n))
    if prof:
        total = sum(by_region.values())
        for title, table in (("by region", by_region), ("by routine", by_name)):
            print(title)
            for k, v in table.most_common(22):
                print("  %-28s %7d a tick  %5.1f%%" % (k, v // n, 100.0 * v / total))


if __name__ == "__main__":
    main()
