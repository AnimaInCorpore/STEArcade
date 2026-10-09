"""Where render_frame spends its cycles (Musashi, the Blitter model counted separately): the frames of render_test.py seq,
every instruction of the frames `first`..`first + n` attributed to the nearest symbol before it.

    python profile.py [n] [first] [cheat|finish]      (cheat: lives and invincibility, finish: and "Finish Current Level Now!" every 600 frames, the later stages: see logic_test.py --cheat)
"""
import os, random, re, sys, bisect, collections
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine68k import Register as R
from sim import Sim
from machine import Machine1942
import logic_test as lt

RUN, MAP = lt.RUN, lt.MAP


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 1200
    mode = sys.argv[3] if len(sys.argv) > 3 else ""
    cheat = mode in ("cheat", "finish")
    s = Sim(str(RUN / "1942.PRG"), ram_kib=16384, run_dir=RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    s.bad = sym["z80_badpc"]
    mem, cpu = s.mem, s.cpu
    block = sym["g_block"]
    z = lambda addr: block + addr - 0x8000
    ret = sym["sim_render_ret"]
    lt.run_to(s, {sym["sim_wait"]})
    names = sorted((v, k) for k, v in sym.items() if not re.fullmatch(r"[ZL]x?[0-9A-F_a-z]*\d+|Z[0-9A-F]{4}(_r)?|Lx\d+", k) and v >= sym["init_video"] and v < sym["g_iff"])
    addrs = [v for v, _ in names]
    ref = Machine1942()
    ref.run_to_idle()
    ref.booted = True
    rnd = random.Random(1)
    last = {}
    total = collections.Counter()
    blit = 0
    cpu_cycles = 0
    frames = 0
    f = 0
    warm = 30
    while frames < n + warm:
        ref.sys_in, ref.p1, ref.p2 = lt.inputs(f, rnd)
        if cheat:
            ref.ram[0x101], ref.ram[0x0A5] = 6, 2
            if mode == "finish" and f >= 1000 and f % 600 == 0:
                ref.ram[0xBD0], ref.ram[0x099], ref.ram[0x102] = 7, 1, 0x43
        ref.run_frame_port()
        f += 1
        if f < first:
            continue
        mem.w_block(z(0xCC00), bytes(ref.sprram))
        mem.w_block(z(0xD000), bytes(ref.fg))
        mem.w_block(z(0xD800), bytes(ref.bg))
        mem.w8(z(0xC802), ref.scroll[0])
        mem.w8(z(0xC803), ref.scroll[1])
        mem.w8(z(0xC805), ref.palette_bank)
        # (the harness stands in for the translated code that sets the dirty flags: when the RAM changed since the last frame)
        if bytes(ref.fg) != last.get("fg"):
            mem.w8(sym["fg_dirty"], 1)
        if bytes(ref.bg) != last.get("bg"):
            mem.w8(sym["bg_dirty"], 1)
        last["fg"], last["bg"] = bytes(ref.fg), bytes(ref.bg)
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, ret)
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym["render_frame"])
        mem.set_trace_mode(True)
        count = frames >= warm
        while cpu.r_pc() != ret:
            pc = cpu.r_pc()
            if not count:
                cpu.execute(2000)
                s.blitter.cycles = 0
                continue
            r = cpu.execute(1)
            i = bisect.bisect_right(addrs, pc) - 1
            total[names[i][1]] += r.cycles
            cpu_cycles += r.cycles
            blit += s.blitter.cycles
            total["(blitter)"] += s.blitter.cycles
            s.blitter.cycles = 0
        mem.set_trace_mode(False)
        cpu.w_reg(R.A7, sp + 4)
        mem.w16(sym["prev_idx"], mem.r16(sym["shown_idx"]))      # (the VBL shows the frame)
        mem.w16(sym["shown_idx"], mem.r8(sym["frame_ready"]) - 1)
        mem.w8(sym["frame_ready"], 0)
        frames += 1
    print("%d frames from %d: %d cycles a frame (%d CPU, %d Blitter)" % (n, first, (cpu_cycles + blit) // n, cpu_cycles // n, blit // n))
    for name, c in total.most_common(25):
        print("  %-24s %8d  %5.1f%%" % (name, c // n, 100.0 * c / (cpu_cycles + blit)))


if __name__ == "__main__":
    main()
