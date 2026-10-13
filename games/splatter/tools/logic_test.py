"""The translated main and sub CPU programs (run/splatter_sim/SPLATTER.PRG on Musashi) against the reference's port
schedule (machine.py run_frame_port), frame by frame.

    venv/bin/python games/splatter/tools/logic_test.py [frames] [--seed N]

The reference boots on MAME's schedule to machine.START; its state goes into the simulator (the virtual space's RAM
and I/O pages, the CPUs' registers and MMU state, the key custom's random seed).  Every frame: the reference does the
vertical blank, the MCU and the sound CPU (machine.run_others) and their memory (TRIRAM, the CUS30 RAM, the latched
sprite list) is copied into the simulator; then port_frame runs the translated CPUs and the reference runs its main and
sub CPU.  Compared: the work RAM, TRIRAM, the CUS30 RAM, the tile RAM, the palette pages, the scratch and sprite RAM,
the CUS123 control and both CPUs' registers.  Seeds above 3 press coin, start and random inputs as ref/cover.py does;
seeds 11-17 start stage seed - 10 (the Stage Select DIP switch).
"""
import argparse
import random
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import Splatter, START
from paths import ROOT, build_dir

VIO0 = 0x2E0000
PROFILE = None                  # (tools/profile.py: dict(start, frames, stepper))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=600)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--trace", type=int, default=-1, help="frame (after the start) whose translated labels are logged")
    ap.add_argument("--steplock", type=int, default=-1, help="frame (after the start) run instruction by instruction "
                    "against the reference interpreter (registers compared at every 6809 instruction)")
    args = ap.parse_args()
    run = ROOT / "run" / "splatter_sim"
    s = Sim(str(run / "SPLATTER.PRG"), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(build_dir("splatter") / "splatter_sim.map").items()}
    mem, cpu = s.mem, s.cpu

    import bisect
    # the translated instructions' addresses, from the dispatcher's page tables (label -> 6809 pc); about 2 GB, so only
    # for --trace, --steplock and tools/profile.py
    labels = []
    need_labels = args.trace >= 0 or args.steplock >= 0 or PROFILE
    for cpu_name, pre in (("main", "M"), ("sub", "S")) if need_labels else ():
        tables = sym["%s_page_tables" % cpu_name]
        for p in range(0x400):
            pt = mem.r32(tables + 4 * p)
            if pt:
                for off in range(0x2000):
                    a = mem.r32(pt + 4 * off)
                    if a != sym["%s_badpc" % cpu_name]:
                        labels.append((a, "%s%06X" % (pre, (p << 13) | off)))
    labels.sort()
    lv = [v for v, k in labels]
    trail = []

    def run_to(stop, limit=400_000_000, trace=False):
        total = 0
        bad = sym["sim_badpc"]
        while total < limit:
            if trace:
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
                    print("last labels:", " ".join(trail[-80:]))
                regs = {r: cpu.r_reg(getattr(R, r)) & 0xFFFFFFFF for r in ("D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7",
                                                                          "A0", "A1", "A5", "A6", "A7")}
                print("registers", {k: "%X" % v for k, v in regs.items()}, "ctx_main %X ctx_sub %X" % (sym["ctx_main"], sym["ctx_sub"]))
                a7 = regs["A7"]
                print("68000 stack", ["%08X" % mem.r32(a7 + 4 * k) for k in range(6)])
                for nm in ("cpu_frame", "port_frame", "main_idle", "main_dispatch", "main_io_w", "mmu_w"):
                    print("   %s %X" % (nm, sym.get(nm, 0)))
                raise RuntimeError("badpc %04X (ctx %s)" % (mem.r16(sym["badpc"]),
                                                            "main" if mem.r32(sym["badctx"]) == sym["ctx_main"] else "sub"))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError("timeout at %06X" % (cpu.r_pc() - s.base))

    run_to(sym["sim_wait"])
    m = Splatter()
    m.boot()
    vio, rom, nopage = sym["vio"], sym["rom_image"], sym["nopage"]

    def page_base(p):
        if p >= 0x200:
            r = p * 0x2000 - 0x400000
            return rom + (r >> 19) * 0x10000 + (r & 0xFFFF)
        if 0x170 <= p <= 0x183:
            return vio + (p - 0x170) * 0x2000
        return nopage

    def vio_put(virt, data):
        mem.w_block(vio + virt - VIO0, bytes(data))

    def vio_get(virt, n):
        return bytes(mem.r_block(vio + virt - VIO0, n))

    # the reference's state into the simulator
    vio_put(0x2E0000, bytes(m.c116_rd(o) for o in range(0x8000)))
    vio_put(0x2F0000, m.vram)
    vio_put(0x2FC000, m.scratch)
    vio_put(0x2FC800, m.spriteram)
    vio_put(0x2FD000, m.control)
    vio_put(0x2FE000, m.sound_ram)
    vio_put(0x2FF000, m.triram)
    vio_put(0x300000, m.ram)
    mem.w32(sym["rand_seed"], m.rand_seed)
    mem.w_block(sym["key_regs"], bytes(m.key[:8]))
    ctx = {0: sym["ctx_main"], 1: sym["ctx_sub"]}
    for i in (0, 1):
        c, a = m.cpus[i], ctx[i]
        for k in range(8):
            p = m.offsets[i][k] >> 13
            mem.w16(a + 96 + 2 * k, p)
            mem.w32(a + 4 * k, page_base(p))
            mem.w32(a + 32 + 4 * k, (page_base(p) - k * 0x2000) & 0xFFFFFFFF)
        assert c.s <= 0x2000, "S outside slot 0"
        mem.w8(a + 112, c.cc)
        for k, val in enumerate((c.a, c.b, c.x, c.y, c.u)):
            mem.w32(a + 116 + 4 * k, val)
        mem.w32(a + 136, page_base(m.offsets[i][0] >> 13) + c.s)
        mem.w16(a + 140, c.cc & 0x0F)

    def compare(f):
        bad = []
        for name, virt, ref in (("ram", 0x300000, m.ram), ("triram", 0x2FF000, m.triram), ("snd", 0x2FE000, m.sound_ram),
                                ("vram", 0x2F0000, m.vram), ("scratch", 0x2FC000, m.scratch),
                                ("control", 0x2FD000, m.control),
                                ("palette", 0x2E0000, bytes(m.c116_rd(o) for o in range(0x8000)))):
            got = vio_get(virt, len(ref))
            diff = [o for o in range(len(ref)) if got[o] != ref[o]]
            if name == "ram":
                # the CC bytes the IRQs pushed (machine.run_cpu): H and the flags the code after the idle loop does not
                # read are not kept by the translation (gen_info.json)
                for i, a in m.irq_cc_addr.items():
                    o = a - 0x300000
                    if o in diff and not (got[o] ^ ref[o]) & ~dontcare[i] & 0xFF:
                        diff.remove(o)
            if name == "palette":                       # (the C116 registers: the first of their mirrors)
                diff = [o for o in diff if (o & 0x1800) != 0x1800 or 0x1800 <= o < 0x1810]
            if diff:
                bad.append("%s: %d bytes, first %s" % (name, len(diff), ["%06X %02X/%02X" % (virt + o, got[o], ref[o])
                                                                        for o in diff[:6]]))
        spr = vio_get(0x2FC800, 0x800)
        diff = [o for o in range(0x800) if spr[o] != m.spriteram[o] and o % 16 < 10]
        if diff and os.environ.get("DUMPSPR"):
            for e in range(0, 0x300, 16):
                print("%03X %s | %s" % (e, spr[e + 4:e + 10].hex(), bytes(m.spriteram[e + 4:e + 10]).hex()))
        if diff:
            bad.append("sprites: %d bytes, first %s" % (len(diff), ["%03X %02X/%02X" % (o, spr[o], m.spriteram[o])
                                                                   for o in diff[:6]]))
        for i in (0, 1):
            c, a = m.cpus[i], ctx[i]
            got = [mem.r32(a + 116 + 4 * k) & 0xFF if k < 2 else mem.r32(a + 116 + 4 * k) for k in range(5)]
            want = [c.a, c.b, c.x, c.y, c.u]
            sv = mem.r32(a + 136) - (page_base(m.offsets[i][0] >> 13))
            if got != want or sv != c.s:
                bad.append("cpu %d regs %s S %04X, reference %s S %04X" % (i, ["%X" % x for x in got], sv,
                                                                          ["%X" % x for x in want], c.s))
            pages = [mem.r16(a + 96 + 2 * k) for k in range(8)]
            if pages != [o >> 13 for o in m.offsets[i]]:
                bad.append("cpu %d pages %s, reference %s" % (i, [hex(p) for p in pages],
                                                             [hex(o >> 13) for o in m.offsets[i]]))
        if bad:
            print("frame %d (%d after the start):" % (m.frame, f))
            for b in bad:
                print("   " + b)
            return False
        return True

    import json
    info = json.loads((build_dir("splatter") / "gen_info.json").read_text())
    dontcare = {0: 0x20 | (0x0F & ~info["main"]["idle_flags"]), 1: 0x20 | (0x0F & ~info["sub"]["idle_flags"])}
    print("CC bits the IRQs push that the translation does not keep:", {k: hex(v) for k, v in dontcare.items()})
    addr_of = {}
    for v, k in labels:                         # (an instruction without code shares its address with the next)
        addr_of.setdefault(v, []).append(k)

    def steplock(f):
        """port_frame in the simulator, a 6809 instruction of the reference at every translated label"""
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_wait"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym["port_frame"])
        ctxs = {sym["ctx_main"]: 0, sym["ctx_sub"]: 1}
        started = {0: False, 1: False}
        hist = []
        for n in range(3_000_000):
            pc = cpu.r_pc()
            if pc == sym["sim_wait"]:
                print("frame done without a difference")
                return
            if pc == sym["sim_badpc"]:
                i = ctxs.get(cpu.r_reg(R.A6) & 0xFFFFFFFF)
                c = m.cpus[i]
                c.step()
                print("badpc %04X; the reference went to %06X (slot pages %s) after:" % (
                    mem.r16(sym["badpc"]), m.offsets[i][c.pc >> 13] | (c.pc & 0x1FFF),
                    " ".join("%X" % (o >> 13) for o in m.offsets[i])))
                for h in hist[-12:]:
                    print("   cpu %d %s %s | ref %s %s" % (h[0], h[1], ["%X" % x for x in h[2]], h[3],
                                                            ["%X" % x for x in h[4]]))
                return
            for lab in sorted(addr_of.get(pc, ())):
                i = ctxs.get(cpu.r_reg(R.A6) & 0xFFFFFFFF)
                if i is not None:
                    c = m.cpus[i]
                    if not started[i]:
                        # the reference takes its interrupt here (machine.run_cpu)
                        m.irq_cc_addr[i] = 0
                        c.set_irq(True)
                        c.step()
                        c.set_irq(False)
                        started[i] = True
                    want_v = m.offsets[i][c.pc >> 13] | (c.pc & 0x1FFF)
                    got_v = int(lab[1:], 16)
                    regs = [cpu.r_reg(R.D0) & 0xFF, cpu.r_reg(R.D1) & 0xFF, cpu.r_reg(R.D2) & 0xFFFF,
                            cpu.r_reg(R.D3) & 0xFFFF, cpu.r_reg(R.D4) & 0xFFFF]
                    want = [c.a, c.b, c.x, c.y, c.u]
                    hist.append((i, lab, regs, "%06X" % want_v, want))
                    if got_v != want_v or regs != want:
                        print("cpu %d differs before %s (reference at %06X):" % (i, lab, want_v))
                        for h in hist[-12:]:
                            print("   cpu %d %s %s | ref %s %s" % (h[0], h[1], ["%X" % x for x in h[2]], h[3],
                                                                    ["%X" % x for x in h[4]]))
                        return
                    c.step()
            cpu.execute(1)
        print("no end")

    rng = random.Random(args.seed)
    play = args.seed > 3
    hold = 0
    cycles = 0
    stage = args.seed - 10 if 11 <= args.seed <= 17 else 0
    if stage:
        m.dipsw &= ~0x04
    tile_frames = flag_frames = all_frames = 0
    probe = {int(x, 16) for x in os.environ.get("PROBE_PCS", "").split(",") if x}
    probe_frame = int(os.environ.get("PROBE_FRAME", "-1"))     # (debugging: the sub CPU at these pcs in that frame)
    probe_on = [False]
    if probe:
        c1 = m.cpus[1]
        step1 = c1.step

        def step_probe():
            if probe_on[0] and c1.pc in probe:
                print("probe %04X A %02X B %02X X %04X Y %04X U %04X [51] %02X%02X" % (c1.pc, c1.a, c1.b, c1.x, c1.y, c1.u, m.ram[0x51], m.ram[0x52]))
            return step1()
        c1.step = step_probe
    for f in range(args.frames):
        probe_on[0] = f == probe_frame
        if stage and 130 <= f < 430:
            k, phase = (f - 180) // 30, (f - 180) % 30
            if f == 130:
                m.control_in[0] = 0x7F
            elif 0 <= k < stage - 1:
                m.control_in[0] = 0xFE if phase < 6 else 0xFF
            elif k == stage - 1 and f >= 180:
                m.control_in[0] = 0xEF if phase < 6 else 0xFF
            else:
                m.control_in[0] = 0xFF
        elif play:
            if f == 30:
                m.coin_in &= ~0x10
            elif f == 36:
                m.coin_in |= 0x10
            elif f == 130:
                m.control_in[0] &= ~0x80
            elif f == 136:
                m.control_in[0] |= 0x80
            elif f > (430 if stage else 180):
                if hold <= 0:
                    bits = rng.choice([0, 1, 2, 4, 8, 0x10, 0x20, 0x11, 0x12, 0x21, 0x22, 0x01, 0x01])
                    m.control_in[0] = (0xFF & ~bits) | 0x80
                    hold = rng.randint(2, 40)
                hold -= 1
        m.run_others()
        vio_put(0x2FF000, m.triram)
        vio_put(0x2FE000, m.sound_ram)
        vio_put(0x2FC800, m.spriteram)
        # port_frame, returning to sim_wait
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_wait"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym["port_frame"])
        tile0 = vio_get(0x2F0000, 0x8000)          # (the render's writer flags: tools/gen.py tile_marks)
        mem.w8(sym["tile_written"], 0)
        mem.w8(sym["tile_written_fix"], 0)
        mem.w8(sym["tile_fix_all"], 0)
        mem.w_block(sym["tile_fix_rows"], bytes(56))
        if f == args.steplock:
            steplock(f)
            return 1
        try:
            if PROFILE and PROFILE["start"] <= f < PROFILE["start"] + PROFILE["frames"]:
                cycles += PROFILE["stepper"](cpu, mem, sym, labels, sym["sim_wait"])
            else:
                cycles += run_to(sym["sim_wait"], trace=f == args.trace)
        except RuntimeError as ex:
            print("frame %d (%d after the start): %s" % (m.frame, f, ex))
            return 1
        tile1 = vio_get(0x2F0000, 0x8000)
        if tile0[:0x7000] != tile1[:0x7000]:
            tile_frames += 1
            if not mem.r8(sym["tile_written"]):
                print("frame %d: tile RAM (layers 0-3) changed without tile_written" % f)
                return 1
        if tile0[0x7000:] != tile1[0x7000:] and not mem.r8(sym["tile_written_fix"]):
            print("frame %d: tile RAM (the fixed layers) changed without tile_written_fix" % f)
            return 1
        if not mem.r8(sym["tile_fix_all"]):
            for k, base in enumerate((0x7010, 0x7810)):
                for r in range(28):
                    a = base + 72 * r
                    if tile0[a:a + 72] != tile1[a:a + 72] and not mem.r8(sym["tile_fix_rows"] + 28 * k + r):
                        print("frame %d: fixed layer %d row %d changed without its tile_fix_rows flag" % (f, 4 + k, r))
                        return 1
        flag_frames += bool(mem.r8(sym["tile_written"]))
        all_frames += bool(mem.r8(sym["tile_fix_all"]))
        m.run_cpu(0)
        m.run_cpu(1)
        if not compare(f):
            print("stopped after %d good frames" % f)
            if trail and os.environ.get("TRAIL"):
                print("labels:", " ".join(t for t in trail if t[:1] == os.environ["TRAIL"]))
            return 1
        if f % 100 == 99:
            print("%d frames ok (%.0f 68000 cycles a frame)" % (f + 1, cycles / (f + 1)), flush=True)
    print("%d frames identical; %.0f 68000 cycles a frame for the two CPUs" % (args.frames, cycles / args.frames))
    print("tile RAM (layers 0-3) changed in %d frames, tile_written set in %d; tile_fix_all set in %d" % (
        tile_frames, flag_frames, all_frames))
    return 0


if __name__ == "__main__":
    sys.exit(main())
