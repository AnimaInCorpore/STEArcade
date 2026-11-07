"""Rolling Thunder (Namco System 86, MAME `rthunder`, src/mame/namco/namcos86.cpp + namcos86_v.cpp): the reference board.

CPUs (all 1.536 MHz = 49.152 MHz / 32; the MCU's E clock): cpu1 and cpu2, MC6809E (engine/m6809.py), and the HD63701V0
MCU (engine/hd63701.py, internal ROM cus60-60a1.mcu at $F000, the sub program rt3_4.6b at $4000-$BFFF).  There is no
MMU: each 6809 has its own map (cpu1_map, rthunder_cpu2_map), sharing 6 KB of RAM ($4400-$57FF of cpu1 = $0400-$17FF of
cpu2), the sprite RAM, and the two tile RAMs (the CUS42 + CUS43 pairs of tilemaps).  The CUS30 sound RAM (1 KB at
cpu1 $4000, the MCU's $1000) is the MCU's mailbox to cpu1: the MCU reads the controls and DIP switches (IN0 / IN1 at
$2020 / $2021, IN2 on its port 1, DSWA / DSWB at $2030 / $2031) and writes them there; the YM2151 (at $2000) and the
63701X sample player (cpu1 writes at $6000-$7FFF) are not rendered here (sound is a later step).

Frame: 384 x 264 pixel clocks at 6.144 MHz = 25344 CPU cycles (60.6 Hz), the picture lines 16-239, pixels 67-354
(288 x 224).  The vertical blank's start (line 240) asserts IRQ on cpu1 and cpu2 (until the program writes $8400 /
$8800: int_ack1_w / int_ack2_w) and takes IRQ1 on the MCU (HOLD_LINE: cleared when taken).  The sprite list is latched
there (the program wrote $7F2 of the sprite RAM).  The CPUs interleave as MAME's scheduler does (1/48000 s quanta,
`set_maximum_quantum`; the two 6809 synchronize through a semaphore at $5606/$5607 and need it).

Video (namcos86_v.cpp): the picture is the back colour pen (8 * backcolor + 7 of the tile pens), then eight priority
levels of the four tilemaps (layer priority = bits 9-11 of its X scroll), then the sprites (CUS39) against the priority
bitmap.  `render_raw` gives the 9 bit indirect colour (0-511: the palette PROMs) of every pixel; `render_rgb` the picture.
"""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from mamegfx import resistor_weights, combine, decode_gfx
import namcos1 as S1                                       # (the scheduler's constants and the YM2151 status model)

CPU_HZ = 1536000
LINE = 96
LINES = 264
FRAME = LINE * LINES
AS, CPU_AS, SCAN_AS, FRAME_AS = S1.AS, S1.CPU_AS, S1.SCAN_AS, S1.FRAME_AS
_SHIFT, _DIV = S1._SHIFT, S1._DIV
QUANTUM_AS = AS // 48000                                   # set_maximum_quantum(attotime::from_hz(48000))
SOUND_UPDATE_AS = S1.SOUND_UPDATE_AS
VIS_X0, VIS_X1, VIS_Y0, VIS_Y1 = 67, 354, 16, 239          # set_raw(..., 384, 3+8*8, 3+44*8, 264, 2*8, 30*8)
WIDTH, HEIGHT = VIS_X1 - VIS_X0 + 1, VIS_Y1 - VIS_Y0 + 1  # 288 x 224
DSWA, DSWB = 0xFF, 0xD7                                    # the driver's default DIP switches
FILES = {
    "cpu1": [("rt3_1b.9c", 0x8000)],
    "cpu2": [("rt3_3.12d", 0x0000), ("rt3_2b.12c", 0x8000)],
    "tiles_0": [("rt1_7.7r", 0x00000), ("rt1_8.7s", 0x10000)],
    "tiles_1": [("rt1_5.4r", 0x00000), ("rt1_6.4s", 0x08000)],
    "sprites": [("rt1_%d.12%s" % (n, c), 0x10000 * i) for i, (n, c) in
                enumerate([(9, "h"), (10, "k"), (11, "l"), (12, "m"), (13, "p"), (14, "r"), (15, "t"), (16, "u")])],
    "bankeddata": [("rt1_17.f1", 0x00000), ("rt1_18.h1", 0x10000), ("rt3_19.k1", 0x20000), ("rt3_20.m1", 0x30000)],
    "mcusub": [("rt3_4.6b", 0)],
    "mcu": [("cus60-60a1.mcu", 0)],
    "proms": [("rt1-1.3r", 0), ("rt1-2.3s", 0x200), ("rt1-3.4v", 0x400), ("rt1-4.5v", 0xC00), ("rt1-5.6u", 0x1400)],
}
SIZES = {"cpu1": 0x10000, "cpu2": 0x10000, "tiles_0": 0x18000, "tiles_1": 0xC000, "sprites": 0x80000,
         "bankeddata": 0x40000, "mcusub": 0x8000, "mcu": 0x1000, "proms": 0x1420}


