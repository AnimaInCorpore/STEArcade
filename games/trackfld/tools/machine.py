"""Track & Field (MAME `trackfld`, Konami GX361, 1983): the reference board, from MAME konami/trackfld.cpp.

Main CPU: KONAMI-1 (MC6809E, opcodes encrypted, engine/m6809.py with konami1_opcode) at 18.432 MHz / 12 = 1.536 MHz.
Screen: 6.144 MHz pixel clock, 384 x 264 total, 256 x 224 visible (lines 16-239), 60.606 Hz: 25344 CPU cycles a
frame, 96 a line.  The VBLANK (line 240) asserts IRQ while the INT latch bit is 1; writing that bit 0 clears it.
NVRAM $2800-$2FFF (MAME: all 0 at the first start).  No NMI, no FIRQ.

Memory map (main CPU):
    $1000        w  watchdog                       $1080-$1087 w  LS259 latch (mirror $78): bit 0 of the data
                                                      Q0 flip screen, Q1 sound IRQ trigger (0->1), Q3/Q4 coin
                                                      counters, Q7 IRQ enable
    $1100        w  sound latch (mirror $7F)       $1200 r DSW2 (mirror $7F)
    $1280-$1283  r  SYSTEM IN0 IN1 DSW1 (mirror $7C)
    $1800-$183F  sprite RAM 2 (attr, y)            $1840-$185F scroll (x low, a row each)
    $1C00-$1C3F  sprite RAM (x, code)              $1C40-$1C5F scroll 2 (bit 0: x bit 8)
    $1800-$1FFF  RAM (all of it), $2800-$2FFF NVRAM, $3000-$37FF video RAM, $3800-$3FFF colour RAM
    $6000-$FFFF  ROM; anything else reads 0 (MAME's unmapped value)
Sound: a Z80 (14.318 MHz / 4) with an SN76489A, a VLM5030 and an 8-bit DAC behind the latch; the main CPU only writes
(the latch and the trigger), so it is not emulated here: sound_log keeps (frame, latch value) at each trigger.

Video: a 64 x 32 tilemap of 8x8 4bpp tiles (768 of them), x scrolled per tile row; 32 sprites 16x16 4bpp (256),
drawn from the last entry to the first (the first on top), each also at x - 256.  Colours: a 32-entry palette PROM
(3-3-2 resistor network), 16 sprite and 16 tile colour sets of 16 pens through two 256x4 lookup PROMs (pens 0-255
sprites -> palette 0-15, pens 256-511 tiles -> palette 16-31).  A sprite pixel whose lookup entry is 0 is transparent.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809, konami1_opcode
import mamegfx as G

CPU_HZ = 1536000
LINE = 96                                  # CPU cycles a line (384 pixels / 4)
LINES = 264
FRAME = LINE * LINES                       # 25344
VBLANK_LINE = 240
VISIBLE = (0, 255, 16, 239)                # MAME's visible area (min_x, max_x, min_y, max_y)

# MAME's defaults: DSW1 1 coin 1 credit both slots; DSW2 1 life ($01), game continues, upright, no bonus ($08),
# keep the records ($10), normal ($40), demo sounds on
DSW1, DSW2 = 0xFF, 0x59


def load(name):
    return (EXTRACTED / "trackfld" / name).read_bytes()


class Video:
    def __init__(self):
        prom = load("361b16.f1") + load("361b17.b16") + load("361b18.e15")
        gfx1 = b"".join(load(n) for n in ("c11_d06.bin", "c12_d07.bin", "c13_d08.bin", "c14_d09.bin"))
        gfx2 = b"".join(load(n) for n in ("h16_e12.bin", "h15_e11.bin", "h14_e10.bin"))
        half = G.rgn_frac(len(gfx1), 1, 2)
        sx = [0, 1, 2, 3, 64, 65, 66, 67, 128, 129, 130, 131, 192, 193, 194, 195]
        sy = [0, 8, 16, 24, 32, 40, 48, 56, 256, 264, 272, 280, 288, 296, 304, 312]
        self.sprites = G.decode_gfx(gfx1, 16, 16, len(gfx1) * 8 // 2 // 512, [half + 4, half, 4, 0], sx, sy, 512)
        self.tiles = G.decode_gfx(gfx2, 8, 8, len(gfx2) // 32, [0, 1, 2, 3], list(range(0, 32, 4)),
                                  list(range(0, 256, 32)), 256)          # gfx_8x8x4_packed_msb
        self.pens = konami_pens(prom)
        self.lut = np.array([prom[0x20 + i] & 15 for i in range(256)] +
                            [(prom[0x120 + i] & 15) | 16 for i in range(256)], np.uint8)

    def render_raw(self, mem, flip=False):
        """The screen's pens [256 rows, 256] (rows 16-239 visible) from the main CPU's memory (64 KB image)."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        vram = np.frombuffer(bytes(mem[0x3000:0x3800]), np.uint8).reshape(32, 64)
        cram = np.frombuffer(bytes(mem[0x3800:0x4000]), np.uint8).reshape(32, 64)
        codes = vram.astype(np.int32) + 4 * (cram & 0xC0).astype(np.int32)
        pix, _ = G.tile_pixmap(self.tiles, codes, cram & 15, cram & 0x10, cram & 0x20, 32, 64, 256, 16)
        scroll = [mem[0x1840 + r] + 256 * (mem[0x1C40 + r] & 1) for r in range(32)]
        bm = G.scroll_rows(pix, scroll, 256)[:, :256].astype(np.int16)
        sr, sr2 = mem[0x1C00:0x1C40], mem[0x1800:0x1840]
        lut = self.lut
        for offs in range(0x3E, -1, -2):
            attr, code = sr2[offs], sr[offs + 1]
            color = attr & 15
            if attr & 1:
                code |= 0x100                  # (Yie Ar's extra bit: masked by the 256 sprites)
            x, y = sr[offs] - 1, 240 - sr2[offs + 1] + 1
            trans = lut[color * 16:color * 16 + 16] == 0
            for dx in (x, x - 256):
                G.draw_gfx(bm, VISIBLE, self.sprites, code, color * 16, not attr & 0x40, attr & 0x80, dx, y,
                           lambda s: trans[s])
        return bm

    def render_rgb(self, mem, flip=False):
        """The visible picture [224, 256, 3] as MAME's snapshot shows it."""
        raw = self.render_raw(mem, flip)[VISIBLE[2]:VISIBLE[3] + 1]
        return self.pens[raw]


