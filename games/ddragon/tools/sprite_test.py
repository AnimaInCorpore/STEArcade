"""Sprites at every edge against the reference renderer (render.s through engine/sim.py, tools/assets.py Oracle).

    python games/ddragon/tools/sprite_test.py

A play state (ref/cover.py seed -1, the reference at frame 2400: its RAM, palette and registers) with the text layer
cleared (its frame of solid characters would hide the picture's edges) is drawn with test sprite lists: for each of
the 16 fine scrolls (x = 16 n + f) and both rings, sprites across the left and right edges at every pixel position
near them (clipped at the black words' boundary, whole in the masked word, culled beyond), 32 x 32 objects across
both edges, in the top and bottom guard lines, flipped in x and y, with transparent holes (codes whose rows have pen
0 pixels between opaque ones), and across a 64 KB boundary of the ring where one lies in the lines sprites are drawn
into (ring 1: picture line -7, in the top guard; ring 0's is above them).  Every picture must equal the reference's;
the side bands black but where render.s draws a sprite whole into a masked word (its band part: screen x 32 - f ..
31 and 288 .. 303 - f).
"""
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine"),
                str(Path(__file__).resolve().parents[1] / "ref")]
from sim import Sim
from machine68k import Register as R
from machine import DDragonPort, DSW0, Video
from assets import Oracle
from paths import ROOT, build_dir
import cover

STRIDE = 416


