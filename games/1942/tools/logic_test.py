"""The translated game (1942.PRG built with --sim) on Musashi against the Z80 reference in the port's schedule: at the
foreground's idle point after every frame's interrupts and tasks (the runtime's `sim_frame_done`) the RAM, the video RAM, the
sprite RAM and the latches are compared.

    python logic_test.py [frames] [--stop] [--cheat] [--two]

--two: a two-player game (two coins, start 2, both joysticks played at random; the turns change at every death).
--cheat: MAME's cheats for 1942b, applied to both machines before every frame: lives E101, invincibility E0A5 and every 600 frames
(from frame 1000) "Finish Current Level Now!" (EBD0, E099, E102), to reach the later stages, bosses and the ending.
"""
import argparse, os, random, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import Machine1942

from paths import ROOT, build_dir
RUN = ROOT / "run" / "1942_sim"
MAP = build_dir("1942") / "1942_sim.map"


def inputs(f, rnd):
    """(SYSTEM, P1, P2): a coin, the start button, then random play"""
    sys_in, p1 = 0xFF, 0xFF
    if 900 <= f < 905:
        sys_in &= 0x7F
    if 940 <= f < 945:
        sys_in &= 0xFE
    if f >= 1000:
        p1 = (0xFF, 0xFF, 0xFE, 0xFD, 0xFB, 0xF7, 0xFA, 0xF6)[(f // 20 + rnd.randrange(2)) % 8]
        if rnd.random() < 0.3:
            p1 &= ~0x10
        if f % 400 < 3:
            p1 &= ~0x20
    return sys_in, p1, 0xFF


def inputs_two(f, rnd):
    """(SYSTEM, P1, P2): two coins, start 2, then both players at random (and coins and start 2 again after the game over)"""
    sys_in, p1, p2 = 0xFF, 0xFF, 0xFF
    if 900 <= f < 905 or 920 <= f < 925 or (f > 3000 and f % 2500 in (0, 1, 2, 20, 21, 22)):
        sys_in &= 0x7F
    if 940 <= f < 945 or (f > 3000 and f % 2500 in (40, 41, 42)):
        sys_in &= 0xFD
    if f >= 1000:
        p1 = (0xFF, 0xFF, 0xFE, 0xFD, 0xFB, 0xF7, 0xFA, 0xF6)[(f // 20 + rnd.randrange(2)) % 8]
        p2 = (0xFF, 0xFE, 0xFD, 0xFB, 0xF7, 0xFA, 0xF6, 0xFF)[(f // 23 + rnd.randrange(2)) % 8]
        if rnd.random() < 0.3:
            p1 &= ~0x10
        if rnd.random() < 0.3:
            p2 &= ~0x10
        if f % 400 < 3:
            p1 &= ~0x20
        if f % 500 < 3:
            p2 &= ~0x20
    return sys_in, p1, p2


CYCLES = [0]                  # 68000 cycles run so far (the frame loop reports the cost of a frame)


def run_to(s, pcs, limit=400_000_000):
    """Run the 68000 until it reaches one of pcs (returns it); None if it ended or ran away."""
    cpu = s.cpu
    total = 0
    while True:
        r = cpu.execute(2000)
        total += r.cycles
        CYCLES[0] += r.cycles
        pc = cpu.r_pc()
        if pc in pcs:
            return pc
        if pc == s.bad or pc == s.bad + 4:
            return None
        if pc == TRAP1:
            s.gemdos()
        elif pc == 0x600 or s.terminated:
            return None
        if total > limit:
            return None


def name_of(sym, pc):
    best = None
    for k, v in sym.items():
        if v <= pc and (best is None or v > best[1]):
            best = (k, v)
    return "%s+%d" % (best[0], pc - best[1]) if best else "?"


def ref_ranges(ref):
    """(name, z80 address, reference bytes) of everything the game's state lives in"""
    return [("RAM E000-EFFF", 0xE000, bytes(ref.ram)), ("sprites CC00", 0xCC00, bytes(ref.sprram)),
            ("characters D000", 0xD000, bytes(ref.fg)), ("background D800", 0xD800, bytes(ref.bg)),
            ("scroll C802", 0xC802, bytes(ref.scroll))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=300)
    ap.add_argument("--prg", default=str(RUN / "1942.PRG"))
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--cheat", action="store_true")
    ap.add_argument("--two", action="store_true")
    ap.add_argument("--audit", action="store_true", help="record the translated instructions that touch the block's unused window "
                    "area (an access there is a site gen.py left unguarded) -> build/wsites_audit_*.pkl")
    a = ap.parse_args()
    s = Sim(a.prg, run_dir=RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    wait, done = sym["sim_wait"], sym["sim_frame_done"]
    s.bad = sym["z80_badpc"]
    block = sym["g_block"]
    s.mem.w16(sym["render_frame"], 0x4E75)          # (rts: the renderer has its own test, render_test.py)
    mem, cpu = s.mem, s.cpu
    audit = {}
    ref = Machine1942()
    if a.audit:
        import bisect, pickle, re
        labels = sorted((v, k) for k, v in sym.items() if re.fullmatch(r"Z[0-9A-F]{4,5}", k))
        lv = [v for v, _ in labels]
        on_access = s.on_access

        def watch(mode, width, addr, value):
            # (the block holds the Z80's $8000-$FFFF first, then $0000-$7FFF: the window area is its first 16 KB, unused
            # but for IY and F' at $BFF0; it holds $FF, which is bank 3: a read of it with bank 3 selected is right as it is)
            if mode == "R" and block <= addr < block + 0x3FE0 and mem.r8(sym["g_bank"]) != 3:
                i = bisect.bisect_right(lv, cpu.r_pc()) - 1
                if i >= 0:
                    audit[labels[i][1]] = audit.get(labels[i][1], 0) + 1
                    if os.environ.get("AUDIT_VERBOSE") and audit[labels[i][1]] < 3:
                        print("  audit", labels[i][1], mode, width, "Z80 %04x" % ((addr - block + 0x8000) & 0xFFFF), "pc %06x" % (cpu.r_pc() - s.base),
                              "g_bank", mem.r8(sym["g_bank"]), "ref bank", ref.bank, "latch", mem.r8(block + 0xC806))
            return on_access(mode, width, addr, value)
        mem.set_trace_func(watch)
        mem.set_trace_mode(True)
    rnd = random.Random(1)

    def z80(addr):                        # Z80 address of the RAM half -> 68k address
        return block + addr - 0x8000

    def resume():                         # emulate the rts of the sim_* routine
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def fail(msg):
        print(msg)
        print("68000 pc %06X (%s) log %s" % (cpu.r_pc(), name_of(sym, cpu.r_pc()), s.log[-3:]))
        print("  d0-d7", " ".join("%08X" % cpu.r_reg(r) for r in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6, R.D7)))
        print("  a0-a7", " ".join("%08X" % cpu.r_reg(r) for r in (R.A0, R.A1, R.A2, R.A3, R.A4, R.A5, R.A6, R.A7)))

    prev = {}

    def compare(f):
        errs = 0
        for name, addr, want in ref_ranges(ref):
            got = bytes(mem.r_block(z80(addr), len(want)))
            d = [i for i in range(len(want)) if got[i] != want[i]]
            if d:
                errs += 1
                print("frame %d: %s differs in %d bytes, first %s" % (f, name, len(d), ["%04X got %02X want %02X" % (addr + i, got[i], want[i]) for i in d[:8]]))
        # the renderer only looks at the character / background RAM after a store set a dirty flag: a change without one is a store site
        # the coverage did not see (translation sets the flags, see gen.py video_sites)
        for name, addr, ln in (("fg", 0xD000, 0x800), ("bg", 0xD800, 0x400)):
            now = bytes(mem.r_block(z80(addr), ln))
            if prev.get(name) is not None and now != prev[name] and not mem.r8(sym[name + "_dirty"]):
                errs += 1
                print("frame %d: the %s RAM changed without its dirty flag (a store site that no coverage run saw)" % (f, name))
            prev[name] = now
            mem.w8(sym[name + "_dirty"], 0)
        if mem.r8(z80(0xC806)) & 3 != ref.bank:
            errs += 1
            print("frame %d: ROM bank %d, reference %d" % (f, mem.r8(z80(0xC806)) & 3, ref.bank))
        if mem.r8(z80(0xC805)) & 3 != ref.palette_bank:
            errs += 1
            print("frame %d: palette bank %d, reference %d" % (f, mem.r8(z80(0xC805)) & 3, ref.palette_bank))
        return errs

    # boot: the first idle
    pc = run_to(s, {wait})
    if pc is None:
        fail("68000 stopped in the boot")
        return
    ref.run_to_idle()
    ref.booted = True
    bad = 0
    print("booted, 68000 at %06X; reference at %04X" % (cpu.r_pc(), ref.cpu.pc))
    if compare(-1):
        bad += 1
    f = 0
    costs = []
    while f < a.frames:
        sys_in, p1, p2 = (inputs_two if a.two else inputs)(f, rnd)
        cyc0 = CYCLES[0]
        ref.sys_in, ref.p1, ref.p2 = sys_in, p1, p2
        if a.cheat:
            pokes = [(0xE101, 6), (0xE0A5, 2)]
            if f >= 1000 and f % 600 == 0:
                pokes += [(0xEBD0, 7), (0xE099, 1), (0xE102, 0x43)]
            for addr, v in pokes:
                ref.ram[addr - 0xE000] = v
                mem.w8(z80(addr), v)
        mem.w8(z80(0xC000), sys_in)
        mem.w8(z80(0xC001), p1)
        mem.w8(z80(0xC002), p2)
        mem.w8(sym["vbl_pending"], 1)
        ref.run_frame_port()
        resume()                           # back from sim_wait: the interrupts and the tasks run
        got = run_to(s, {done, wait})
        if got is None:
            fail("68000 stopped in frame %d" % f)
            return
        if got == done:                    # the frame is drawn: compare, then run on to the next wait
            if compare(f):
                bad += 1
                if a.stop or bad > 5:
                    return
            resume()
            got = run_to(s, {wait})
            if got is None:
                fail("68000 stopped after frame %d" % f)
                return
        else:
            print("frame %d: the foreground idled without a frame to draw" % f)
        costs.append(CYCLES[0] - cyc0)
        if f % 100 == 0:
            print("frame %d ok (%s) pc %06X" % (f, "mismatch" if bad else "same", cpu.r_pc()), flush=True)
        f += 1
    print("compared %d frames, %d with differences" % (f, bad))
    if a.audit:
        out = build_dir("1942") / ("wsites_audit_%s.pkl" % ("two" if a.two else "cheat" if a.cheat else "0"))
        pickle.dump({int(k[1:], 16) for k in audit}, out.open("wb"))
        print("audit: accesses to the unguarded window area by", len(audit), "instructions", sorted(audit.items())[:20], "->", out)
    if costs:
        costs.sort()
        print("68000 cycles per frame (game logic, no drawing; a 50 Hz frame is 160256): mean %d, median %d, 95%% %d, max %d" % (
            sum(costs) // len(costs), costs[len(costs) // 2], costs[len(costs) * 95 // 100], costs[-1]))


if __name__ == "__main__":
    main()
