"""Frame by frame: the translated program (run/mpatrol_sim, Musashi) against the reference's port schedule
(machine.MoonPatrolPort.run_frame_port) through the coverage seeds' play (ref/cover.py: inputs, cheats, DIP switches).

    python games/mpatrol/tools/logic_test.py [frames] [--seed N]

Compared every frame: the text RAM $8000-$87FF and the RAM $E000-$E7FF (the stack bytes only a merged
`push rr; pop rr'` would have written are dead below SP and left out), the sprite RAM $C800-$C8FF, the six video
registers (io_regs), the flip latch and the sound commands of the frame.  Reports the 68000 cycles of the logic a
frame (Musashi; no drawing yet).
"""
from pathlib import Path
import argparse
import random
import re
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import MoonPatrolPort
from paths import ROOT, build_dir
import cover

BUILD = build_dir("mpatrol")
REGS = (0, 2, 3, 4, 5, 6)              # io_regs by port >> 5 -> machine.regs (scroll, bg1 x, bg1 y, bg2 x, bg2 y, ctl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    program = ROOT / "run" / "mpatrol_sim" / "MPATROL.PRG"
    s = Sim(str(program), run_dir=program.parent)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / "mpatrol_sim.map").items()}
    mem, cpu = s.mem, s.cpu
    wait, done, bad = sym["sim_wait"], sym["sim_frame_done"], sym["z80_badpc"]
    a6 = sym["g_block"] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    m = MoonPatrolPort(*cover.dsw(args.seed))
    m.cpu.afmask = 0xC1

    def put_inputs():
        for i, v in enumerate((m.in0, m.in1, m.in2, m.dsw1, m.dsw2)):
            mem.w8(sym["io_in"] + i, v)

    put_inputs()
    rnd = random.Random(args.seed)
    merged = set()
    for line in (BUILD / "code_mpatrol.s").read_text().splitlines():
        hit = re.match(r"^Z([0-9A-F]{4}):\t\t; push .* \(merged\)", line)
        if hit:
            merged.add(int(hit[1], 16))
    dead, site = set(), [0]
    step0, write0 = m.cpu.step, m.cpu.wr8

    def ref_step():
        site[0] = m.cpu.pc
        return step0()

    def ref_write(a, v):
        (dead.add if site[0] in merged else dead.discard)(a)
        return write0(a, v)

    m.cpu.step, m.cpu.wr8 = ref_step, ref_write
    cycles = [0]

    def run_to(targets):
        total = 0
        while total < 400_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                cycles[0] += total
                return pc
            if pc in (bad, bad + 4) or s.terminated:
                raise RuntimeError("CPU stopped at %06x, d7=%08x, log=%s" % (pc - s.base, cpu.r_reg(R.D7), s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError("CPU timeout at %06x" % (cpu.r_pc() - s.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    snd = [0]

    def compare(f):
        for lo, hi in ((0x8000, 0x8800), (0xE000, 0xE800)):
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(addr(lo), hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and lo + i not in dead]
            if diff:
                raise RuntimeError("frame %d: %d RAM differences, ref pc %04x %s" % (
                    f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        if bytes(mem.r_block(addr(0xC800), 0x100)) != bytes(m.sprite_ram[:0x100]):
            raise RuntimeError("frame %d: the sprite RAM differs" % f)
        regs = [mem.r8(sym["io_regs"] + i) for i in REGS]
        if regs != m.regs:
            raise RuntimeError("frame %d: video registers %s, reference %s" % (f, regs, m.regs))
        if mem.r8(sym["io_flip"]) & 1 != m.flip ^ (~m.dsw2 & 1):
            raise RuntimeError("frame %d: the flip latch %02x, reference %d" % (f, mem.r8(sym["io_flip"]), m.flip))
        head = mem.r8(sym["snd_head"])
        got = [mem.r8(sym["snd_ring"] + ((snd[0] + i) & 255)) for i in range((head - snd[0]) & 255)]
        want = [v for fr, v in m.sound_log if fr == f]
        if got != want:
            raise RuntimeError("frame %d: sound commands %s, reference %s" % (f, got, want))
        snd[0] = head

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    m.frame = 0
    compare(-1)
    state = {}
    cycles[0] = 0
    for f in range(args.frames):
        m.in0, m.in1 = cover.inputs(f, rnd, state, args.seed)
        put_inputs()
        before = bytes(m.mem[0xE000:0xE800])
        cover.cheats(args.seed, f, m, state)
        after = bytes(m.mem[0xE000:0xE800])
        for i in range(0x800):
            if before[i] != after[i]:
                mem.w8(addr(0xE000 + i), after[i])
        mem.w8(sym["vbl_pending"], 1)
        m.frame = f
        m.run_frame_port()
        resume()
        if run_to({done, sym["sim_render_start"]}) != done:
            resume()
            run_to({done})
        compare(f)
        resume()
        run_to({wait})
        if f % 1000 == 999 and not args.quiet:
            print("%d frames exact (state %02x, course %d, point %02x)" % (
                f + 1, m.mem[0xE046], m.mem[0xE510], m.mem[0xE50E]), flush=True)
    print("PASS: %d frames (seed %d): text RAM, RAM, sprite RAM, video registers, flip and sound commands exact"
          % (args.frames, args.seed))
    print("68000 cycles a frame (the logic, no drawing; Musashi): %d" % (cycles[0] // args.frames))


if __name__ == "__main__":
    main()
