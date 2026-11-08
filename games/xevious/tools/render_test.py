"""The STE renderer (run/xevious_sim, Musashi) against the reference renderer: the reference machine plays (the scripted
play of ref/cover.py), every N frames its RAM, scroll registers and sprite registers are copied into the build, render_frame
draws, and the picture (4 planes, 224 x 288 pixels, rotated) is compared pixel by pixel with machine.render_raw() through the
colour map of tools/assets.py.  The pixels outside the picture area must stay black.

    python render_test.py [frames] [--seed N] [--start F] [--every N] [--png DIR]
"""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
import numpy as np
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import Xevious, Gfx
import assets
from paths import ROOT, build_dir

BUILD = build_dir('xevious')
STRIDE, GAME_X, PIC_Y0 = 256, 24, 32


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--start', type=int, default=300)
    ap.add_argument('--every', type=int, default=100)
    ap.add_argument('--png', default=None)
    ap.add_argument('--shots', default=None, help='a folder for the own pictures of the build (shot<frame>.png, 2x)')
    ap.add_argument('--tag', default='xevious_sim')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--prof', action='store_true', help='a histogram of where the render routine spends its cycles (symbols)')
    ap.add_argument('--entry', default='render_frame', help='(debugging) a routine to call instead')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'XEVIOUS.PRG'), run_dir=run, ram_kib=16384)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    if args.debug:
        orig = s.blitter.run
        calls = []

        def logged():
            b = s.blitter
            calls.append((b.reg32(0xA24), b.reg32(0xA32), b.reg16(0xA36), b.reg16(0xA38), s.io[0xA3A], s.io[0xA3B], b.reg16(0xA22), b.reg16(0xA30)))
            return orig()
        s.blitter.run = logged
    g_ram = sym['g_block'] + 0x8000
    bad = {sym['z80_badpc'], sym['z80_badpc'] + 4}

    hist = {}
    import bisect
    by = sorted((v, k) for k, v in sym.items() if not k.startswith('.'))
    byaddr = [a for a, _ in by]

    def run_to(targets, limit=900_000_000):
        total = 0
        while total < limit:
            c = cpu.execute(30).cycles
            total += c
            pc = cpu.r_pc()
            if args.prof and prof_on[0]:
                k = by[max(0, bisect.bisect_right(byaddr, pc) - 1)][1]
                hist[k] = hist.get(k, 0) + c
            if pc in targets:
                return total
            if pc in bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x' % (pc - s.base))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x' % (cpu.r_pc() - s.base))

    # the program's start: it runs the Z80 code; stop it right after the hardware set-up (at the first hook) and use its
    # state only for the renderer
    prof_on = [False]
    run_to({sym['sim_render_start']}, 900_000_000)
    ret = sym['sim_render_ret']
    g = Gfx()
    palette, pmap = assets.build_palette(g)
    pmap = np.array(pmap, np.uint8)
    m = Xevious(skip_tests=True, invincible=args.seed >= 31)
    rnd = random.Random(args.seed)
    state = {'mode': 'attract', 't0': 0, 'joy': 0, 'coin_at': 300 + rnd.randrange(300)}
    worst = 0
    tested = 0
    cycles = []
    for f in range(args.frames):
        m.in0 = m.in1 = 0xff
        m.dswb |= 1
        if args.seed >= 31:
            pass
        mode = state['mode']
        if mode == 'attract' and f >= state['coin_at']:
            mode = state['mode'] = 'coin'
            state['t0'] = f
        if mode == 'coin':
            t0 = state['t0']
            if f < t0 + 5: m.in1 &= ~0x10
            elif f < t0 + 85 and f >= t0 + 80: m.in1 &= ~0x04
            elif f >= t0 + 85: mode = state['mode'] = 'play'; state['t0'] = f
        if mode == 'play':
            gf = f - state['t0']
            if gf % 12 == 0:
                state['joy'] = rnd.choice([0, 1, 2, 3, 4, 5, 6, 7, 8])
            m.in0 &= ~{1: 0x01, 2: 0x03, 3: 0x02, 4: 0x06, 5: 0x04, 6: 0x0c, 7: 0x08, 8: 0x09}.get(state['joy'], 0)
            if rnd.random() < 0.15: m.in1 &= ~0x01
            if rnd.random() < 0.05: m.dswb &= ~1
            if m.n51.mcu.ram[3] == 0 and gf > 600:
                state['mode'] = 'attract'
                state['coin_at'] = f + 400
        m.run_frame_port()
        if f < args.start or (f - args.start) % args.every:
            continue
        # the state into the build
        for i, b in enumerate(bytes(m.mem[0x8000:0xd000])):
            mem.w8(g_ram + i, b)
        for i in range(4):
            mem.w16(sym['scroll'] + 2 * i, m.scroll[i])
        mem.w16(sym['flip'], m.flip)
        mem.w8(sym['vblock_all'], 1)
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, ret)
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym[args.entry])
        if args.entry == 'compose_bg':
            cpu.w_pc(sym['update_bg'])
            mem.w32(sp, sym['sim_render_ret'])
            run_to({ret})
            cpu.w_reg(R.A7, sp)
            mem.w32(sp, ret)
            cpu.w_pc(sym['compose_bg'])
        prof_on[0] = True
        cycles.append(run_to({ret}))
        prof_on[0] = False
        cpu.w_reg(R.A7, sp + 4)
        if args.debug:
            ring = bytes(mem.r_block(sym['ring'], 800 * 112))
            sh = bytes(mem.r_block(sym['shadow_bg'], 4096))
            print('ring nonzero bytes', sum(1 for b in ring if b), 'shadow nonzero', sum(1 for b in sh if b), 'scroll', m.scroll,
                  'bg code sample', bytes(m.mem[0xc800:0xc810]).hex(), 'attr', bytes(m.mem[0xb800:0xb810]).hex())
        if args.debug and args.png:
            from PIL import Image
            ringb = np.frombuffer(bytes(mem.r_block(sym['ring'], 800 * 112)), np.uint8).reshape(800, 14, 4, 2)
            w = (ringb[:, :, :, 0].astype(np.uint16) << 8) | ringb[:, :, :, 1]
            ri = np.zeros((800, 224), np.uint8)
            for k in range(4):
                for bit in range(16):
                    ri[:, bit::16] |= (((w[:, :, k] >> (15 - bit)) & 1) << k).astype(np.uint8)
            Image.fromarray(np.array(palette, np.uint8)[ri]).save(str(Path(args.png) / 'ring.png'))
        draw = mem.r32(sym['draw_screen_address'])
        buf = np.frombuffer(bytes(mem.r_block(draw, 0x20000)), np.uint8).reshape(512, STRIDE)
        if args.debug:
            print('blitter regs', bytes(s.io[0xA20:0xA40]).hex(), bytes(mem.r_block(0xFF8A20, 32)).hex(), 'ring', hex(sym['ring']), 'a3c', hex(s.io[0xA3C]))
            sw = sym['ring'] + ((m.scroll[0] + 20) & 511) * 112
            print('src window', bytes(mem.r_block(sw, 16)).hex(), 'dst', bytes(mem.r_block(mem.r32(sym['draw_screen_address']) + 32 * 256 + 24, 16)).hex(), 'draw_screen_address', hex(mem.r32(sym['draw_screen_address'])))
            allmem = bytes(mem.r_block(0, 0x1000000))
            pat = bytes(mem.r_block(sw, 16))
            hits = []; i = allmem.find(pat)
            while i >= 0 and len(hits) < 8:
                hits.append(hex(i)); i = allmem.find(pat, i + 1)
            print('pattern found at', hits)
            print('blitter calls', len(calls), [tuple(hex(v) if i < 2 else v for i, v in enumerate(c)) for c in calls[-5:]])
            print('draw screen', hex(draw), 'picture nonzero bytes', int((buf[PIC_Y0:PIC_Y0 + 288, GAME_X:GAME_X + 112] != 0).sum()), 'whole', int((buf != 0).sum()))
        pic = buf[PIC_Y0:PIC_Y0 + 288, GAME_X:GAME_X + 112].reshape(288, 14, 4, 2)      # [line][group][plane][byte]
        words = (pic[:, :, :, 0].astype(np.uint16) << 8) | pic[:, :, :, 1]              # [line][group][plane]
        idx = np.zeros((288, 224), np.uint8)
        for k in range(4):
            for bit in range(16):
                idx[:, bit::16] |= (((words[:, :, k] >> (15 - bit)) & 1) << k).astype(np.uint8)
        if args.shots:
            from PIL import Image
            Image.fromarray(np.array(palette, np.uint8)[idx]).resize((448, 576), Image.NEAREST).save(str(Path(args.shots) / ('shot%d.png' % f)))
        raw = m.render_raw()
        want = pmap[raw[::-1, :].T]                                                       # [display line][display x]
        diff = int((idx != want).sum())
        outside = int(buf.sum() - buf[PIC_Y0:PIC_Y0 + 288, GAME_X:GAME_X + 112].astype(np.int64).sum())
        tested += 1
        worst = max(worst, diff)
        print('frame %5d: %5d of %d pixels differ; %d bytes outside the picture; render %d cycles (Musashi)' % (
            f, diff, 288 * 224, outside, cycles[-1]), flush=True)
        if args.png and diff:
            from PIL import Image
            pal = np.array(palette, np.uint8)
            dd = (idx != want)
            ys, xs = np.nonzero(dd)
            print('first differing pixels (line, x, got, want):', [(int(y), int(x), int(idx[y, x]), int(want[y, x])) for y, x in zip(ys[:12], xs[:12])], 'bbox', (int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())))
            Image.fromarray(np.concatenate([pal[idx], pal[want]], axis=1)).resize((896, 576), Image.NEAREST).save(
                str(Path(args.png) / ('cmp%d.png' % f)))
    if args.prof:
        tot = sum(hist.values())
        for k, v in sorted(hist.items(), key=lambda kv: -kv[1])[:25]:
            print('%-24s %5.1f%%  %d' % (k, 100 * v / tot, v // max(1, tested)))
    print('%s: %d pictures, worst %d differing pixels' % ('PASS' if worst == 0 else 'FAIL', tested, worst))
    sys.exit(0 if worst == 0 else 1)


if __name__ == '__main__':
    main()
