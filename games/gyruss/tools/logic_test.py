"""Frame by frame: the translated programs (run/gyruss_sim, Musashi) against the reference's port schedule
(machine.GyrussPort.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: cheats, DIP switches)

Compared every frame: the main CPU's video RAM and RAM $8000-$87FF, $9000-$A7FF (the shared RAM too; the stack bytes
only a merged `push rr; pop rr'` would have written are dead below SP and left out), the latch bytes the runtime
reads ($C180 the NMI mask, $C185 the flip), the sub CPU's RAM $4000-$47FF (the sprite RAM), the sound commands of the
frame.  Every changed video RAM cell must be listed (gen.py tile_marks, cell_list).  Reports the 68000 cycles of the
logic a frame (Musashi; the drawing is switched off: render_frame returns at once).
"""
from pathlib import Path
import argparse
import random
import re
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import GyrussPort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('gyruss')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--tag', default='gyruss_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'GYRUSS.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['z80_badpc'], sym['z80_badpc'] + 4, sym['sub_badpc']}
    a6 = sym['g_block'] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    m = GyrussPort(*cover.dsw(args.seed))
    m.main.afmask = 0xc1
    io = sym['io_in']
    for off, v in ((0, m.dsw2), (4, 0xFF), (5, 0xFF), (6, 0xFF), (7, m.dsw1), (8, m.dsw3)):
        mem.w8(io + off, v)
    rnd = random.Random(args.seed)
    merged = set()
    for line in (BUILD / 'code_main.s').read_text().splitlines():
        hit = re.match(r'^Z([0-9A-F]{4}):\t\t; push .* \(merged\)', line)
        if hit:
            merged.add(int(hit[1], 16))
    dead, site = set(), [0]
    step0, write0 = m.main.step, m.main.wr8

    def ref_step():
        site[0] = m.main.pc
        return step0()

    def ref_write(a, v):
        (dead.add if site[0] in merged else dead.discard)(a)
        return write0(a, v)

    m.main.step, m.main.wr8 = ref_step, ref_write
    cycles = [0]

    def run_to(targets):
        total = 0
        while total < 400_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                cycles[0] += total
                return pc
            if pc in bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x, d7=%08x, log=%s' % (pc - s.base, cpu.r_reg(R.D7), s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x' % (cpu.r_pc() - s.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    snd = [0]

    def compare(f):
        for lo, hi in ((0x8000, 0x8800), (0x9000, 0xA800)):
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(addr(lo), hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and lo + i not in dead]
            if diff:
                raise RuntimeError('frame %d: %d main RAM differences, ref pc %04x %s' % (
                    f, len(diff), m.main.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        for q in (0, 5):
            if (mem.r8(addr(0xC180 + q)) & 1) != m.latch[q]:
                raise RuntimeError('frame %d: latch Q%d %d, reference %d' % (f, q, mem.r8(addr(0xC180 + q)) & 1,
                                                                             m.latch[q]))
        want = bytes(m.sub_mem[0x4000:0x4800])
        got = bytes(mem.r_block(sym['sub_ram'], 0x800))
        diff = [0x4000 + i for i in range(0x800) if want[i] != got[i]]
        if diff:
            raise RuntimeError('frame %d: %d sub RAM differences, ref pc %04x %s' % (
                f, len(diff), m.sub.pc, [(hex(a), hex(got[a - 0x4000]), hex(want[a - 0x4000])) for a in diff[:12]]))
        if (mem.r8(sym['sub_mask']) & 1) != m.sub_irq_mask:
            raise RuntimeError('frame %d: the sub IRQ mask differs' % f)
        head = mem.r8(sym['snd_head'])
        got = [mem.r8(sym['snd_ring'] + ((snd[0] + i) & 255)) for i in range((head - snd[0]) & 255)]
        want = [v for fr, v in m.sound_log if fr == f]
        if got != want:
            raise RuntimeError('frame %d: sound commands %s, reference %s' % (f, got, want))
        snd[0] = head

    last = [None]

    def rows(f):
        now = bytes(mem.r_block(addr(0x8000), 0x800))
        marks = bytes(mem.r_block(sym['cell_dirty'], 1024))
        listed = sorted(mem.r16(sym['cell_list'] + 2 * k) for k in range((mem.r32(sym['cell_ptr']) - sym['cell_list']) // 2))
        if listed != sorted(i for i in range(1024) if marks[i]):
            raise RuntimeError('frame %d: cell_list and cell_dirty disagree' % f)
        if last[0] is not None and not mem.r8(sym['tiles_all']):
            for i in range(0x800):
                if now[i] != last[0][i] and not marks[i & 0x3ff]:
                    raise RuntimeError('frame %d: %04x changed, its cell not listed (a writer missing in gen.py)' % (
                        f, 0x8000 + i))
        last[0] = now
        for i in range(1024):
            mem.w8(sym['cell_dirty'] + i, 0)
        mem.w32(sym['cell_ptr'], sym['cell_list'])
        mem.w8(sym['tiles_all'], 0)

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.run_sub_to_idle()
    m.booted = True
    m.frame = 0
    compare(-1)
    rows(-1)
    state = {'two': args.seed in (10, 11)}
    cycles[0] = 0
    for f in range(args.frames):
        m.system, m.p1 = cover.inputs(f, rnd, state, m)
        for a, v in zip((4, 5), (m.system, m.p1)):
            mem.w8(io + a, v)
        before = bytes(m.mem[0x9000:0xA000])
        cover.cheats(args.seed, f, m, state)
        after = bytes(m.mem[0x9000:0xA000])
        for i in range(0x1000):
            if before[i] != after[i]:
                mem.w8(addr(0x9000 + i), after[i])
        mem.w8(sym['vbl_pending'], 1)
        m.frame = f
        m.run_frame_port()
        resume()
        if run_to({done, sym['sim_render_start']}) != done:
            resume()
            run_to({done})
        compare(f)
        resume()
        run_to({wait})
        rows(f)
        if f % 1000 == 999 and not args.quiet:
            print('%d frames exact (state %02x)' % (f + 1, m.mem[0x942B]), flush=True)
    print('PASS: %d frames (seed %d), main RAM, sub RAM, latches and sound commands exact; every video RAM change '
          'marked' % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
