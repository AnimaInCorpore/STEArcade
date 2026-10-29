"""Frame by frame: the translated program (run/pacman_sim, Musashi) against the reference's port schedule
(machine.PacmanPort.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: cheats, DIP switches)

Compared every frame: the RAM $4000-$47FF and $4C00-$4FFF (the stack bytes only a merged `push rr; pop rr'` would have
written are dead below SP and left out), the latch bit 0 (the IRQ enable), the IM 2 vector, IFF1, the WSG registers
$5040-$505F (4 bits) and the sprite coordinates $5060-$506F.  Every changed video / colour RAM cell must be listed
(gen.py tile_marks, cell_list / cell_dirty).  Reports the 68000 cycles of the logic a frame (Musashi; no drawing).
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
from machine import PacmanPort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('pacman')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--tag', default='pacman_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'PACMAN.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['z80_badpc'], sym['z80_badpc'] + 4}
    a6 = sym['g_block'] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    m = PacmanPort(dsw1=cover.dsw1(args.seed))
    m.cpu.afmask = 0xc1
    for a, v in ((0x5100, 0xFF), (0x5101, 0xFF), (0x5102, m.dsw1), (0x5103, m.dsw2)):
        mem.w8(addr(a), v)
    rnd = random.Random(args.seed)
    merged = set()
    for line in (BUILD / 'code_main.s').read_text().splitlines():
        hit = re.match(r'^Z([0-9A-F]{4}):\t\t; push .* \(merged\)', line)
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
            if pc in bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x, d7=%08x, log=%s' % (pc - s.base, cpu.r_reg(R.D7), s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x' % (cpu.r_pc() - s.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def compare(f):
        sp = m.cpu.sp
        for lo, hi in ((0x4000, 0x4800), (0x4C00, 0x5000)):
            want = bytes(m.ram[lo - 0x4000:hi - 0x4000])
            got = bytes(mem.r_block(addr(lo), hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and lo + i not in dead and
                    not (sp - 64 <= lo + i < sp)]
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x %s' % (
                    f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        got = bytes(mem.r_block(addr(0x5040), 0x30))
        snd = [v & 15 for v in got[:0x20]]
        if snd != list(m.sound):
            raise RuntimeError('frame %d: WSG registers %s, reference %s' % (f, bytes(snd).hex(), m.sound.hex()))
        if got[0x20:] != bytes(m.sprite2):
            raise RuntimeError('frame %d: sprite coordinates %s, reference %s' % (f, got[0x20:].hex(), m.sprite2.hex()))
        checks = (('latch bit 0', mem.r8(addr(0x5000)) & 1, m.latch[0]), ('vector', mem.r8(sym['pm_vector']), m.vector),
                  ('IFF1', 1 if mem.r8(sym['pm_iff']) else 0, m.cpu.iff1))
        for name, g, w in checks:
            if g != w:
                raise RuntimeError('frame %d: %s %02x, reference %02x' % (f, name, g, w))

    last = [None]

    def cells(f):
        now = bytes(mem.r_block(addr(0x4000), 0x800))
        marks = bytes(mem.r_block(sym['cell_dirty'], 1024))
        listed = sorted(mem.r16(sym['cell_list'] + 2 * k) for k in range((mem.r32(sym['cell_ptr']) - sym['cell_list']) // 2))
        if listed != sorted(i for i in range(1024) if marks[i]):
            raise RuntimeError('frame %d: cell_list and cell_dirty disagree' % f)
        if last[0] is not None and not mem.r8(sym['tiles_all']):
            for i in range(0x800):
                if now[i] != last[0][i] and not marks[i & 0x3ff]:
                    raise RuntimeError('frame %d: %04x changed, its cell not listed (a writer missing in gen.py)' % (
                        f, 0x4000 + i))
        last[0] = now
        for i in range(1024):
            mem.w8(sym['cell_dirty'] + i, 0)
        mem.w32(sym['cell_ptr'], sym['cell_list'])
        mem.w8(sym['tiles_all'], 0)

    mem.w32(sym['cell_ptr'], sym['cell_list'])
    run_to({wait})                          # the boot to its halt
    m.run_to_wait()
    compare(-1)
    cells(-1)
    state = {'seed': args.seed}
    cycles[0] = 0
    for f in range(args.frames):
        cover.apply_inputs(m, f, rnd, state)
        mem.w8(addr(0x5100), m.in0)
        mem.w8(addr(0x5101), m.in1)
        before = bytes(m.ram)
        cover.cheats(args.seed, f, m, state)
        after = bytes(m.ram)
        for i in range(len(after)):
            if before[i] != after[i]:
                mem.w8(addr(0x4000 + i), after[i])
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
        cells(f)
        if f % 1000 == 999 and not args.quiet:
            print('%d frames exact (level %d)' % (f + 1, m.ram[0xE13]), flush=True)
    print('PASS: %d frames (seed %d): RAM, latch, vector, IFF1, WSG registers and sprite coordinates exact; every '
          'video RAM change marked' % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