def konami_pens(prom, rg_pulldown=1000):
    """The 512 pens' RGB: palette PROM bits 0-2 red, 3-5 green (1k, 470, 220 ohm), 6-7 blue (470, 220); lookup PROMs
    at $20 (sprites -> 0-15) and $120 (tiles -> 16-31)."""
    rw, gw, bw = G.resistor_weights(0, 255, -1.0, ([1000, 470, 220], rg_pulldown, 0), ([1000, 470, 220], rg_pulldown, 0),
                                    ([470, 220], rg_pulldown, 0))
    pal = []
    for i in range(32):
        v = prom[i]
        bit = [(v >> k) & 1 for k in range(8)]
        pal.append((G.combine(rw, *bit[0:3]), G.combine(gw, *bit[3:6]), G.combine(bw, *bit[6:8])))
    pal = np.array(pal, np.uint8)
    idx = [prom[0x20 + i] & 15 for i in range(256)] + [(prom[0x120 + i] & 15) | 16 for i in range(256)]
    return pal[idx]


class TrackField:
    def __init__(self, dsw1=DSW1, dsw2=DSW2):
        rom = bytearray(0x10000)
        for i, n in enumerate(("a01_e01.bin", "a02_e02.bin", "a03_k03.bin", "a04_e04.bin", "a05_e05.bin")):
            rom[0x6000 + i * 0x2000:0x8000 + i * 0x2000] = load(n)
        self.rom = bytes(rom)
        self.mem = bytearray(0x10000)              # RAM areas (and the ROM copy, for render/compare convenience)
        self.mem[0x6000:] = self.rom[0x6000:]
        self.system = self.in0 = self.in1 = 0xFF
        self.dsw1, self.dsw2 = dsw1, dsw2
        self.latch = [0] * 8
        self.sound_latch = 0
        self.sound_log = []
        self.watchdog = 0
        self.frame = 0
        self.cpu = M6809(self.rd, self.wr, konami1_opcode(self.rd))
        self.video = None
        self.cpu.reset()
        self.next_vblank = VBLANK_LINE * LINE      # the first VBLANK: line 240 of the first frame

    def rd(self, a):
        if a >= 0x6000 or 0x1800 <= a < 0x2000 or 0x2800 <= a < 0x4000:
            return self.mem[a]
        if 0x1200 <= a < 0x1300:
            if a < 0x1280:
                return self.dsw2
            return (self.system, self.in0, self.in1, self.dsw1)[a & 3]
        return 0

    def wr(self, a, v):
        if 0x1800 <= a < 0x2000 or 0x2800 <= a < 0x4000:
            self.mem[a] = v
        elif 0x1000 <= a < 0x1080:
            self.watchdog += 1
        elif 0x1080 <= a < 0x1100:
            q, b = a & 7, v & 1
            old = self.latch[q]
            self.latch[q] = b
            if q == 1 and b and not old:
                self.sound_log.append((self.frame, self.sound_latch))
            elif q == 7 and not b:
                self.cpu.set_irq(False)
        elif 0x1100 <= a < 0x1180:
            self.sound_latch = v

    def run_frame(self):
        """Runs to the next VBLANK and starts it (IRQ when enabled): the state MAME's frame_done callback sees."""
        c = self.cpu
        c.run(self.next_vblank - c.cycles)
        if self.latch[7]:
            c.set_irq(True)
        self.next_vblank += FRAME
        self.frame += 1

    def render_rgb(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, bool(self.latch[0]))


if __name__ == "__main__":
    import time
    m = TrackField()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, sound commands %d" % (time.time() - t, m.cpu.pc, len(m.sound_log)))
