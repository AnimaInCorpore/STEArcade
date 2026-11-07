"""Frame by frame: the translated programs (run/xevious_sim, Musashi) against the reference's STE schedule
(machine.Xevious.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: DIP switches, two players, infinite lives)

Compared every frame: the work RAM $7800-$CFFF (main CPU's view, the sub CPU's half of $7900-$7FFF; the stack words below
each CPU's SP are dead and left out, and so are the bytes a merged `push rr; pop rr'` would have written), the latches
($6820-$6827, the scroll registers, the flip register), the 51XX's data RAM and registers, the 50XX's answers.  Every
changed tile RAM block must have been marked (vblocks / vblock_all: gen.py).  Reports the 68000 cycles of the logic a
frame (Musashi; the drawing is switched off: render_frame returns at once).
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
from machine import Xevious
import sound
from paths import ROOT, build_dir

BUILD = build_dir('xevious')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--tag', default='xevious_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'XEVIOUS.PRG'), run_dir=run, ram_kib=16384)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['z80_badpc'], sym['z80_badpc'] + 4}
    g_ram, g_block, g3_block = sym['g_block'] + 0x8000, sym['g_block'], sym['g3_block']
    g_rom1 = g_block + 0x10000

    m = Xevious(skip_tests=True, invincible=args.seed >= 31)
    rnd = random.Random(args.seed)
    seed = args.seed
    players = 2 if seed in (4, 5) else 1
    nocoin = seed == 6
    infinite = 11 <= seed < 31
    if seed in (7, 8):
        m.dswa = 0xff & ~0x60 | (0x40 if seed == 7 else 0x00)
    if seed == 9:
        m.dswb = m.dswb & ~0x60
    for base in (g_rom1, g_block):
        for i in range(8):
            mem.w8(base + 0x6800 + i, ((m.dswb >> i) & 1) | (((m.dswa >> i) & 1) << 1))

    merged = [set(), set(), set()]
    for n, pfx in enumerate('ZYX'):
        pass
    for line in (BUILD / 'xevious_code.s').read_text().splitlines():
        hit = re.match(r'^([ZYX])([0-9A-F]{4}):\t\t; push .* \(merged\)', line)
        if hit:
            merged['ZYX'.index(hit[1])].add(int(hit[2], 16))
    dead, site = set(), [0, 0, 0]
    for n in range(3):
        def mk(n):
            step0, write0 = m.cpus[n].step, m.cpus[n].wr8

            def ref_step():
                site[n] = m.cpus[n].pc
                return step0()

            def ref_write(a, v):
                (dead.add if site[n] in merged[n] else dead.discard)(a)
                return write0(a, v)
            m.cpus[n].step, m.cpus[n].wr8 = ref_step, ref_write
        mk(n)
    import bisect
    by_addr = sorted((v - s.base, k) for k, v in sym.items() if v - s.base >= 0 and (k[0] in 'ZYX' or k[0].islower()))
    addrs = [a for a, _ in by_addr]

    def where(pc):
        i = bisect.bisect_right(addrs, pc - s.base) - 1
        return '%s+%d' % (by_addr[i][1], pc - s.base - by_addr[i][0])
    expl = sound.Explosion()
    n54 = {'skip': 0}
    n54_write0 = m.n54.write

    def n54_write(v):
        n54_write0(v)
        if n54['skip']:
            n54['skip'] -= 1
        elif (v & 0xf0) in (0x30, 0x40):
            n54['skip'] = 4
        elif (v & 0xf0) in (0x10, 0x20) and m.cpus[2].pc >= 0x80:
            expl.trigger()
            n54['n'] = n54.get('n', 0) + 1
    m.n54.write = n54_write
    cycles = [0]

    def run_to(targets):
        total = 0
        while total < 2_000_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                cycles[0] += total
                return pc
            if pc in bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x, d7=%08x, a5=%08x, log=%s' % (pc - s.base, cpu.r_reg(R.D7), cpu.r_reg(R.A5), s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x (%s), d0=%08x d3=%08x a6=%08x g_ram[0:8]=%s latch=%s current=%d' % (cpu.r_pc() - s.base, where(cpu.r_pc()), cpu.r_reg(R.D0), cpu.r_reg(R.D3), cpu.r_reg(R.A6), bytes(mem.r_block(g_ram, 8)).hex(), bytes(mem.r_block(sym['latch'], 8)).hex(), mem.r8(sym['current'])))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    last = [None]
    level = [0]

    def compare(f):
        if args.verbose:
            st = sym['N51_state']
            print('f%d 51XX: held %d ram %s | ref ram %s | PORTO %02x ref %02x | latch %s ref %s' % (
                f, mem.r8(sym['n51_held']), [mem.r8(st + i) & 15 for i in range(16)], list(m.n51.mcu.ram[:16]),
                mem.r8(st + 86), m.n51.port_o, [mem.r8(sym['latch'] + i) for i in range(4)], m.latch[:4]))
        skip = set()
        for c in m.cpus:
            skip.update(range(c.sp - 64, c.sp))
        want = bytes(m.mem[0x7800:0xd000])
        got = bytes(mem.r_block(g_rom1 + 0x7800, 0x800)) + bytes(mem.r_block(g_ram, 0x5000))
        got2 = bytes(mem.r_block(g_block + 0x7900, 0x700))
        diff = [0x7800 + i for i in range(len(want)) if want[i] != got[i] and 0x7800 + i not in dead and 0x7800 + i not in skip]
        diff2 = [0x7900 + i for i in range(0x700) if want[0x100 + i] != got2[i] and 0x7900 + i not in dead and 0x7900 + i not in skip]
        if diff or diff2:
            raise RuntimeError('frame %d: %d + %d (sub half) RAM differences, ref pcs %s %s' % (
                f, len(diff), len(diff2), ['%04x' % c.pc for c in m.cpus],
                [(hex(a), hex(got[a - 0x7800]), hex(want[a - 0x7800])) for a in diff[:12]] +
                [('sub', hex(a), hex(got2[a - 0x7900]), hex(want[a - 0x7800])) for a in diff2[:6]]))
        lat = [mem.r8(sym['latch'] + i) for i in range(8)]
        if lat[:4] != m.latch[:4] or lat[4:] != m.latch[4:]:
            raise RuntimeError('frame %d: latches %s, reference %s' % (f, lat, m.latch))
        sc = [mem.r16(sym['scroll'] + 2 * i) for i in range(4)]
        if sc != [m.scroll[i] for i in range(4)] or mem.r16(sym['flip']) != m.flip:
            raise RuntimeError('frame %d: scroll %s flip %d, reference %s %d' % (f, sc, mem.r16(sym['flip']), m.scroll, m.flip))
        wsg = [mem.r8(g3_block + 0x6800 + i) & 15 for i in range(32)]
        if wsg != [v & 15 for v in m.sound]:
            raise RuntimeError('frame %d: the sound registers %s, reference %s' % (f, wsg, [v & 15 for v in m.sound]))
        ym = [mem.r8(sym['snd_ym'] + i) for i in range(11)]
        if ym != sound.ym_image(list(m.sound), level[0]):
            raise RuntimeError('frame %d: the YM registers %s, the model %s' % (f, ym, sound.ym_image(list(m.sound), level[0])))
        st = sym['N51_state']
        ram51 = [mem.r8(st + i) & 15 for i in range(64)]
        if not m.n51.held and ram51 != list(m.n51.mcu.ram):
            raise RuntimeError('frame %d: the 51XX\'s RAM differs: %s, reference %s' % (f, ram51, list(m.n51.mcu.ram)))
        if last[0] is not None and not mem.r8(sym['vblock_all']):
            now = bytes(mem.r_block(g_ram + 0x3000, 0x2000))
            marks = bytes(mem.r_block(sym['vblocks'], 256))
            for i in range(0x2000):
                if now[i] != last[0][i] and not marks[((0xb000 + i) >> 5) & 255]:
                    raise RuntimeError('frame %d: %04x changed, its block not marked (a writer missing in gen.py)' % (f, 0xb000 + i))
        last[0] = bytes(mem.r_block(g_ram + 0x3000, 0x2000))
        for i in range(256):
            mem.w8(sym['vblocks'] + i, 0)
        mem.w8(sym['vblock_all'], 0)

    state = {'t0': 0, 'joy': 0, 'mode': 'attract', 'coin_at': 300 + rnd.randrange(600)}

    def inputs(f):
        """cover.py's scripted play: sets the reference's and the build's inputs for frame f"""
        in0 = in1 = 0xff
        m.dswb |= 1
        if infinite:
            m.mem[0x8183] = 9
            mem.w8(g_ram + 0x0183, 9)
        mode = state['mode']
        if mode == 'attract' and f >= state['coin_at'] and not nocoin:
            mode = state['mode'] = 'coin'
            state['t0'] = f
        t0 = state['t0']
        if mode == 'coin':
            if f < t0 + 5: in1 &= ~0x10
            elif f < t0 + 40: pass
            elif players == 2 and f < t0 + 45: in1 &= ~0x10
            elif players == 2 and f < t0 + 80: pass
            elif f < t0 + 85: in1 &= ~(0x08 if players == 2 else 0x04)
            else: mode = state['mode'] = 'play'; state['t0'] = f
        if mode in ('play', 'over'):
            g = f - state['t0']
            if g % 12 == 0:
                state['joy'] = rnd.choice([0, 1, 2, 3, 4, 5, 6, 7, 8])
            bits = {1: 0x01, 2: 0x03, 3: 0x02, 4: 0x06, 5: 0x04, 6: 0x0c, 7: 0x08, 8: 0x09}.get(state['joy'], 0)
            in0 &= ~bits
            if rnd.random() < 0.15: in1 &= ~0x01
            if rnd.random() < 0.05: m.dswb &= ~1
        if mode == 'play' and m.n51.mcu.ram[3] == 0 and f - state['t0'] > 600:
            mode = state['mode'] = 'over'
            state['t0'] = f
        if mode == 'over' and f - state['t0'] > 300:
            mode = state['mode'] = 'attract'
            state['coin_at'] = f + 300
        m.in0, m.in1 = in0, in1
        mem.w8(sym['in0_kbd'], (~in0) & 0xff)
        mem.w8(sym['in1_kbd'], (~in1) & 0xff)
        mem.w8(sym['in2_kbd'], (~m.dswb) & 1)

    mem.w8(sym['vbl_pending'], 0)
    for f in range(args.frames):
        inputs(f)
        m.run_frame_port()
        level[0] = expl.step()
        if run_to({done, sym['sim_render_start']}) != done:
            resume()
            run_to({done})
        compare(f)
        resume()
        run_to({wait})
        mem.w8(sym['vbl_pending'], 1)
        resume()
        if f % 1000 == 999 and not args.quiet:
            print('%d frames exact' % (f + 1), flush=True)
    print('PASS: %d frames (seed %d), work RAM, latches, scroll registers and the 51XX exact; every tile RAM change marked'
          % (args.frames, args.seed))
    print('explosions started: %d' % n54.get('n', 0))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
