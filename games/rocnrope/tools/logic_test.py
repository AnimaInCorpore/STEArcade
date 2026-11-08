"""Frame by frame: the translated program (run/rocnrope_sim, Musashi) against the reference's port schedule
(machine.RocnRopePort.run_frame_port) through attract, coin, start, the name entry and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: cheats, DIP switches)

Compared every frame: the RAM $1800-$1FFF and $2800-$3FFF (NVRAM, video and colour RAM; the 64 bytes below the stack
pointer are dead and left out), the latch (Q0 flip, Q7 the IRQ enable), the sound commands of the frame (Q1's rising
edges).  Reports the 68000 cycles of the logic a frame (Musashi; the drawing is switched off: render_frame returns at
once).
"""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import RocnRopePort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('rocnrope')
AREAS = ((0x4000, 0x6000), (0xFFF2, 0xFFFE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--tag', default='rocnrope_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'ROCNROPE.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['main_badpc'], sym['main_badpc'] + 4}
    base = sym['rr_mem']

    m = RocnRopePort(*cover.dsw(args.seed))
    mem.w8(sym['io_dsw1'], m.dsw1)
    mem.w8(sym['io_dsw2'], m.dsw2)
    mem.w8(sym['io_dsw3'], m.dsw3)
    for n in ('io_sys', 'io_in0', 'io_in1'):
        mem.w8(sym[n], 0xFF)
    rnd = random.Random(args.seed)
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
                raise RuntimeError('CPU stopped at %06x, d7=%08x (badpc %04x), log=%s' % (
                    pc - s.base, cpu.r_reg(R.D7), mem.r16(sym['badpc']), s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x' % (cpu.r_pc() - s.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    snd = [0]

    def compare(f):
        sp = m.cpu.s
        if f < 4 or 950 <= f <= 965:
            print('frame', f, 'ref pc %04x wait %d s %04x; ste wait_pc %04x cwai %d round %d a5 %06x vbl %d cc %02x scchi %02x latch7 %d/%d' % (m.cpu.pc, m.cpu.wait, sp, mem.r16(sym['wait_pc']), mem.r8(sym['wait_cwai']), mem.r8(sym['idle_round']), cpu.r_reg(R.A5) - base, mem.r8(sym['vbl_pending']), m.cpu.cc, mem.r8(sym['main_ctx'] + 112), m.latch[7], mem.r8(sym['rr_latch'] + 7)))
        for lo, hi in AREAS:
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(base + lo, hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and not (sp - 64 <= lo + i < sp + 12 * bool(m.cpu.wait))]
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x (wait %d), ste wait_pc %04x cwai %d round %d queue %s / ref %s %s' % (
                    f, len(diff), m.cpu.pc, m.cpu.wait, mem.r16(sym['wait_pc']), mem.r8(sym['wait_cwai']), mem.r8(sym['idle_round']), bytes(mem.r_block(base + 0x5018, 4)).hex(), bytes(m.mem[0x5018:0x501C]).hex(), [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:int(__import__("os").environ.get("NDIFF", "12"))]]))
        latch = list(mem.r_block(sym['rr_latch'], 8))
        if [latch[0], latch[7]] != [m.latch[0], m.latch[7]]:
            raise RuntimeError('frame %d: latch %s, reference %s' % (f, latch, m.latch))
        head = mem.r8(sym['snd_head'])
        got = [mem.r8(sym['snd_ring'] + ((snd[0] + i) & 255)) for i in range((head - snd[0]) & 255)]
        want = [v for fr, v in m.sound_log if fr == f]
        if got != want:
            raise RuntimeError('frame %d: sound commands %s, reference %s' % (f, got, want))
        snd[0] = head

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.round()
    m.booted = True
    compare(-1)
    state = {'two': args.seed == 10}
    cycles[0] = 0
    for f in range(args.frames):
        m.frame = f
        m.system, m.in0, m.in1 = cover.inputs(f, rnd, state)
        for n, v in (('io_sys', m.system), ('io_in0', m.in0), ('io_in1', m.in1)):
            mem.w8(sym[n], v)
        before = bytes(m.mem)
        cover.cheats(args.seed, f, m, state)
        after = bytes(m.mem)
        for lo, hi in AREAS:
            for a in range(lo, hi):
                if before[a] != after[a]:
                    mem.w8(base + a, after[a])
        mem.w8(sym['vbl_pending'], 1)
        m.run_frame_port()
        m.frame = f
        resume()
        if run_to({done, sym['sim_render_start']}) != done:
            resume()
            run_to({done})
        compare(f)
        resume()
        run_to({wait})
        if f % 1000 == 999 and not args.quiet:
            print('%d frames exact (lives %d)' % (f + 1, m.mem[cover.LIVES1]), flush=True)
    print('PASS: %d frames (seed %d), RAM, NVRAM, video RAM, latch and sound commands exact' % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
