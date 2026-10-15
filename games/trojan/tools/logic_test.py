"""The translated program (run/trojan_sim, engine/sim.py) frame by frame against the reference's port schedule
(tools/machine.py TrojanPort): the RAM ($C000-$EFFF but the dead stack below SP), the palette, the registers, the
sprite buffer and the sound latch after every arcade frame; every change of the character / tile RAM and the palette
comes with its flag (gen.py's writers).

    python games/trojan/tools/logic_test.py [FRAMES] [--seed N] [--level L] [--auto] [--play]

Input: --seed N the random play of ref/cover.py's seed N (levels and cheats included); --auto the AUTOPLAY schedule
(src/trojan.s ap_inputs: a coin, the start, walking right with attacks); default seed 1.  --play: the recorded play
against a sim build with -D PLAYBACK=1.  Reports the 68000 cycles a frame (Musashi: the logic, no drawing).
"""
from pathlib import Path
import argparse
import re
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine'),
                str(Path(__file__).resolve().parents[1] / 'ref')]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import TrojanPort, DSWA
from paths import ROOT, build_dir
import cover


def auto_inputs(f):
    """src/trojan.s ap_inputs (the frame f counts from 0 as cnt_ticks - 1)"""
    t = f % 3000
    s = 0xFF
    if 900 <= t < 905:
        s &= ~0x40
    if 940 <= t < 945:
        s &= ~1
    p = 0xFF
    if t >= 1000:
        p ^= 1 | 16
        if t % 90 < 15:
            p ^= 32
    return s, p, t >= 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--auto', action='store_true')
    ap.add_argument('--play', action='store_true')
    args = ap.parse_args()
    run = ROOT / 'run' / 'trojan_sim'
    sim = Sim(str(run / 'TROJAN.PRG'), run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir('trojan') / 'trojan_sim.map').items()}
    stops = {sym[n]: n for n in ['sim_wait', 'sim_frame_done', 'z80_badpc']}
    mem, cpu = sim.mem, sim.cpu
    mem.w16(sym['render_frame'], 0x4E75)            # (no drawing)
    block = sym['g_block']

    def z(a):                                       # the image address of Z80 address a
        return block + 0x8000 + (a if a < 0x8000 else a - 0x10000)

    level, cheats, inputs = cover.schedule(args.seed)
    if args.auto or args.play:
        level, cheats = None, False
    dswb = 0x1C | cover.LEVEL_DSW[level] if level else 0xFC
    ref = TrojanPort(DSWA, dswb)
    mem.w8(sym['tr_dsw'], dswb)
    play = None
    if args.play:
        import playbot
        play = playbot.load(build_dir('trojan') / 'play_inputs.bin')

    # (z80x merges `push rr / pop rr'` into a move: the stack word below SP is never written; the reference's bytes
    # written by such a push are not compared until another instruction writes them)
    merged = set()
    for line in (build_dir('trojan') / 'code_trojan.s').read_text().splitlines():
        hit = re.match(r'^Z([0-9A-F]{4,5}):\t\t; push .* \(merged\)', line)
        if hit:
            merged.add(int(hit[1], 16))
    dead = set()
    site = [0]
    step0, write0 = ref.cpu.step, ref.cpu.wr8

    def ref_step():
        pc = ref.cpu.pc
        site[0] = 0x10000 + ref.bank * 0x4000 + pc - 0x8000 if 0x8000 <= pc < 0xC000 else pc
        return step0()

    def ref_write(a, v):
        if site[0] in merged:
            dead.add(a)
        else:
            dead.discard(a)
        return write0(a, v)
    ref.cpu.step, ref.cpu.wr8 = ref_step, ref_write

    cycles = [0]

    def run_to_stop():
        used = 0
        while used < 400_000_000:
            r = cpu.execute(2000)
            used += r.cycles
            pc = cpu.r_pc()
            if pc in stops:
                cycles[0] += used
                return stops[pc]
            if pc == TRAP1:
                sim.gemdos()
            if sim.terminated:
                raise RuntimeError('terminated at %06x: %s' % (pc, sim.log[-3:]))
        raise RuntimeError('68000 budget exceeded at %06x' % cpu.r_pc())

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def compare(f):
        got = mem.r_block(z(0xC000), 0x3800)
        want = ref.mem[0xC000:0xF800]
        sp = ref.cpu.sp
        diff = [i for i in range(len(want)) if got[i] != want[i] and not (0xCF80 <= 0xC000 + i < sp)
                and 0xC000 + i not in dead]
        if diff:
            raise RuntimeError('frame %d: %d bytes differ: %s' % (f, len(diff), [
                ('%04X' % (0xC000 + i), got[i], want[i]) for i in diff[:12]]))
        regs = mem.r_block(z(0xF800), 6)
        if bytes(regs) != bytes(ref.mem[0xF800:0xF806]):
            raise RuntimeError('frame %d: registers %s, reference %s' % (f, bytes(regs).hex(), ref.mem[0xF800:0xF806].hex()))
        if mem.r8(sym['g_bankreg']) != ref.bankreg:
            raise RuntimeError('frame %d: $F80E %02x, reference %02x' % (f, mem.r8(sym['g_bankreg']), ref.bankreg))
        if bytes(mem.r_block(sym['tr_sprites'], 0x180)) != bytes(ref.sprites):
            raise RuntimeError('frame %d: the sprite buffer differs' % f)
        a5 = cpu.r_reg(R.A5) & 0xFFFFFF
        if a5 - z(0x10000) & 0xFFFF != sp:
            raise RuntimeError('frame %d: SP %04x, reference %04x' % (f, (a5 - z(0x10000)) & 0xFFFF, sp))

    regions = [('fg_written', 0xE000, 0x800), ('bg_written', 0xE800, 0x800), ('pal_written', 0xF000, 0x800)]
    last = {}

    def flags(f):
        for flag, a, size in regions:
            now = bytes(mem.r_block(z(a), size))
            if flag in last and now != last[flag] and not mem.r8(sym[flag]):
                i = next(i for i in range(size) if now[i] != last[flag][i])
                raise RuntimeError('frame %d: %04X changed without %s (a writer missing in gen.py)' % (f, a + i, flag))
            last[flag] = now
            mem.w8(sym[flag], 0)

    if run_to_stop() != 'sim_wait':
        raise RuntimeError('did not reach the idle point')
    ref.run_to_idle()
    ref.booted = True
    compare(-1)
    flags(-1)
    first = None
    for f in range(args.frames):
        if play:
            ref.inputs[0], ref.inputs[1] = play[f]
            if f >= 1000:
                ref.mem[0xCDA0] = 3
        else:
            if args.auto:
                s, p, lives = auto_inputs(f)
            else:
                s, p = inputs(f)
                lives = cheats and f >= 1000
            ref.inputs[0], ref.inputs[1] = s, p
            mem.w8(sym['tr_inputs'], s)
            mem.w8(sym['tr_inputs'] + 1, p)
            if lives:
                for a, v in ((0xCDA0, 3), (0xC078, 0), (0xC079, 0x99)) if cheats else ((0xCDA0, 3),):
                    ref.mem[a] = v
                    mem.w8(z(a), v)
        mem.w8(sym['vbl_pending'], 1)
        ref.run_frame_port()
        c0 = cycles[0]
        resume()
        stop = run_to_stop()
        if stop != 'sim_frame_done':
            raise RuntimeError('frame %d: stopped at %s (pc %04x, d7 %08x)' % (f, stop, mem.r16(sym['g_dispatch_pc']),
                                                                             cpu.r_reg(R.D7)))
        compare(f)
        resume()
        if run_to_stop() != 'sim_wait':
            raise RuntimeError('frame %d: not back at the idle point' % f)
        flags(f)
        if f == 100:
            first = cycles[0]
        if f % 1000 == 999:
            print('%d frames identical' % (f + 1), flush=True)
    n = args.frames - 101
    if n > 0:
        print('68000 cycles a frame (Musashi, logic only, frames 101-%d): %.0f' % (args.frames, (cycles[0] - first) / n))
    print('PASS: %d frames: RAM, palette, registers, sprite buffer identical; every video RAM / palette change flagged'
          % args.frames)


if __name__ == '__main__':
    main()
