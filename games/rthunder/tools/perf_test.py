"""68000 cycles of the pipeline per arcade frame on the simulator (Musashi, the Blitter's HOG bus cycles counted).

    python games/rthunder/tools/perf_test.py [frames] [--seed N] [--skip K] [--every E]

Per arcade frame: mcu_frame, port_frame (both CPUs); every E-th frame also a picture: ren_update, ren_sprites.  Reports the
means over the frames after the first K (the tile cache and the part conversions warm) and the worst picture.  The reference
(tools/machine.py) supplies the inputs and the sprite list the picture needs (the translated CPUs run their own state:
they are only timed, the picture is made from the reference's tile RAM, so the logic's cycles and the picture's are the
same game frame's).  Hatari's figures are the ones that count; this one says where the time goes.
"""
import argparse
import sys
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
    ap.add_argument("frames", nargs="?", type=int, default=900)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--skip", type=int, default=300)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--profile", action="store_true", help="where the picture's CPU cycles go (the PC every 50 cycles, by routine)")
    args = ap.parse_args()
    run = ROOT / "run" / "rthunder_sim"
    s = Sim(str(run / "RTHUNDER.PRG"), run_dir=run)
    sym = {k: v + s.base for k, v in s.symbols(build_dir("rthunder") / "rthunder_sim.map").items()}
    mem, cpu = s.mem, s.cpu

    def run_to(stop):
        total = 0
        while True:
            total += cpu.execute(20000).cycles
            pc = cpu.r_pc()
            if pc == stop:
                return total
            if pc == sym["sim_badpc"]:
                raise RuntimeError("badpc")
            if pc == TRAP1:
                s.gemdos()

    import bisect
    syms = sorted((v, k) for k, v in sym.items() if v >= s.base)
    sv = [v for v, k in syms]
    prof = {}

    def run_prof(stop):
        total = 0
        while True:
            if cpu is None:
                break
            total += cpu.execute(50).cycles
            pc = cpu.r_pc()
            i = bisect.bisect_right(sv, pc) - 1
            k = syms[i][1] if i >= 0 else "?"
            prof[k] = prof.get(k, 0) + 1
            if pc == stop:
                return total
            if pc == sym["sim_badpc"]:
                raise RuntimeError("badpc")
            if pc == TRAP1:
                s.gemdos()

    def call(name):
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_wait"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym[name])
        s.blitter.cycles = 0
        c = (run_prof if args.profile and f_now[0] >= args.skip and name in ("ren_update", "ren_sprites", "mcu_frame") else run_to)(sym["sim_wait"])
        return c, s.blitter.cycles

    f_now = [0]
    mem.set_trace_mode(False)
    run_to(sym["sim_wait"])
    dswa, dswb, inputs = cover.schedule(args.seed)
    m = RthunderRule()
    m.dsw = [dswa, dswb]
    m.boot()
    hw = bytearray(0x40)
    ctx = {0: sym["ctx_main"], 1: sym["ctx_sub"]}
    tables = {0: sym["main_page_tables"], 1: sym["sub_page_tables"]}

    def set_bank(i):
        a = ctx[i]
        bank = m.bank1 if i == 0 else m.bank2
        base = sym["banks_main"] + bank * 0x2000 if i == 0 else sym["rom_sub"] + bank * 0x2000
        mem.w16(a + 96 + 6, 8 + bank)
        mem.w32(a + 12, base)
        mem.w32(a + 32 + 12, base - 0x6000)
        mem.w32(a + 64 + 12, mem.r32(tables[i] + 4 * (8 + bank)))

    def hw_regs():
        hw = bytearray(0x40)
        for dev in (0, 1):
            for layer in (0, 1):
                x = m.xscroll[dev][layer]
                b = dev * 16 + layer * 4
                hw[b], hw[b + 1], hw[b + 2] = x >> 8, x & 0xFF, m.yscroll[dev][layer]
        hw[0x20], hw[0x30] = m.backcolor, m.tilebank
        return bytes(hw)

    def load_state():
        mem.w_block(sym["vram0"], bytes(m.vram[0]))
        mem.w_block(sym["vram1"], bytes(m.vram[1]))
        mem.w_block(sym["shared"], bytes(m.shared) + bytes(m.spriteram))
        mem.w_block(sym["cus30"], bytes(m.cus30))
        mem.w_block(sym["hwregs"], hw_regs())
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
    rows = {"logic": [], "mcu": [], "update": [], "sprites": [], "blit": [], "misses": [], "tmisses": []}
    worst = 0
    for f in range(args.frames):
        f_now[0] = f
        m.in0, m.in1, m.in2 = inputs(f)
        before = bytes(m.cus30)
        m.run_others()
        mem.w_block(sym["cus30"], before)
        for k, v in enumerate((m.in0, m.in1, m.in2)):
            mem.w8(sym["io_in0"] + k, v)
        cm, _ = call("mcu_frame")
        mem.w_block(sym["cus30"], bytes(m.cus30))
        mem.w_block(sym["shared"] + 0x1800, bytes(m.spriteram))
        mem.w8(sym["sprite_latch"], 0)
        cl, _ = call("port_frame")
        m.run_cpus()
        if f % args.every == 0:
            mem.w_block(sym["vram0"], bytes(m.vram[0]))
            mem.w_block(sym["vram1"], bytes(m.vram[1]))
            mem.w_block(sym["hwregs"], hw_regs())
            mem.w16(sym["ren_buf"], f % 3)
            miss0 = mem.r32(sym["pm_miss"])
            tmiss0 = mem.r32(sym["pm_tmiss"])
            cu, _ = call("ren_update")
            mem.set_trace_mode(True)
            cs, cb = call("ren_sprites")
            mem.set_trace_mode(False)
            if f >= args.skip:
                rows["update"].append(cu)
                rows["sprites"].append(cs)
                rows["blit"].append(cb)
                rows["misses"].append(mem.r32(sym["pm_miss"]) - miss0)
                rows["tmisses"].append(mem.r32(sym["pm_tmiss"]) - tmiss0)
                worst = max(worst, cu + cs + cb)
        if f >= args.skip:
            rows["logic"].append(cl)
            rows["mcu"].append(cm)
        load_state()
    if args.profile:
        tot = sum(prof.values())
        print("profile (share of the picture's CPU samples, %d samples):" % tot)
        for k, v in sorted(prof.items(), key=lambda x: -x[1])[:14]:
            print("  %-16s %5.1f%%" % (k, 100.0 * v / tot))

    def mean(v):
        return sum(v) / max(len(v), 1)
    print("frames %d..%d seed %d: logic %.0f, mcu %.0f; per picture: ren_update %.0f, ren_sprites %.0f + Blitter %.0f, "
          "sprite part conversions %.2f, tile parts %.2f; picture total %.0f (worst %d)" % (
              args.skip, args.frames, args.seed, mean(rows["logic"]), mean(rows["mcu"]), mean(rows["update"]),
              mean(rows["sprites"]), mean(rows["blit"]), mean(rows["misses"]), mean(rows["tmisses"]),
              mean(rows["update"]) + mean(rows["sprites"]) + mean(rows["blit"]), worst))


if __name__ == "__main__":
    main()