def load_regions(romdir=None):
    romdir = Path(romdir or EXTRACTED / "rthunder")
    r = {}
    for region, files in FILES.items():
        r[region] = bytearray(SIZES[region])
        for name, start in files:
            data = (romdir / name).read_bytes()
            r[region][start:start + len(data)] = data
    return {k: bytes(v) for k, v in r.items()}


class YM2151(S1.YM2151):
    """the status model of the sound board; the chip's IRQ line is not connected on System 86"""

    def check_interrupts(self):
        self.irq_state = bool(self.status & 3)


class Rthunder:
    def __init__(self, regions=None, cpus=True):
        r = regions or load_regions()
        self.r = r
        self.rom1, self.rom2 = r["cpu1"], r["cpu2"]
        self.banked = r["bankeddata"]
        self.vram = [bytearray(0x2000), bytearray(0x2000)]    # the two CUS42 / CUS43 pairs (layer 1 at +$1000)
        self.shared = bytearray(0x1800)                       # cpu1 $4000-$57FF = cpu2 $0000-$17FF
        self.spriteram = bytearray(0x800)
        self.cus30 = bytearray(0x400)                         # CUS30 wave data, sound registers, shared RAM
        self.mcu_ram = bytearray(0xC00)                       # MCU $1400-$1FFF
        self.bank1 = 0
        self.bank2 = 0
        self.tilebank = 0
        self.backcolor = 0
        self.scroll = [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]]  # per tilegen: x hi, x lo, y, then layer 1's
        self.xscroll = [[0, 0], [0, 0]]
        self.yscroll = [[0, 0], [0, 0]]
        self.copy_sprites = False
        self.flip = False
        self.in0 = self.in1 = self.in2 = 0xFF
        self.dsw = [DSWA, DSWB]
        self.irq_pending = [False, False]
        self.wdog = 0
        self.frame = 0
        self.pcm_writes = []
        self.mcu_patch_log = []
        self._gfx = None
        self.prom = r["proms"]
        # the scheduler (see engine/namcos1.py)
        self.base = 0
        self.local = [0, 0, 0]
        self.suspended = [False, False, False]
        self.executing = None
        self.timers = []
        self.seq = 0
        self.queues = {}
        self.stop = False
        self.vblank_due = False
        self.deferred = []
        self.aborted = False
        if cpus:
            self.make_cpus()

    # ---- memory maps ----------------------------------------------------------
    def rd1(self, a):
        if a < 0x2000:
            return self.vram[0][a]
        if a < 0x4000:
            return self.vram[1][a - 0x2000]
        if a < 0x4400:
            return self.cus30[a & 0x3FF]
        if a < 0x5800:
            return self.shared[a - 0x4000]
        if a < 0x6000:
            return self.spriteram[a - 0x5800]
        if a < 0x8000:
            return self.banked[self.bank1 * 0x2000 + a - 0x6000]
        return self.rom1[a]

    def wr1(self, a, v):
        if a < 0x2000:
            self.vram[0][a] = v
        elif a < 0x4000:
            self.vram[1][a - 0x2000] = v
        elif a < 0x4400:
            self.cus30[a & 0x3FF] = v
        elif a < 0x5800:
            self.shared[a - 0x4000] = v
        elif a < 0x6000:
            self.sprite_w(a - 0x5800, v)
        elif a < 0x8000:                                      # cus115_w: bank select and 63701X sample player
            sel = ((a - 0x6000) & 0x1E00) >> 9
            if sel == 4:
                self.bank1 = v & 0x1F
            elif sel < 4:
                self.pcm_writes.append((sel, v))
        elif a == 0x8000:
            self.watchdog(0)
        elif a == 0x8400:
            self.set_line(0, "irq", False)                    # int_ack1_w
        elif 0x8800 <= a < 0x9000:
            bit = (a - 0x8800) >> 10 & 1                      # tilebank_select_w: offset bit 10
            self.tilebank = bit
        elif 0x9000 <= a < 0x9007 and a != 0x9003:
            i = a - 0x9000 if a < 0x9003 else a - 0x9004      # tilegen 0, layer 0: 9000-9002, layer 1: 9004-9006
            self.scroll_w(0, 0 if a < 0x9003 else 1, i, v)
        elif 0x9400 <= a < 0x9407 and a != 0x9403:
            i = a - 0x9400 if a < 0x9403 else a - 0x9404
            self.scroll_w(1, 0 if a < 0x9403 else 1, i, v)
        elif a == 0xA000:
            self.backcolor = v
        # (0x9003: bankswitch1_w does nothing with the expansion ROM board)

    def rd2(self, a):
        if a < 0x1800:
            return self.shared[a]
        if a < 0x2000:
            return self.spriteram[a - 0x1800]
        if a < 0x4000:
            return self.vram[0][a - 0x2000]
        if a < 0x6000:
            return self.vram[1][a - 0x4000]
        if a < 0x8000:
            return self.rom2[self.bank2 * 0x2000 + a - 0x6000]
        return self.rom2[a]

    def wr2(self, a, v):
        if a < 0x1800:
            self.shared[a] = v
        elif a < 0x2000:
            self.sprite_w(a - 0x1800, v)
        elif a < 0x4000:
            self.vram[0][a - 0x2000] = v
        elif a < 0x6000:
            self.vram[1][a - 0x4000] = v
        elif a == 0x8000:
            self.watchdog(1)
        elif a == 0x8800:
            self.set_line(1, "irq", False)                    # int_ack2_w
        elif a == 0xD803:
            self.bank2 = v & 3

    def scroll_w(self, dev, layer, off, v):
        if off == 0:
            self.xscroll[dev][layer] = (self.xscroll[dev][layer] & 0xFF) | (v << 8)
        elif off == 1:
            self.xscroll[dev][layer] = (self.xscroll[dev][layer] & 0xFF00) | v
        else:
            self.yscroll[dev][layer] = v

    def sprite_w(self, o, v):
        self.spriteram[o] = v
        if o == 0x7F2:
            self.copy_sprites = True
        if o == 0x7F6:
            self.flip = bool(v & 1)

    def watchdog(self, bit):
        self.wdog |= 1 << bit
        if self.wdog == 3:
            self.wdog = 0

    def dsw0(self):
        a, b = self.dsw
        hi = ((a & 1) << 4) | ((a & 4) << 3) | ((a & 0x10) << 2) | ((a & 0x40) << 1)
        lo = (b & 1) | ((b & 4) >> 1) | ((b & 0x10) >> 2) | ((b & 0x40) >> 3)
        return hi | lo

    def dsw1(self):
        a, b = self.dsw
        hi = ((a & 2) << 3) | ((a & 8) << 2) | ((a & 0x20) << 1) | (a & 0x80)
        lo = ((b & 2) >> 1) | ((b & 8) >> 2) | ((b & 0x20) >> 3) | ((b & 0x80) >> 4)
        return hi | lo

    def mcu_rd(self, a):
        if 0x1000 <= a < 0x1400:
            return self.cus30[a & 0x3FF]
        if 0x1400 <= a < 0x2000:
            return self.mcu_ram[a - 0x1400]
        if a in (0x2000, 0x2001):
            return self.ym.read_status()
        if a == 0x2020:
            return self.in0
        if a == 0x2021:
            return self.in1
        if a == 0x2030:
            return self.dsw0()
        if a == 0x2031:
            return self.dsw1()
        if 0x4000 <= a < 0xC000:
            return self.r["mcusub"][a - 0x4000]
        return 0

    def mcu_wr(self, a, v):
        if 0x1000 <= a < 0x1400:
            self.cus30[a & 0x3FF] = v
        elif 0x1400 <= a < 0x2000:
            self.mcu_ram[a - 0x1400] = v
        elif a in (0x2000, 0x2001):
            self.ym.write(a & 1, v)

    # ---- CPUs and the scheduler (MAME's device_scheduler, as engine/namcos1.py) -------------
    def make_cpus(self):
        from m6809 import M6809
        from hd63701 import HD63701
        self.cpu1 = M6809(self.rd1, self.wr1)
        self.cpu2 = M6809(self.rd2, self.wr2)
        self.ym = YM2151(self)
        self.mcu = HD63701(self.r["mcu"], self.mcu_rd, self.mcu_wr, in_p1=lambda: self.in2,
                           in_p2=lambda: 0xFF, out_p1=lambda v, ddr: None, out_p2=lambda v, ddr: None)
        self.mcu.irq_hook = lambda c, line: c.set_irq1(False) if line == 0 else None    # irq0_line_hold
        self.mcu.on_rmcr = self.mcu_rmcr
        self.sci_timer = None
        self.cpus = [self.cpu1, self.cpu2, self.mcu]
        self.cpu1.reset()
        self.cpu2.reset()
        self.local[0] = self.cpu1.cycles * CPU_AS
        self.local[1] = self.cpu2.cycles * CPU_AS
        self.timer(FRAME_AS, self.vblank_begin)
        self.timer(SOUND_UPDATE_AS, self.sound_update)

    now = S1.NamcoS1.now
    timer = S1.NamcoS1.timer
    cancel = S1.NamcoS1.cancel
    synchronize = S1.NamcoS1.synchronize
    set_line = S1.NamcoS1.set_line
    mcu_rmcr = S1.NamcoS1.mcu_rmcr

    def at_end(self, fn):
        """fn() when the executing 6809's instruction is done; at once for the MCU and outside a CPU"""
        i = self.executing
        if i is not None and i < 2:
            self.deferred.append(fn)
            c = self.cpus[i]
            c.end = c.cycles
        else:
            fn()

    def abort(self):
        i = self.executing
        c = self.cpus[i]
        self.aborted = True
        if i < 2:
            c.end = c.cycles
        else:
            c.icount = 0

    def apply_line(self, cpu, line):
        for state in self.queues.pop((cpu, line)):
            c = self.cpus[cpu]
            if cpu == 2:
                c.set_irq1(state)
            else:
                c.set_irq(state)

    def timeslice(self):
        timers = self.timers
        cpus, local, suspended = self.cpus, self.local, self.suspended
        while self.base < timers[0][0]:
            target = self.base + QUANTUM_AS
            if timers[0][0] < target:
                target = timers[0][0]
            for i in range(3):
                delta = target - local[i]
                if delta >= CPU_AS:
                    n = (delta >> _SHIFT) // _DIV
                    if suspended[i]:
                        local[i] += n * CPU_AS            # held (the port's schedule): its time passes
                        if local[i] < target:
                            target = max(local[i], self.base)
                        continue
                    c = cpus[i]
                    self.executing = i
                    self.slice_start = start = c.cycles
                    if i == 2:
                        c.icount = 0
                        c.run(n)
                    else:
                        end = start + n
                        while True:
                            c.run(end - c.cycles)
                            if not self.deferred:
                                break
                            d, self.deferred = self.deferred, []
                            self.aborted = False
                            for fn in d:
                                fn()
                            if self.aborted or c.cycles >= end:
                                break
                    self.executing = None
                    local[i] += (c.cycles - start) * CPU_AS
                    if local[i] < target:
                        target = max(local[i], self.base)
            self.base = target
        while timers and timers[0][0] <= self.base and not self.stop:
            t = timers.pop(0)
            t[2]()

    def vblank_begin(self):
        self.timer(self.base + FRAME_AS, self.vblank_begin)
        self.vblank_due = True
        self.stop = True

    def vblank_callback(self):
        self.vblank_due = False
        if self.copy_sprites:                                  # screen_vblank -> copy_sprites
            for i in range(0, 0x800, 16):
                self.spriteram[i + 10:i + 16] = self.spriteram[i + 4:i + 10]
            self.copy_sprites = False
        self.set_line(0, "irq", True)                          # irq0_line_assert
        self.set_line(1, "irq", True)
        self.set_line(2, "irq", True)                          # irq0_line_hold

    def sound_update(self):
        self.timer(self.base + SOUND_UPDATE_AS, self.sound_update)

    def run_frame(self):
        """one arcade frame, ending at the start of the vertical blank (MAME's frame_done)"""
        if self.vblank_due:
            self.vblank_callback()
        self.stop = False
        while not self.stop:
            self.timeslice()
        self.frame += 1

    # ---- video -------------------------------------------------------------------------
    def palette(self, int_weights=False):
        """the 512 indirect colours (r, g, b) of namcos86_palette.  The 0.286 source computes `double` weights
        (int_weights=False); the WolfMAME 0.248 binary behaves as if the four weights were rounded to integers first
        (14, 31, 67, 143: 398 of the 4096 pens are one level off), so the comparison with that binary uses
        int_weights=True."""
        res = [2200, 1000, 470, 220]
        w = resistor_weights(0, 255, -1.0, (res, 0, 0), (res, 0, 0), (res, 0, 0))
        if int_weights:
            w = [[float(round(x)) for x in n] for n in w]
        p = self.prom
        out = np.zeros((512, 3), np.uint8)
        for i in range(512):
            v, b = p[i], p[i | 0x200]
            out[i] = [combine(w[0], v & 1, v >> 1 & 1, v >> 2 & 1, v >> 3 & 1),
                      combine(w[1], v >> 4 & 1, v >> 5 & 1, v >> 6 & 1, v >> 7 & 1),
                      combine(w[2], b & 1, b >> 1 & 1, b >> 2 & 1, b >> 3 & 1)]
        return out

    def pen_table(self):
        """the 4096 pens -> indirect colour: tiles 0-2047 = the tile table, sprites 2048-4095 = 256 + the sprite table"""
        p = np.frombuffer(self.prom, np.uint8)
        return np.concatenate([p[0x400:0xC00].astype(np.int32), 256 + p[0xC00:0x1400].astype(np.int32)])

    def gfx(self):
        if self._gfx is None:
            def planar(rom):
                """init_namco86 shuffles the two plane ROM's nibbles into two planes and inverts the third (mono)
                plane; then gfx_8x8x3_planar (planes at 2/3, 1/3, 0 of the region)"""
                size = len(rom) * 2 // 3
                b = np.frombuffer(rom[:size], np.uint8)
                d1, d2 = b[0::2], b[1::2]
                out = np.zeros(len(rom), np.uint8)
                out[:size // 2] = (d1 << 4) | (d2 & 0xF)
                out[size // 2:size] = (d1 & 0xF0) | (d2 >> 4)
                out[size:] = np.frombuffer(rom[size:], np.uint8) ^ 0xFF
                n = len(rom) // 3
                return decode_gfx(out.tobytes(), 8, 8, n * 8 // 64, [2 * n * 8, n * 8, 0], list(range(8)),
                                  [8 * y for y in range(8)], 64)
            t0 = planar(self.r["tiles_0"])
            t1 = planar(self.r["tiles_1"])
            s = np.frombuffer(self.r["sprites"], np.uint8).reshape(-1, 2, 2, 16, 8)
            px = np.stack([s >> 4, s & 15], axis=-1).reshape(-1, 2, 2, 16, 16)
            spr = px.transpose(0, 1, 3, 2, 4).reshape(-1, 32, 32)
            self._gfx = (t0, t1, spr)
        return self._gfx

    def tilemap(self, dev, layer):
        """(pens, opaque) of one tilemap, 256 x 512: tile index = 64 * row + column"""
        t0, t1, _ = self.gfx()
        v = np.frombuffer(bytes(self.vram[dev]), np.uint8).reshape(2, 2048, 2)[layer]
        attr = v[:, 1].astype(np.int32)
        code = v[:, 0].astype(np.int32) + ((attr & 3) << 8)
        pr = self.prom[0x1400:0x1420]
        sel = np.array([pr[((layer & 1) << 4) + (c << 2)] for c in range(4)] if dev == 0 else
                       [pr[((layer & 1) << 4) + c] for c in range(4)], np.int32)
        hi = code >> 8
        if dev == 0:
            code = (code & 0xFF) | (((sel[hi] & 0x0E) >> 1) << 8) | (self.tilebank << 11)
            gfx = t0
        else:
            code = (code & 0xFF) | (((sel[hi] & 0xE0) >> 5) << 8)
            gfx = t1
        code %= len(gfx)
        px = gfx[code]                                         # [2048, 8, 8]
        lut = self.pen_table()
        pens = lut[(attr[:, None, None] * 8 + px.astype(np.int32)) & 0x7FF]
        pens = pens.reshape(32, 64, 8, 8).transpose(0, 2, 1, 3).reshape(256, 512)
        opaque = (px != 7).reshape(32, 64, 8, 8).transpose(0, 2, 1, 3).reshape(256, 512)
        return pens, opaque

    def render_raw(self):
        """the picture as indirect colours (288 x 224, MAME's visible area)"""
        bw, bh = 384, 264
        lut = self.pen_table()
        out = np.full((bh, bw), lut[8 * self.backcolor + 7], np.int32)
        pri = np.zeros((bh, bw), np.int32)
        ys, xs = np.mgrid[0:bh, 0:bw]
        xextent, yextent = VIS_X1 + VIS_X0 + 1, VIS_Y1 + VIS_Y0 + 1
        flip = self.flip
        for layer_pri in range(8):
            for i in (3, 2, 1, 0):
                dev, lay = i >> 1, i & 1
                if ((self.xscroll[dev][lay] & 0x0E00) >> 9) != layer_pri:
                    continue
                pens, opaque = self.tilemap(dev, lay)
                dx = (47 if dev == 0 else 46) + (0, 2)[lay]
                dxf = 422 - dx
                sx, sy = self.xscroll[dev][lay], self.yscroll[dev][lay]
                if flip:
                    pens, opaque = pens[::-1, ::-1], opaque[::-1, ::-1]
                    sx, sy = -sx, -sy
                h, w = pens.shape
                # effective scroll: value = dx - scroll (flipped: screen_width - width - (dx_flipped - scroll)), mod size
                vx = (dx - sx) if not flip else (xextent - w - (dxf - sx))
                vy = (-9 - sy) if not flip else (yextent - h - (9 - sy))
                px = (xs - vx) % w
                py = (ys - vy) % h
                o = opaque[py, px]
                out[o] = pens[py, px][o]
                pri[o] = layer_pri
        self.draw_sprites(out, pri)
        return out[VIS_Y0:VIS_Y1 + 1, VIS_X0:VIS_X1 + 1]

    def draw_sprites(self, out, pri):
        _, _, spr = self.gfx()
        sr = self.spriteram
        lut = self.pen_table()
        size = (16, 8, 32, 4)
        xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
        yoffs = sr[0x7F7]
        pri = pri.copy()
        bank_sprites = len(spr) // 8
        for off in range(0x7E0, -1, -0x10):
            attr1, attr2, color = sr[off + 10], sr[off + 14], sr[off + 12]
            flipx, flipy = bool(attr1 & 0x20), bool(attr2 & 1)
            sizex, sizey = size[attr1 >> 6], size[(attr2 & 6) >> 1]
            tx = (attr1 & 0x18) & ~(sizex - 1)
            ty = (attr2 & 0x18) & ~(sizey - 1)
            sx = sr[off + 13] + ((color & 1) << 8)
            sy = -sr[off + 15] - sizey
            code = (sr[off + 11] & (bank_sprites - 1)) + (attr1 & 7) * bank_sprites
            pmask = ((0xFF << (((attr2 & 0xE0) >> 5) + 1)) & 0xFF) | (1 << 31)
            color >>= 1
            sx += xoffs
            sy -= yoffs
            if self.flip:
                sx, sy = -sx - sizex, -sy - sizey
                flipx, flipy = not flipx, not flipy
            sy += 1
            x, y = sx & 0x1FF, ((sy + 16) & 0xFF) - 16
            img = spr[code, ty:ty + sizey, tx:tx + sizex]
            if flipx:
                img = img[:, ::-1]
            if flipy:
                img = img[::-1, :]
            bh, bw = out.shape
            yy0, xx0 = max(y, 0), max(x, 0)
            yy1, xx1 = min(y + sizey, bh), min(x + sizex, bw)
            if yy0 >= yy1 or xx0 >= xx1:
                continue
            sub = img[yy0 - y:yy1 - y, xx0 - x:xx1 - x]
            region = (slice(yy0, yy1), slice(xx0, xx1))
            opq = sub != 15
            p = pri[region]
            vis = opq & (((np.int64(1) << (p & 0x1F)) & pmask) == 0)
            o = out[region]
            o[vis] = lut[2048 + color * 16 + sub[vis].astype(np.int32)]
            p[opq] = 31

    def render_rgb(self, int_weights=False):
        raw = self.render_raw()
        return self.palette(int_weights)[raw]


class RthunderPort(Rthunder):
    """The port's schedule (translated code on the STE cannot interleave the two 6809 at MAME's grain).  A frame:

      1. the vertical blank: the sprite list latched, the MCU run for the frame on the board's scheduler (cpu1 and cpu2
         held), as MAME runs it (`run_others`);
      2. both 6809 take their IRQ at their idle point (the main loop's BRA, $81BC / $80A6, with its queues empty), then run
         cooperatively, cpu1 first: a CPU runs until it is idle again, until it *writes a semaphore byte* (shared RAM
         $5606 / $5607 = cpu2's $1606 / $1607) or until a spin wait would go round again (`SPIN`: the backward branch
         of a loop that reads and waits); then the other CPU runs, and so on.

    The two programs run in lock step through those bytes (cpu1: clear $5606, work, set it to 1, spin until $5607 = 1;
    cpu2: spin until $1606 = 0, clear $1607, spin until $1606 = 1, work, set $1607 to 1; the many variants of it).  On the
    board the spins last a few cycles; the yield at every write of the bytes and at every spin keeps the order in which
    the two CPUs see each other's writes that the hardware's timing gives them, and is the same in the translation.

    STATE (2026-11-07): NOT sufficient.  In attract mode it runs 1972 (ORDER (0, 1)) or 2168 (ORDER (1, 0)) frames from
    the start (frame 200) and then deadlocks: the programs also assume the *timing* of the board, which a cooperative
    schedule does not give them.  Examples: cpu1's sub-step completion (`STA <$04; STA <$05`, $92A0) advances cpu2's
    counter on the assumption that cpu2 dispatched its own step ~7000 cycles earlier; cpu2 samples cpu1's flag $18 at
    ~100 cycles into its IRQ, long before cpu1 changes it.  Whichever CPU runs first breaks one of the two kinds.
    """
    START = 200
    IDLE = {0: 0x81BC, 1: 0x80A6}              # the main loops' BRA (the translation's hooks replace them)
    SPIN = ({0x903A, 0x918A, 0xAA6F}, {0x858F, 0x8597})            # backward branches of spin waits; more are learned (`learned`)
    SEMO = {0x1606, 0x1607}                                  # the shared RAM offsets (cpu2's address) of the semaphore bytes
    ORDER = (1, 0)                                         # cpu2's IRQ handler reaches its dispatch long before cpu1's: it runs first
    LEARN = True                                           # (ref/cover.py: learn more spin waits and semaphore bytes)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.port_frames = 0
        self.state = ["idle", "idle"]
        self.instructions = [0, 0]
        self.yield_req = False
        self.writes = 0
        self.last = ({}, {})
        self.learned = set()
        self.SEMO = set(self.SEMO)
        self.learned_sem = set()
        self.readlog = ([], [])
        self.SPIN = tuple(set(x) for x in (self.SPIN[0], self.SPIN[1]))   # (instance copy: learns)

    # the IRQ acknowledges are no-ops in the port: the line is only high while the CPU takes the interrupt
    def wr1(self, a, v):
        if a == 0x8400:
            return
        self.writes += 1
        super().wr1(a, v)
        if 0x4400 <= a < 0x5800 and a - 0x4000 in self.SEMO:
            self.yield_req = True

    def wr2(self, a, v):
        if a == 0x8800:
            return
        self.writes += 1
        super().wr2(a, v)
        if a < 0x1800 and a in self.SEMO:
            self.yield_req = True

    def rd1(self, a):
        if self.LEARN and 0x4400 <= a < 0x5800:
            self.readlog[0].append(a - 0x4000)
        return super().rd1(a)

    def rd2(self, a):
        if self.LEARN and a < 0x1800:
            self.readlog[1].append(a)
        return super().rd2(a)

    def virt(self, i, pc):
        """the virtual address (engine/m6809x.py pages, ref/cover.py): the banked window's page is 8 + bank"""
        if pc >> 13 == 3:
            return ((8 + (self.bank1 if i == 0 else self.bank2)) << 13) | (pc & 0x1FFF)
        return pc

    def idle(self, i):
        c = self.cpus[i]
        s = self.shared
        if i == 0:
            return c.pc == 0x81BC and s[0x16B4] == s[0x16B3] and s[0x166F] == s[0x166E]
        return c.pc == 0x80A6 and s[0x1668] == s[0x1667]

    def boot(self, frames=None):
        """MAME's schedule up to the port's start, then both CPUs to their idle points"""
        frames = self.START if frames is None else frames
        while self.frame < frames:
            self.run_frame()
        for i in (0, 1):
            self.queues.pop((i, "irq"), None)
            self.cpus[i].set_irq(False)
        self.state = ["run", "run"]
        self.cooperate()

    def run_others(self):
        held = self.suspended[0], self.suspended[1]
        self.suspended[0] = self.suspended[1] = True
        self.run_frame()
        self.suspended[0], self.suspended[1] = held
        for i in (0, 1):
            self.queues.pop((i, "irq"), None)
            self.cpus[i].set_irq(False)

    def run_cpu(self, i, limit=3000000):
        """-> 'idle' (at the idle point), 'yield' (wrote a semaphore byte), 'blocked' (a spin wait goes round again)"""
        c = self.cpus[i]
        spin = self.SPIN[i]
        last = self.last[i]
        self.yield_req = False
        n = 0
        while n < limit:
            if self.idle(i):
                self.instructions[i] += n
                return "idle"
            pc = c.pc
            c.step()
            n += 1
            if self.yield_req:
                self.yield_req = False
                self.instructions[i] += n
                return "yield"
            if c.pc < pc:                                  # a backward jump: a spin wait?
                pc = self.virt(i, pc)
                if pc in spin:
                    self.instructions[i] += n
                    return "blocked"
                st = (c.a, c.b, c.x, c.y, c.u, c.s, c.dp, c.cc, self.writes)
                if last.get(pc) == st and self.LEARN:    # the same registers, nothing written since its last pass
                    spin.add(pc)
                    self.learned.add((i, pc))
                    new = set(self.readlog[i]) - self.SEMO     # what the loop reads: the other CPU's counters
                    self.SEMO |= new
                    self.learned_sem |= new
                    self.instructions[i] += n
                    return "blocked"
                last[pc] = st
                self.readlog[i].clear()
        raise RuntimeError("cpu %d runs on (pc %04X) after %d instructions" % (i + 1, c.pc, limit))

    def cooperate(self):
        stuck = 0
        while "run" in self.state:
            before = (self.writes, tuple(c.pc for c in self.cpus))
            for i in self.ORDER:
                if self.state[i] != "run":
                    continue
                r = self.run_cpu(i)
                if r == "idle":
                    self.state[i] = "idle"
            if before == (self.writes, tuple(c.pc for c in self.cpus)):
                stuck += 1
                if stuck > 2:
                    raise RuntimeError("deadlock: cpu1 pc %04X cpu2 pc %04X" % (self.cpu1.pc, self.cpu2.pc))
            else:
                stuck = 0

    def run_frame_port(self):
        self.run_others()
        for i in (0, 1):
            c = self.cpus[i]
            assert self.idle(i), "cpu %d not idle (pc %04X)" % (i + 1, c.pc)
            c.set_irq(True)
            c.step()                                      # the interrupt entry
            c.set_irq(False)
            self.state[i] = "run"
        self.cooperate()
        self.port_frames += 1
