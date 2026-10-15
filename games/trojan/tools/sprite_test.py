"""Sprites at every edge against the reference renderer (render.s through engine/sim.py, tools/assets.py Oracle).

    python games/trojan/tools/sprite_test.py

A background state of the attract mode (the reference at frame 700: its RAM, palette and registers) is drawn with test
sprite lists: for each of the 16 fine scrolls (bg1's x = 16 n + f) and both rings, sprites across the left and right
edges at every pixel position near them (clipped at the black words' boundary, whole in the masked word, culled
beyond), in the top and bottom guard lines, with flip x, with transparent holes (codes whose rows have pen 15 pixels
between opaque ones), and across a 64 KB boundary of the ring.  Every picture must equal the reference's; the side
bands black but where render.s draws a sprite whole into a masked word (its band part: screen x 32 - f .. 31 and
288 .. 303 - f).
"""
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim
from machine68k import Register as R
from machine import TrojanPort, Video
from assets import Oracle
from paths import ROOT, build_dir
from render_test import picture

STRIDE = 416
GUARD_T = 32


class Renderer:
    def __init__(self):
        run = ROOT / 'run' / 'trojan_sim'
        self.sim = Sim(str(run / 'TROJAN.PRG'), ram_kib=16384, run_dir=run)
        self.mem, self.cpu = self.sim.mem, self.sim.cpu
        self.sym = {k: v + self.sim.base for k, v in
                    self.sim.symbols(build_dir('trojan') / 'trojan_sim.map').items()}
        self.cpu.w_reg(R.A7, self.sym['own_stack_top'])
        self.cpu.w_sr(0x2700)
        self.call('init_video')

    def call(self, name):
        sp = self.cpu.r_reg(R.A7) - 4
        ret = self.sym['sim_render_ret']
        self.mem.w32(sp, ret)
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym[name])
        used = 0
        while used < 200_000_000:
            used += self.cpu.execute(4000).cycles
            if self.cpu.r_pc() == ret:
                return used
        raise RuntimeError('%s stopped at %06x' % (name, self.cpu.r_pc()))

    def render(self, m):
        mem, sym = self.mem, self.sym
        z = sym['g_block'] + 0x8000 - 0x10000
        mem.w_block(z + 0xC000, bytes(m.mem[0xC000:0xF806]))
        for flag in ('pal_written', 'bg_written', 'fg_written'):
            mem.w8(sym[flag], 1)
        mem.w_block(sym['tr_sprites'], bytes(m.sprites))
        self.call('render_frame')
        return picture(mem, sym), mem.r8(sym['flip_fine'])


def hole_codes(v, n=4):
    """sprite codes with a transparent pixel between opaque ones in a row"""
    out = []
    for code, t in enumerate(v.sprites):
        for row in t:
            o = np.nonzero(row != 15)[0]
            if len(o) > 1 and (row[o[0]:o[-1] + 1] == 15).any():
                out.append(code)
                break
        if len(out) == n:
            break
    return out


def check(r, oracle, m, label):
    mine, f = r.render(m)
    want = oracle.frame(m)
    diff = np.argwhere(mine[:, 32:288] != want)
    band = np.hstack((mine[:, :32 - f], mine[:, 304 - f:] if f else mine[:, 288:]))
    if len(diff) or band.any():
        from PIL import Image
        out = build_dir('trojan') / 'sprite_diff.png'
        full = np.hstack((np.zeros((240, 32), np.uint8), want, np.zeros((240, 32), np.uint8)))
        Image.fromarray(np.hstack((oracle.rgb[mine], oracle.rgb[full]))).save(out)
        return '%s: %d pixels differ, %d band pixels; %s' % (label, len(diff), int(np.count_nonzero(band)), out)
    return None


def run():
    r = Renderer()
    oracle = Oracle()
    v = Video()
    m = TrojanPort()
    m.run_to_idle()
    m.booted = True
    for f in range(700):
        m.run_frame_port()
    holes = hole_codes(v)
    base = bytes(m.mem[0xF800:0xF806])
    cases = 0
    for ring in range(2):
        for f in range(16):
            sx = 16 * 7 + f
            m.mem[0xF800], m.mem[0xF801] = sx & 255, sx >> 8
            m.regs['scroll1x'] = sx
            # the line of the ring where a 64 KB boundary lies: a sprite across it
            work = r.mem.r32(r.sym['ring_base'] + 4 * (1 - r.mem.r16(r.sym['ring_index']) // 4))
            cross = ((work + 0xFFFF) & ~0xFFFF) - work
            yc = cross // STRIDE - GUARD_T + 8 - 7
            positions = [(-15, 40), (-9, 60), (-1, 80), (0, 100), (1, 120), (7, 140), (240, 40), (241, 60), (247, 80),
                         (249, 100), (255, 120), (-16, 140), (256, 160), (100, 1), (120, 245), (140, 0xf9),
                         (160, yc if 0 < yc < 240 else 180)]
            spr = bytearray([0, 0, 0xF8, 0] * 96)
            for i, (x, y) in enumerate(positions):
                code = holes[i % len(holes)] if i % 3 else 37 + i
                attr = (0x01 if x < 0 or x >= 256 else 0) | (0x10 if i & 1 else 0) | ((i % 8) << 1)
                attr |= ((code >> 10 & 1) << 7) | ((code >> 9 & 1) << 5) | ((code >> 8 & 1) << 6)
                spr[4 * i:4 * i + 4] = bytes([code & 255, attr, y & 255, x & 255])
            m.sprites[:] = spr
            err = check(r, oracle, m, 'ring %d f %d' % (ring, f))
            cases += 1
            if err:
                return err, cases
    m.mem[0xF800:0xF806] = base
    return None, cases


def main():
    err, cases = run()
    if err:
        print('FAIL', err)
        return 1
    print('PASS: %d pictures (2 rings x 16 fine scrolls, 17 sprites each: both edges at every position near them, the '
          'guards, flips, holes, a 64 KB crossing)' % cases)
    return 0


if __name__ == '__main__':
    sys.exit(main())
