"""The translated program (run/ddragon_sim, engine/sim.py) frame by frame against the reference's port schedule
(tools/machine.py DDragonPort): after every arcade frame the RAM ($0000-$0FFF but the dead stack below S), the
palette, the fg, the shared RAM, the sprite RAM, the bg, the MCU's RAM, the bank register, the scroll, the sound
commands and the registers at the idle point (CC but H, which only DAA reads); every change of the palette, fg, sprite RAM or bg comes with its flag
(gen.py's writers).

    python games/ddragon/tools/logic_test.py [FRAMES] [--seed N]

Inputs: ref/cover.py's schedule of seed N (default 1).  Reports the 68000 cycles a frame (Musashi, logic only).
"""
from pathlib import Path
import argparse
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine"),
                str(Path(__file__).resolve().parents[1] / "ref")]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import DDragonPort, DSW0
from paths import ROOT, build_dir
import cover

REGIONS = [("pal_written", 0x1000, 0x400), ("fg_written", 0x1800, 0x800), ("spr_written", 0x2800, 0x800),
           ("bg_written", 0x3000, 0x800)]
CTX_R_D0, CTX_R_A5, CTX_R_SR, CTX_CCHI = 116, 136, 140, 112


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--trace", type=int, default=-1, help="frame whose translated labels are logged (the last 80 shown "
                    "where it stops)")
    args = ap.parse_args()
    run = ROOT / "run" / "ddragon_sim"
    sim = Sim(str(run / "DDRAGON.PRG"), run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir("ddragon") / "ddragon_sim.map").items()}
    stops = {sym[n]: n for n in ["sim_wait", "sim_frame_done", "sim_badpc"]}
    mem, cpu = sim.mem, sim.cpu
    g = sym["g_mem"]
    cur_ctx = sym["cur_ctx"]
    dsw1, inputs = cover.schedule(args.seed)
    ref = DDragonPort(DSW0, dsw1)
    mem.w8(sym["dd_dsw"] + 1, dsw1)          # (the start code copies it into in_bytes)
    cycles = [0]
    cur = [-1]
    labels = {}
    if args.trace >= 0:
        tables = sym["main_page_tables"]
        for p in range(32):
            pt = mem.r32(tables + 4 * p)
            if pt and pt != sym["bad_table"]:
                base = mem.r32(pt - 4)
                for off in range(0x2000):
                    w = mem.r16(pt + 2 * off)
                    if w:
                        labels[base + 2 * w] = "M%06X" % ((p << 13) | off)
    trail = []
    tracing = [False]

    def run_to_stop():
        used = 0
        while used < 2_000_000_000:
            if tracing[0]:
                pc = cpu.r_pc()
                if pc in labels:
                    trail.append(labels[pc])
                    if len(trail) >= 200000:
                        (build_dir("ddragon") / "trace_labels.txt").write_text("\n".join(trail) + "\n")
                        raise RuntimeError("frame %d: 200000 labels traced, not done (trace_labels.txt)" % cur[0])
                r = cpu.execute(1)
            else:
                r = cpu.execute(4000)
            used += r.cycles
            pc = cpu.r_pc()
            if pc in stops:
                cycles[0] += used
                return stops[pc]
            if pc == TRAP1:
                sim.gemdos()
            if sim.terminated:
                raise RuntimeError("terminated at %06x: %s" % (pc, sim.log[-3:]))
        raise RuntimeError("frame %d: 68000 budget exceeded at %06x" % (cur[0], cpu.r_pc() - sim.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def compare(f):
        got = mem.r_block(g, 0x3800)
        want = bytearray(ref.mem[:0x3800])
        want[0x2000:0x2200] = ref.comram
        s = ref.main.s
        diff = [i for i in range(0x3800) if got[i] != want[i] and not (0x0F00 <= i < s) and not 0x1400 <= i < 0x1800
                and not 0x2200 <= i < 0x2800]
        if diff:
            raise RuntimeError("frame %d: %d bytes differ: %s" % (f, len(diff), [
                ("%04X" % i, "%02X" % got[i], "%02X" % want[i]) for i in diff[:12]]))
        mr = bytes(mem.r_block(sym["mcu_ram"], 0x27))
        if mr != bytes(ref.mcu.ram256[:0x27]):
            raise RuntimeError("frame %d: the MCU's RAM differs: %s / %s" % (f, mr.hex(), bytes(ref.mcu.ram256[:0x27]).hex()))
        regs = (mem.r8(sym["g_bankreg"]), mem.r8(sym["g_scroll_lo"]), mem.r8(sym["g_scroll_lo"] + 1))
        if regs != (ref.bankreg, ref.scroll_lo[0], ref.scroll_lo[1]):
            raise RuntimeError("frame %d: bank / scroll %s, reference %s" % (f, regs, (ref.bankreg, ref.scroll_lo)))
        c = ref.main
        ctx = mem.r32(cur_ctx)                  # (the selected bank's context)
        r = [mem.r32(ctx + CTX_R_D0 + 4 * k) for k in range(5)]
        a5 = mem.r32(ctx + CTX_R_A5) - g
        cc = (mem.r8(ctx + CTX_CCHI) & 0xF0) | (mem.r16(ctx + CTX_R_SR) & 0x0F)
        want_r = [c.a, c.b, c.x, c.y, c.u]
        if r != want_r or a5 != c.s or (cc & 0xDF) != (c.cc & 0xDF) or mem.r16(sym["port_idle_pc"]) != ref.idle_pc:
            raise RuntimeError("frame %d: registers A B X Y U %s S %04X CC %02X idle %04X; reference %s S %04X CC %02X "
                               "idle %04X" % (f, ["%X" % v for v in r], a5, cc, mem.r16(sym["port_idle_pc"]),
                                              ["%X" % v for v in want_r], c.s, c.cc, ref.idle_pc))

    last = {}
    sound = []

    def flags(f):
        for flag, a, size in REGIONS:
            now = bytes(mem.r_block(g + a, size))
            if flag in last and now != last[flag] and not mem.r8(sym[flag]):
                i = next(i for i in range(size) if now[i] != last[flag][i])
                raise RuntimeError("frame %d: %04X changed without %s (a writer missing in gen.py)" % (f, a + i, flag))
            last[flag] = now
            mem.w8(sym[flag], 0)
        head, tail = mem.r8(sym["snd_head"]), mem.r8(sym["snd_tail"])
        while tail != head:
            sound.append(mem.r8(sym["snd_ring"] + tail))
            tail = (tail + 1) & 0xFF
        mem.w8(sym["snd_tail"], tail)
        mine = [v for fr, v in ref.sound_log]
        if sound != mine:
            raise RuntimeError("frame %d: sound commands %s, reference %s" % (f, sound[-8:], mine[-8:]))

    if run_to_stop() != "sim_wait":
        raise RuntimeError("did not reach sim_wait")
    first = None
    for f in range(args.frames):
        cur[0] = f
        p1, p2, extra, coins = inputs(f)
        if coins:
            ref.coin(coins)
            mem.w8(sym["port_coins"], mem.r8(sym["port_coins"]) | coins)
        ref.inputs[0], ref.inputs[1], ref.inputs[2] = p1, p2, extra
        for k, v in enumerate((p1, p2, extra)):
            mem.w8(sym["in_bytes"] + k, v)
        ref.run_frame_port()
        resume()
        tracing[0] = f == args.trace
        stop = run_to_stop()
        tracing[0] = False
        if f == args.trace:
            (build_dir("ddragon") / "trace_labels.txt").write_text("\n".join(trail) + "\n")
        if trail and stop != "sim_frame_done":
            print("last labels:", " ".join(trail[-80:]))
        if stop != "sim_frame_done":
            raise RuntimeError("frame %d: stopped at %s (6809 pc %04X slot %d)" % (f, stop, mem.r16(sym["badpc"]),
                                                                             mem.r16(sym["badslot"]) // 4))
        compare(f)
        flags(f)
        resume()
        if run_to_stop() != "sim_wait":
            raise RuntimeError("frame %d: not back at sim_wait" % f)
        if f == 100:
            first = cycles[0]
        if f % 1000 == 999:
            print("%d frames identical" % (f + 1), flush=True)
    n = args.frames - 101
    if n > 0:
        print("68000 cycles a frame (Musashi, logic only, frames 101-%d): %.0f" % (args.frames, (cycles[0] - first) / n))
    print("PASS: %d frames: RAM, video RAM, palette, MCU RAM, registers, sound identical; every video change flagged"
          % args.frames)


if __name__ == "__main__":
    main()
