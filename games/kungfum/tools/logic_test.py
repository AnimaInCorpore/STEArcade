"""Frame by frame: the translated program (run/kungfum_sim, Musashi) against the reference's port schedule
(machine.KungFuPort.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N] [--play] [--audit]     (seeds as ref/cover.py: cheats, DIP switches)

Compared every frame: the RAM D000-EFFF (tile RAM, work RAM; the stack bytes only a merged `push rr; pop rr'` would
have written are dead below SP and left out), the sprite RAM C000-C0FF, the scroll register, the flip latch, the
sound commands of the frame.  Every changed tile RAM row must be marked (gen.py tile_marks, tile_rows).  Reports the
68000 cycles of the logic a frame (Musashi; the drawing is switched off: render_frame returns at once).
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
from machine import KungFuPort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('kungfum')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--play', action='store_true', help='the recorded play (play_search.py) against a sim build '
                    'with -D PLAYBACK=1')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--recording', type=Path, default=BUILD / 'play_inputs.bin', help='reference inputs with --play')
    ap.add_argument('--program', type=Path, help='alternate simulator PRG (e.g. an isolated bot replay build)')
    ap.add_argument('--map', dest='mapfile', type=Path, default=BUILD / 'kungfum_sim.map')
    args = ap.parse_args()
    run = ROOT / 'run' / 'kungfum_sim'
    program = args.program or run / 'KUNGFUM.PRG'
    s = Sim(str(program), run_dir=program.parent)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(args.mapfile).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done, bad = sym['sim_wait'], sym['sim_frame_done'], sym['z80_badpc']
    a6 = sym['g_block'] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    m = KungFuPort(*cover.dsw(args.seed))
    m.cpu.afmask = 0xc1
    for i in range(3):
        mem.w8(sym['io_ports'] + i, 0xFF)
    mem.w8(sym['io_ports'] + 3, m.dsw1)
    mem.w8(sym['io_ports'] + 4, m.dsw2)
    rnd = random.Random(args.seed)
    merged = set()
    for line in (BUILD / 'code_kungfum.s').read_text().splitlines():
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
            if pc in (bad, bad + 4) or s.terminated:
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
        want = bytes(m.mem[0xD000:0xF000])
        got = bytes(mem.r_block(addr(0xD000), 0x2000))
        diff = [0xD000 + i for i in range(0x2000) if want[i] != got[i] and 0xD000 + i not in dead]
        if diff:
            raise RuntimeError('frame %d: %d RAM differences, ref pc %04x %s' % (
                f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - 0xD000]), hex(want[a - 0xD000])) for a in diff[:12]]))
        if bytes(mem.r_block(addr(0xC000), 0x100)) != bytes(m.sprite_ram):
            raise RuntimeError('frame %d: the sprite RAM differs' % f)
        scroll = mem.r8(addr(0xA000)) | mem.r8(addr(0xB000)) << 8
        if scroll != m.scroll:
            raise RuntimeError('frame %d: scroll %04x, reference %04x' % (f, scroll, m.scroll))
        head = mem.r8(sym['snd_head'])
        got = [mem.r8(sym['snd_ring'] + ((snd[0] + i) & 255)) for i in range((head - snd[0]) & 255)]
        want = [v for fr, v in m.sound_log if fr == f]
        if got != want:
            raise RuntimeError('frame %d: sound commands %s, reference %s' % (f, got, want))
        snd[0] = head

    last = [None]

    def rows(f):
        now = bytes(mem.r_block(addr(0xD000), 0x1000))
        marks = bytes(mem.r_block(sym['tile_rows'], 32))
        if last[0] is not None:
            for i in range(0x1000):
                if now[i] != last[0][i] and not marks[(i & 0x7ff) >> 6]:
                    raise RuntimeError('frame %d: %04x changed, its row not marked (a writer missing in gen.py)' % (
                        f, 0xD000 + i))
        last[0] = now
        for i in range(32):
            mem.w8(sym['tile_rows'] + i, 0)

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    m.frame = 0
    compare(-1)
    rows(-1)
    state = {'select': args.seed in (12, 13)}
    cycles[0] = 0
    play = None
    if args.play:
        import playbot
        play = playbot.load(args.recording)
        if len(play) < args.frames:
            ap.error('--recording is shorter than the requested frame count')
    for f in range(args.frames):
        if play:
            m.system, m.p1 = play[f]
            if f >= 900:
                m.mem[0xE084] = 6
        else:
            m.system, m.p1 = cover.inputs(f, rnd, state, m)
            for a, v in zip((0, 1), (m.system, m.p1)):
                mem.w8(sym['io_ports'] + a, v)
            before = bytes(m.mem[0xE000:0xF000])
            cover.cheats(args.seed, f, m, state)
            after = bytes(m.mem[0xE000:0xF000])
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
            print('%d frames exact (state %02x, floor %02x)' % (f + 1, m.mem[0xE000], m.mem[0xE080]), flush=True)
    print('PASS: %d frames (seed %d), RAM, sprite RAM, scroll and sound commands exact; every tile RAM change marked'
          % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
