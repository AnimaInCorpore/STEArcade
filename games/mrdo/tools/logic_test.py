"""Frame by frame: the translated program (run/mrdo_sim, Musashi) against the reference's port schedule
(machine.MrDoPort.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: cheats, DIP switches)

Compared every frame: the video RAM $8000-$8FFF, the sprite RAM $9000-$90FF, the RAM $E000-$EFFF (the stack bytes
only a merged `push rr; pop rr'` would have written are dead below SP and left out, as the 64 bytes below SP), the
flip latch $9800, the scroll registers $F000 / $F800, the SN76489 bytes of the frame.  Every changed video RAM cell
must be listed (gen.py tile_marks: cell_list / cell_dirty).  Reports the 68000 cycles of the logic a frame (Musashi; the drawing is
switched off: render_frame returns at once).
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
from machine import MrDoPort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('mrdo')
IN_P1, IN_P2, IN_DSW1, IN_DSW2 = 0xA000, 0xA001, 0xA002, 0xA003
CELLS = 2048


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--tag', default='mrdo_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'MRDO.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['z80_badpc'], sym['z80_badpc'] + 4}
    a6 = sym['g_block'] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    m = MrDoPort(*cover.dsw(args.seed))
    m.cpu.afmask = 0xc1
    m.sound_log = []
    for a, v in ((IN_P1, 0xFF), (IN_P2, 0xFF), (IN_DSW1, m.dsw1), (IN_DSW2, m.dsw2)):
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

    snd = [0]

    def compare(f):
        sp = m.cpu.sp
        for lo, hi, ram in ((0x8000, 0x9000, m.vram), (0x9000, 0x9100, m.spriteram), (0xE000, 0xF000, m.ram)):
            want = bytes(ram)
            got = bytes(mem.r_block(addr(lo), hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and lo + i not in dead and
                    not (sp - 64 <= lo + i < sp)]
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x %s' % (
                    f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        regs = (mem.r8(addr(0x9800)) & 1, mem.r8(addr(0xF000)), mem.r8(addr(0xF800)))
        if regs != (m.flip, m.scrollx, m.scrolly):
            raise RuntimeError('frame %d: flip, scroll x, y %s, reference %s' % (f, regs, (m.flip, m.scrollx, m.scrolly)))
        head = mem.r8(sym['snd_head'])
        got = [(mem.r8(sym['snd_ring'] + ((snd[0] + i) & 255)), mem.r8(sym['snd_ring'] + ((snd[0] + i + 1) & 255)))
               for i in range(0, (head - snd[0]) & 255, 2)]
        want = [(chip, v) for fr, cyc, chip, v in m.sound_log if fr == f]
        del m.sound_log[:]
        if got != want:
            raise RuntimeError('frame %d: SN76489 bytes %s, reference %s' % (f, got[:16], want[:16]))
        snd[0] = head

    last = [None]

    def rows(f):
        now = bytes(mem.r_block(addr(0x8000), 0x1000))
        marks = bytes(mem.r_block(sym['cell_dirty'], CELLS))
        listed = sorted(mem.r16(sym['cell_list'] + 2 * k) for k in range((mem.r32(sym['cell_ptr']) - sym['cell_list']) // 2))
        if listed != sorted(i for i in range(CELLS) if marks[i]):
            raise RuntimeError('frame %d: cell_list and cell_dirty disagree' % f)
        if last[0] is not None and not mem.r8(sym['tiles_all']):
            for i in range(0x1000):
                if now[i] != last[0][i] and not marks[(i & 0x3ff) | ((i & 0x800) >> 1)]:
                    raise RuntimeError('frame %d: %04x changed, its cell not listed (a writer missing in gen.py)' % (
                        f, 0x8000 + i))
        last[0] = now
        for i in range(CELLS):
            mem.w8(sym['cell_dirty'] + i, 0)
        mem.w32(sym['cell_ptr'], sym['cell_list'])
        mem.w8(sym['tiles_all'], 0)

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    m.frame = 0
    compare(-1)
    rows(-1)
    state = {'seed': args.seed}
    cycles[0] = 0
    for f in range(args.frames):
        cover.apply_inputs(m, f, rnd, state)
        for a, v in zip((IN_P1, IN_P2, IN_DSW1), (m.p1, m.p2, m.dsw1)):
            mem.w8(addr(a), v)
        before = bytes(m.ram)
        cover.cheats(args.seed, f, m, state)
        after = bytes(m.ram)
        for i in range(0x1000):
            if before[i] != after[i]:
                mem.w8(addr(0xE000 + i), after[i])
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
            print('%d frames exact (scene %02X)' % (f + 1, m.ram[cover.SCENE - 0xE000]), flush=True)
    print('PASS: %d frames (seed %d), RAM, video and sprite RAM, flip, scroll, SN76489 bytes exact; every video RAM '
          'change listed' % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
