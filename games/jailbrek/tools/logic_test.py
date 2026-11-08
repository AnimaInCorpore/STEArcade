"""Frame by frame: the translated program (run/jailbrek_sim, Musashi) against the reference's port schedule
(machine.JailBreakPort.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: cheats, DIP switches)

Compared every frame: the RAM $0000-$203F (colour and video RAM, sprite RAM, RAM, scroll RAM; the 64 bytes below the
stack pointer are dead and left out), the video chip's control registers ($2040-$2047), the speech chip's BSY pin.
Reports the 68000 cycles of the logic a frame (Musashi; the drawing is switched off: render_frame returns at once).
"""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import JailBreakPort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('jailbrek')
AREAS = ((0x0000, 0x2040),)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--tag', default='jailbrek_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'JAILBREK.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['main_badpc'], sym['main_badpc'] + 4}
    base = sym['jb_mem']

    m = JailBreakPort(*cover.dsw(args.seed))
    mem.w8(sym['io_dsw1'], m.dsw1)
    mem.w8(sym['io_dsw2'], m.dsw2)
    mem.w8(sym['io_dsw3'], m.dsw3)
    for n in ('io_sys', 'io_p1', 'io_p2'):
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

    def compare(f):
        sp = m.cpu.s
        for lo, hi in AREAS:
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(base + lo, hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and not (sp - 64 <= lo + i < sp)]
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x %s' % (
                    f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        ctrl = list(mem.r_block(sym['jb_ctrl'], 8))
        if ctrl != m.ctrl:
            raise RuntimeError('frame %d: ctrl %s, reference %s' % (f, ctrl, m.ctrl))
        if mem.r16(sym['jb_bsy_left']) != m.bsy_left:
            raise RuntimeError('frame %d: BSY count %d, reference %d' % (f, mem.r16(sym['jb_bsy_left']), m.bsy_left))
        if mem.r8(sym['jb_bsy']) != m.bsy:
            raise RuntimeError('frame %d: BSY %d, reference %d' % (f, mem.r8(sym['jb_bsy']), m.bsy))
        sound(f)

    sn = {'regs': [0] * 8, 'latch': 0, 'at': 0, 'vlm': 0, 'st': 0, 'rst': 0, 'param': 0}

    def sound(f):
        """the SN76489A's register file (MAME sn76496 write) and the speech request against the reference's log"""
        log = m.sound_log
        asked = None
        for fr, kind, v in log[sn['at']:]:
            if kind == 'sn':
                if v & 0x80:
                    sn['latch'] = v >> 4 & 7
                    sn['regs'][sn['latch']] = sn['regs'][sn['latch']] & 0x3F0 | v & 15
                elif sn['latch'] & 1 or sn['latch'] == 6:
                    sn['regs'][sn['latch']] = sn['regs'][sn['latch']] & 0x3F0 | v & 15
                else:
                    sn['regs'][sn['latch']] = sn['regs'][sn['latch']] & 15 | (v & 0x3F) << 4
            elif kind == 'vlm':
                sn['vlm'] = v
            else:
                st, rst = v >> 1 & 1, v >> 2 & 1
                if rst != sn['rst']:
                    sn['rst'] = rst
                    if not rst:
                        sn['param'] = sn['vlm']
                if st != sn['st']:
                    sn['st'] = st
                    if not st:
                        asked = sn['vlm'] << 8 | sn['param']
        sn['at'] = len(log)
        got = [mem.r16(sym['jb_sn'] + 2 * i) for i in range(8)]
        if got != sn['regs']:
            raise RuntimeError('frame %d: SN registers %s, reference %s' % (f, got, sn['regs']))
        ptr = mem.r32(sym['snd_dma_last'])
        if asked is not None and ptr and mem.r16(ptr) != asked and any(
                mem.r16(sym['jb_phr_tab'] + 10 * i) == asked for i in range(24)):
            raise RuntimeError('frame %d: phrase %04x asked, the DMA has %04x' % (f, asked, mem.r16(ptr)))

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    compare(-1)
    state = {'two': args.seed in (4, 6)}
    cycles[0] = 0
    replay = cover.replay_ticks() if args.seed == 13 else None     # (the search bot's recorded play, lives cheat from 420)
    if replay:
        args.frames = min(args.frames, len(replay))
    for f in range(args.frames):
        m.frame = f
        if replay:
            m.system, m.p1, m.p2 = replay[f][0], replay[f][1], 0xFF
        else:
            m.system, m.p1, m.p2 = cover.inputs(f, rnd, state)
        for n, v in (('io_sys', m.system), ('io_p1', m.p1), ('io_p2', m.p2)):
            mem.w8(sym[n], v)
        before = bytes(m.mem)
        if replay:
            if f >= 420:
                m.mem[cover.LIVES1] = 8
        else:
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
    print('PASS: %d frames (seed %d), RAM, video RAM, scroll RAM, control registers, BSY, the SN76489A registers and the speech requests exact' % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
