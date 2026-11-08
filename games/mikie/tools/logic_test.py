"""Frame by frame: the translated program (run/mikie_sim, Musashi) against the reference's port schedule
(machine.MikiePort.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: cheats, DIP switches)

Compared every frame: the RAM $0000-$00FF and $2800-$3FFF (sprite RAM, RAM, video and colour RAM; the 64 bytes below the stack
pointer are dead and left out), the latch (Q6 flip, Q7 the IRQ enable), the palette bank, the sound commands of the frame (Q2's rising
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
from machine import MikiePort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('mikie')
AREAS = ((0x0000, 0x0100), (0x2800, 0x4000))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--profile', action='store_true', help='step every instruction, print the cycles by 6809 block (slow)')
    ap.add_argument('--tag', default='mikie_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'MIKIE.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['main_badpc'], sym['main_badpc'] + 4}
    base = sym['mk_mem']

    m = MikiePort(*cover.dsw(args.seed))
    mem.w8(sym['io_dsw1'], m.dsw1)
    mem.w8(sym['io_dsw2'], m.dsw2)
    mem.w8(sym['io_dsw3'], m.dsw3)
    for n in ('io_sys', 'io_p1', 'io_p2'):
        mem.w8(sym[n], 0xFF)
    rnd = random.Random(args.seed)
    cycles = [0]

    import bisect
    import collections
    labels = sorted((v, k) for k, v in sym.items())
    lab_addr = [v for v, _ in labels]
    prof = collections.Counter()

    def charge(pc, cyc):
        name = labels[bisect.bisect_right(lab_addr, pc) - 1][1]
        prof[name] += cyc

    def run_to(targets):
        total = 0
        while total < 400_000_000:
            if args.profile:
                pc0 = cpu.r_pc()
                c = cpu.execute(1).cycles
                charge(pc0, c)
                total += c
            else:
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
        for lo, hi in AREAS:
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(base + lo, hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and not (sp - 64 <= lo + i < sp) and
                    not (lo + i == sp and want[i] ^ got[i] == 0x20)]      # (the pushed CC's H: the translation keeps it only where DAA reads it)
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x %s' % (
                    f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        latch = list(mem.r_block(sym['mk_latch'], 8))
        if [latch[6], latch[7]] != [m.latch[6], m.latch[7]] or mem.r8(sym['pal_bank']) != m.palbank:
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
    m.booted = True
    compare(-1)
    state = {'two': args.seed in (7, 8)}
    cycles[0] = 0
    for f in range(args.frames):
        m.frame = f
        m.system, m.in0, m.in1 = cover.inputs(f, rnd, state)
        for n, v in (('io_sys', m.system), ('io_p1', m.in0), ('io_p2', m.in1)):
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
    print('PASS: %d frames (seed %d), RAM, sprite and video RAM, latch, palette bank and sound commands exact' % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))
    if args.profile:
        blocks = collections.Counter()
        for name, c in prof.items():
            if len(name) == 7 and name[0] == 'M' and all(ch in '0123456789ABCDEF' for ch in name[1:]):
                blocks['6809 $%sxx' % name[3:6]] += c         # (M009962: two bank digits, the address)
            else:
                blocks[name] += c
        print('hottest 6809 instructions:')
        for name, c in [kv for kv in prof.most_common() if len(kv[0]) == 7 and kv[0][0] == 'M'][:25]:
            print('%7d  %s' % (c // args.frames, name))
        tot = sum(prof.values())
        print('profile: %d cycles a frame charged' % (tot // args.frames))
        for name, c in blocks.most_common(40):
            print('%7d  %5.1f%%  %s' % (c // args.frames, 100.0 * c / tot, name))


if __name__ == '__main__':
    main()