def screen(mem, sym):
    """the 240 x 320 colour indices the STE shows (the window from flip_addr, its fine scroll)"""
    base = mem.r32(sym["flip_addr"])
    fine = mem.r8(sym["flip_fine"])
    data = np.frombuffer(bytes(mem.r_block(base, 240 * STRIDE)), np.uint8).reshape(240, STRIDE // 8, 4, 2)
    planes = (data[..., 0].astype(np.uint16) << 8) | data[..., 1]
    bits = np.unpackbits(planes.astype(">u2").view(np.uint8).reshape(240, STRIDE // 8, 4, 2), axis=3)
    bits = bits.reshape(240, STRIDE // 8, 4, 16)
    pix = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(240, STRIDE // 8 * 16)
    return pix[:, fine:fine + 320].astype(np.uint8), fine


class Renderer:
    def __init__(self):
        run = ROOT / "run" / "ddragon_sim"
        self.sim = Sim(str(run / "DDRAGON.PRG"), ram_kib=16384, run_dir=run)
        self.mem, self.cpu = self.sim.mem, self.sim.cpu
        self.sym = {k: v + self.sim.base for k, v in
                    self.sim.symbols(build_dir("ddragon") / "ddragon_sim.map").items()}
        self.cpu.w_reg(R.A7, self.sym["own_stack_top"])
        self.cpu.w_sr(0x2700)
        self.call("init_video")

    def call(self, name):
        sp = self.cpu.r_reg(R.A7) - 4
        ret = self.sym["sim_render_ret"]
        self.mem.w32(sp, ret)
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym[name])
        used = 0
        while used < 400_000_000:
            used += self.cpu.execute(4000).cycles
            if self.cpu.r_pc() == ret:
                return used
        raise RuntimeError("%s stopped at %06x" % (name, self.cpu.r_pc()))

    def render(self, m):
        mem, sym = self.mem, self.sym
        g = sym["g_mem"]
        mem.w_block(g + 0x1000, bytes(m.mem[0x1000:0x2000]))
        mem.w_block(g + 0x2800, bytes(m.mem[0x2800:0x3800]))
        mem.w8(sym["g_bankreg"], m.bankreg)
        mem.w8(sym["g_scroll_lo"], m.scroll_lo[0])
        mem.w8(sym["g_scroll_lo"] + 1, m.scroll_lo[1])
        for flag in ("pal_written", "fg_written", "spr_written", "bg_written"):
            mem.w8(sym[flag], 1)
        self.call("render_frame")
        return screen(mem, sym)


def hole_codes(v, n=4):
    """sprite codes with a transparent pixel (pen 0) between opaque ones in a row"""
    out = []
    for code, t in enumerate(v.sprites):
        for row in t:
            o = np.nonzero(row != 0)[0]
            if len(o) > 1 and (row[o[0]:o[-1] + 1] == 0).any():
                out.append(code)
                break
        if len(out) == n:
            break
    return out


def entry(code, colour, x, y, size=0, fx=False, fy=False):
    """a sprite RAM entry (5 bytes, MAME's draw_sprites) for a sprite at picture x, y (x -15..496, y -23..488)"""
    bx = 240 - x
    xh = 0
    if bx < 0:
        bx += 256
        xh = 2
    by = 232 - y
    yh = 0
    if by < 0:
        by += 256
        yh = 1
    attr = 0x80 | (size << 4) | (8 if fx else 0) | (4 if fy else 0) | xh | yh
    return bytes([by & 255, attr, (colour << 4) | (code >> 8 & 15), code & 255, bx & 255])


def check(r, oracle, m, label):
    mine, f = r.render(m)
    want = oracle.frame(m)
    diff = np.argwhere(mine[:, 32:288] != want)
    band = np.hstack((mine[:, :32 - f], mine[:, 304 - f:] if f else mine[:, 288:]))
    if len(diff) or band.any():
        from PIL import Image
        out = build_dir("ddragon") / "sprite_diff.png"
        full = np.hstack((np.zeros((240, 32), np.uint8), want, np.zeros((240, 32), np.uint8)))
        Image.fromarray(np.hstack((oracle.rgb[mine], oracle.rgb[full]))).save(out)
        return "%s: %d pixels differ, %d band pixels; %s" % (label, len(diff), int(np.count_nonzero(band)), out)
    return None


def run():
    r = Renderer()
    oracle = Oracle()
    v = Video()
    dsw1, inputs = cover.schedule(-1)
    m = DDragonPort(DSW0, dsw1)
    for f in range(2400):
        p1, p2, extra, coins = inputs(f)
        if coins:
            m.coin(coins)
        m.inputs[0], m.inputs[1], m.inputs[2] = p1, p2, extra
        m.run_frame_port()
    m.mem[0x1800:0x2000] = bytes(0x800)              # (the text layer: code 0, blank)
    holes = hole_codes(v)
    sy = m.scroll_lo[1] | (m.bankreg & 2) << 7
    m.mem[0x2800:0x3000] = bytes(0x800)
    r.render(m)                                     # (the rings' picture line 0: the same for both, one scroll y)
    ring0 = r.mem.r32(r.sym["ring_base"] + r.mem.r16(r.sym["ring_index"]))
    line0 = (r.mem.r32(r.sym["flip_addr"]) - ring0) // STRIDE
    cases = crossings = 0
    for ring in range(2):
        for f in range(16):
            sx = 16 * 7 + f
            m.scroll_lo[0] = sx & 255
            m.bankreg = (m.bankreg & ~1) | (sx >> 8)
            # the picture line where a 64 KB boundary lies in the ring drawn next: a sprite across it
            work = r.mem.r32(r.sym["ring_base"] + 4 - r.mem.r16(r.sym["ring_index"]))
            cross = ((work + 0xFFFF) & ~0xFFFF) - work
            yc = cross // STRIDE - line0 - 7
            crossings += -15 <= yc < 224
            positions = [(-15, 40, 0), (-9, 60, 0), (-1, 80, 0), (0, 100, 0), (1, 120, 0), (7, 140, 0),
                         (240, 40, 0), (241, 60, 0), (247, 80, 0), (249, 100, 0), (255, 120, 0), (256, 140, 0),
                         (300, 160, 0), (100, -20, 0), (120, 236, 0), (140, -8, 0), (-3, 170, 3), (245, 180, 3),
                         (14, 200, 1), (230, 20, 2), (160, yc if -15 <= yc < 224 else 180, 0)]
            spr = bytearray(0x800)
            for i, (x, y, size) in enumerate(positions):
                code = holes[i % len(holes)] if i % 3 else 37 * i + 5
                spr[5 * i:5 * i + 5] = entry(code, i % 8, x, y, size, bool(i & 1), bool(i & 2))
            m.mem[0x2800:0x3000] = bytes(spr)
            err = check(r, oracle, m, "ring %d f %d" % (ring, f))
            cases += 1
            if err:
                return err, cases, crossings
    return None, cases, crossings


def main():
    err, cases, crossings = run()
    if err:
        print("FAIL", err)
        return 1
    print("PASS: %d pictures (2 rings x 16 fine scrolls, 21 sprites each: both edges at every position near them, "
          "32 x 32 objects across them, the guards, flips, holes; a sprite across a 64 KB boundary in %d of them)"
          % (cases, crossings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
