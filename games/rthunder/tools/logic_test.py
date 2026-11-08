"""The translated main and sub CPU programs (run/rthunder_sim/RTHUNDER.PRG on Musashi) against the reference's port
schedule (machine.py RthunderRule), frame by frame.

    python games/rthunder/tools/logic_test.py [frames] [--seed N]

The reference boots on MAME's schedule to machine.START and runs both CPUs to their idle points; its state goes into the
simulator (RAM, the CPUs' registers and bank pages).  Every frame: the reference does the vertical blank, the MCU and the
sound CPU (machine.run_others) and the CUS30 RAM (the MCU's) is copied into the simulator; then port_frame runs the
translated CPUs and the reference runs its main and sub CPU (RthunderRule.run_cpus).  Compared: both tile RAMs, the
shared RAM and the sprite RAM, the CUS30 RAM, the hardware registers (scroll, tile bank, back colour), the sprite latch
and both CPUs' registers and bank pages.  The CC bytes the IRQs pushed (H and the flags the code after the idle loop
does not read are not kept by the translation) are left out.  Seeds 0 attract mode, 1-5 random play (ref/cover.py).
"""
import argparse
import sys

import numpy as np
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import RthunderRule
import cover
from paths import ROOT, build_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=600)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steplock", type=int, default=-1, help="frame (after the start) run instruction by instruction "
                    "against the reference (registers compared at every translated 6809 instruction)")
    ap.add_argument("--watch", default="", help="hex offsets of the shared RAM to compare at every label in --steplock")
    ap.add_argument("--render", action="store_true", help="after each frame ren_update runs (the marks the translated stores set) and the window is compared")
    ap.add_argument("--mcu", action="store_true", help="also run src/mcu.s's mcu_frame on the state before the reference's MCU and compare the mailbox bytes it writes")
    ap.add_argument("--trace", action="store_true", help="log the translated labels (slow)")
    ap.add_argument("--skip", type=int, default=0, help="frames the reference runs on without the comparison")
    args = ap.parse_args()
    run = ROOT / "run" / "rthunder_sim"
    s = Sim(str(run / "RTHUNDER.PRG"), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(build_dir("rthunder") / "rthunder_sim.map").items()}
    mem, cpu = s.mem, s.cpu

    import bisect
    labels = []
    for cpu_name, pre in (("main", "M"), ("sub", "S")):
        tb = sym["%s_page_tables" % cpu_name]
        for p in range(0x40):
            pt = mem.r32(tb + 4 * p)
            if pt and pt != sym["bad_table"]:
                for b in range(32):
                    blk = mem.r32(pt + 4 * b)
                    if blk == sym["bad_block"]:
                        continue
                    for off in range(b * 256, b * 256 + 256):
                        a = mem.r32(blk + 4 * (off & 255))
                        if a != sym["%s_badpc" % cpu_name]:
                            labels.append((a, "%s%06X" % (pre, (p << 13) | off)))
    labels.sort()
    lv = [v for v, k in labels]
    trail = []

    def run_to(stop, limit=400_000_000, trace=False):
        total = 0
        bad = sym["sim_badpc"]
        while total < limit:
            if trace or args.trace:
                pc = cpu.r_pc()
                i = bisect.bisect_right(lv, pc) - 1
                if i >= 0 and lv[i] == pc:
                    trail.append(labels[i][1])
                total += cpu.execute(1).cycles
            else:
                total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc == stop:
                return total
            if pc == bad:
                if trail:
                    print("last labels:", " ".join(trail[-40:]))
                print("registers", {r: "%X" % (cpu.r_reg(getattr(R, r)) & 0xFFFFFFFF) for r in (
                    "D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "A0", "A3", "A4", "A5", "A6")})
                raise RuntimeError("badpc %04X (ctx %s) slot %d" % (
                    mem.r16(sym["badpc"]), "main" if mem.r32(sym["badctx"]) == sym["ctx_main"] else "sub",
                    mem.r16(sym["badslot"])))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError("timeout at %06X" % (cpu.r_pc() - s.base))

    run_to(sym["sim_wait"])
    dswa, dswb, inputs = cover.schedule(args.seed)
    m = RthunderRule()
    m.dsw = [dswa, dswb]
    m.boot()
    ctx = {0: sym["ctx_main"], 1: sym["ctx_sub"]}
    tables = {0: sym["main_page_tables"], 1: sym["sub_page_tables"]}

    def put(sym_name, data):
        mem.w_block(sym[sym_name], bytes(data))

    def get(sym_name, n):
        return bytes(mem.r_block(sym[sym_name], n))

    def hw_expected():
        hw = bytearray(0x40)
        for dev in (0, 1):
            for layer in (0, 1):
                x = m.xscroll[dev][layer]
                b = dev * 16 + layer * 4
                hw[b], hw[b + 1], hw[b + 2] = x >> 8, x & 0xFF, m.yscroll[dev][layer]
        hw[0x20], hw[0x30] = m.backcolor, m.tilebank
        return hw

    def set_bank(i):
        a = ctx[i]
        bank = m.bank1 if i == 0 else m.bank2
        base = sym["banks_main"] + bank * 0x2000 if i == 0 else sym["rom_sub"] + bank * 0x2000
        mem.w16(a + 96 + 6, 8 + bank)
        mem.w32(a + 12, base)
        mem.w32(a + 32 + 12, base - 0x6000)
        mem.w32(a + 64 + 12, mem.r32(tables[i] + 4 * (8 + bank)))

    def load_state():
        put("vram0", m.vram[0])
        put("vram1", m.vram[1])
        put("shared", bytes(m.shared) + bytes(m.spriteram))
        put("cus30", m.cus30)
        put("hwregs", hw_expected())
        for i in (0, 1):
            c, a = m.cpus[i], ctx[i]
            set_bank(i)
            vb = mem.r32(a + 32 + 4 * (2 if i == 0 else 0))
            for k, val in enumerate((c.a, c.b, c.x, c.y, c.u)):
                mem.w32(a + 116 + 4 * k, val)
            mem.w32(a + 136, (vb + c.s) & 0xFFFFFFFF)
            mem.w16(a + 140, c.cc & 0x0F)
            mem.w8(a + 112, c.cc & 0xF0)

    load_state()

    def compare(f, pushed):
        bad = []
        want = [("vram0", bytes(m.vram[0])), ("vram1", bytes(m.vram[1])), ("cus30", bytes(m.cus30)),
                ("hwregs", bytes(hw_expected()))]
        sh = bytearray(get("shared", 0x2000))
        ref = bytearray(bytes(m.shared) + bytes(m.spriteram))
        for off in pushed:
            if 0 <= off < len(sh):
                sh[off] = ref[off] = 0
        want.append(("shared+sprites", bytes(ref)))
        for name, ref_ in want:
            got = bytes(sh) if name == "shared+sprites" else get(name.split("+")[0], len(ref_))
            diff = [o for o in range(len(ref_)) if got[o] != ref_[o]]
            if name == "hwregs":
                diff = [o for o in diff if o not in (3, 0x13) and o < 0x40]
            if diff:
                bad.append("%s: %d bytes, first %s" % (name, len(diff), ["%04X %02X/%02X" % (o, got[o], ref_[o])
                                                                       for o in diff[:8]]))
        latch = bool(mem.r8(sym["sprite_latch"]))
        if latch != bool(m.copy_sprites):
            bad.append("sprite latch %s, reference %s" % (latch, bool(m.copy_sprites)))
        for i in (0, 1):
            c, a = m.cpus[i], ctx[i]
            got = [mem.r32(a + 116 + 4 * k) & 0xFF if k < 2 else mem.r32(a + 116 + 4 * k) & 0xFFFF for k in range(5)]
            vb = mem.r32(a + 32 + 4 * (2 if i == 0 else 0))
            sv = (mem.r32(a + 136) - vb) & 0xFFFF
            if got != [c.a, c.b, c.x, c.y, c.u] or sv != c.s:
                bad.append("cpu %d regs %s S %04X, reference %s S %04X" % (
                    i + 1, ["%X" % x for x in got], sv, ["%X" % x for x in (c.a, c.b, c.x, c.y, c.u)], c.s))
            page = mem.r16(a + 96 + 6)
            if page != 8 + (m.bank1 if i == 0 else m.bank2):
                bad.append("cpu %d bank page %d, reference %d" % (i + 1, page, 8 + (m.bank1 if i == 0 else m.bank2)))
        if bad:
            print("frame %d (%d after the start):" % (m.frame, f))
            for b in bad:
                print("   " + b)
            return False
        return True

    addr_of = {}
    for a, k in labels:
        addr_of.setdefault(a, []).append(k)

    def steplock(f):
        """port_frame in the simulator; the reference steps its CPU at every translated label (RthunderPort.run_cpus
        without the schedule: the simulator's order is followed)"""
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_wait"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym["port_frame"])
        for i in (0, 1):                                   # (both take their IRQ first, as run_cpus)
            c = m.cpus[i]
            c.set_irq(True)
            c.step()
            c.set_irq(False)
        ctxs = {sym["ctx_main"]: 0, sym["ctx_sub"]: 1}
        watch = [int(x, 16) for x in args.watch.split(",") if x]
        hist = []
        for n in range(5_000_000):
            pc = cpu.r_pc()
            if pc == sym["sim_wait"]:
                print("frame done without a difference at an instruction")
                return
            labs = addr_of.get(pc)
            i = ctxs.get(cpu.r_reg(R.A6) & 0xFFFFFFFF) if labs else None
            if i is not None:
                c = m.cpus[i]
                done = set()
                for w in watch:
                    refb = m.shared[w] if w < 0x1800 else m.spriteram[w - 0x1800]
                    if mem.r8(sym["shared"] + w) != refb:
                        print("shared %04X differs: %02X, reference %02X before cpu %d at %04X" % (
                            w, mem.r8(sym["shared"] + w), refb, i + 1, c.pc))
                        for h in hist[-14:]:
                            print("   cpu %d %s %s | ref %s %s S %04X" % (h[0] + 1, h[1], ["%X" % x for x in h[2]], h[3],
                                                                         ["%X" % x for x in h[4]], h[5]))
                        return
                while True:
                    want_v = c.pc
                    lab = "%s%06X" % ("MS"[i], want_v)
                    regs = [cpu.r_reg(R.D0) & 0xFF, cpu.r_reg(R.D1) & 0xFF, cpu.r_reg(R.D2) & 0xFFFF,
                            cpu.r_reg(R.D3) & 0xFFFF, cpu.r_reg(R.D4) & 0xFFFF]
                    want = [c.a, c.b, c.x, c.y, c.u]
                    if lab not in labs or lab in done:
                        if done:
                            break
                        lab = sorted(labs)[0]
                    hist.append((i, lab, regs, "%04X" % want_v, want, c.s, (cpu.r_reg(R.A5) & 0xFFFFFFFF)))
                    if want_v != int(lab[1:], 16) or regs != want:
                        print("cpu %d differs before %s (reference at %04X):" % (i + 1, lab, want_v))
                        for h in hist[-14:]:
                            print("   cpu %d %s %s | ref %s %s S %04X" % (h[0] + 1, h[1], ["%X" % x for x in h[2]], h[3],
                                                                         ["%X" % x for x in h[4]], h[5]))
                        return
                    done.add(lab)
                    if not m.idle(i):
                        c.step()
                    else:
                        break
            cpu.execute(1)
        print("no end")

    def call_routine(name):
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_wait"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym[name])
        return run_to(sym["sim_wait"], limit=2_000_000_000)

    if args.render:
        import render_test
        flat = np.load(build_dir("rthunder") / "palfit.npz")["flat"]
    rcycles = []
    cycles = 0
    for f in range(args.frames):
        m.in0, m.in1, m.in2 = inputs(f)
        before = bytes(m.cus30)
        m.run_others()
        if args.mcu:
            put("cus30", before)
            for k, v in enumerate((m.in0, m.in1, m.in2)):
                mem.w8(sym["io_in0"] + k, v)
            call_routine("mcu_frame")
            got = get("cus30", 0x400)
            watch = list(range(0x25C, 0x282)) + [0x189, 0x18A, 0x18B, 0x18C, 0x18D, 0x1A5, 0x1A6, 0x1A7, 0x380]
            dm = [(o, got[o], m.cus30[o]) for o in watch if got[o] != m.cus30[o]]
            if dm:
                print("frame %d: mailbox model differs: %s" % (m.frame, " ".join("%03x:%02x/%02x" % d for d in dm)))
                return 1
        put("cus30", m.cus30)
        mem.w_block(sym["shared"] + 0x1800, bytes(m.spriteram))      # (the vertical blank's sprite buffer copy)
        mem.w8(sym["sprite_latch"], 0)
        pushed = []
        for i in (0, 1):                                # (the CC bytes the IRQs push: 12 bytes below S at the idle point)
            base = 0x4000 if i == 0 else 0
            pushed.append(m.cpus[i].s - 12 - base)
        if f == args.steplock:
            steplock(f)
            return 1
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_wait"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym["port_frame"])
        try:
            cycles += run_to(sym["sim_wait"])
        except RuntimeError as ex:
            print("frame %d (%d after the start): %s" % (m.frame, f, ex))
            return 1
        m.run_cpus()
        if f >= args.skip and not compare(f, pushed):
            print("stopped after %d good frames" % f)
            return 1
        if args.render:
            mem.w16(sym["ren_buf"], f & 1)
            rc = call_routine("ren_update")
            rcycles.append(rc)
            dd = render_test.window_diff(mem, sym, m, flat, "dbuf%d" % (f & 1))
            if dd:
                print("frame %d (%d after the start): ren_update, %d window pixels differ" % (m.frame, f, dd))
                return 1
        if f % 100 == 99:
            print("%d frames ok (%.0f 68000 cycles a frame)" % (f + 1, cycles / (f + 1)), flush=True)
    print("%d frames identical; %.0f 68000 cycles a frame for the two CPUs" % (args.frames, cycles / args.frames))
    if rcycles:
        print("ren_update: mean %.0f, worst %d cycles" % (sum(rcycles) / len(rcycles), max(rcycles)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
