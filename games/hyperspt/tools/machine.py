"""Hyper Sports (MAME `hyperspt`, Konami GX330, 1984): the reference board, from MAME konami/hyperspt.cpp.

Main CPU: KONAMI-1 (MC6809E, opcodes encrypted, engine/m6809.py with konami1_opcode) at 18.432 MHz / 12 = 1.536 MHz.
Screen (MAME): 60 Hz, 256 lines (no raw timing given), 256 x 224 visible (lines 16-239): 25600 CPU cycles a frame,
100 a line.  The VBLANK (line 240) asserts IRQ while the INT latch bit is 1; writing that bit 0 clears it.
NVRAM $3800-$3FFF (MAME: all 0 at the first start).  No NMI, no FIRQ.

Memory map (main CPU, no mirrors):
    $1000-$10BF  sprite RAM (48 x attr, y, code, x)   $10C0-$10FF scroll (a row: x low, x bit 8)
    $1400 w watchdog       $1480-$1487 w LS259 latch: bit 0 of the data; Q0 flip screen, Q1 sound IRQ trigger
                           (0->1), Q3/Q4 coin counters, Q7 IRQ enable
    $1500 w sound latch    $1600 r DSW2   $1680 r SYSTEM   $1681 r P1_P2   $1682 r P3_P4   $1683 r DSW1
    $2000-$27FF video RAM  $2800-$2FFF colour RAM  $3000-$37FF RAM  $3800-$3FFF NVRAM  $4000-$FFFF ROM
    anything else reads 0 (MAME's unmapped value)
Sound: a Z80 (14.318 MHz / 4) with an SN76489A, a VLM5030 and a DAC; the main CPU only writes the latch and the
trigger, so it is not emulated: sound_log keeps (frame, latch value) at each trigger.

Video: a 64 x 32 tilemap of 8x8 4bpp tiles (1024), x scrolled per tile row; 48 sprites 16x16 4bpp (512), drawn
from the last to the first (the first on top), each also at x - 256.  Colours as Track & Field: a 32-entry palette
PROM, two 256x4 lookup PROMs (sprites -> 0-15, tiles -> 16-31); a sprite pixel whose lookup entry is 0 is transparent.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809, konami1_opcode
import mamegfx as G

CPU_HZ = 1536000
LINES = 256
FRAME = CPU_HZ // 60                       # 25600
LINE = FRAME // LINES                      # 100
VBLANK_LINE = 240
VISIBLE = (0, 255, 16, 239)

# MAME's defaults: DSW1 1 coin 1 credit both slots; DSW2 game over after the last event ($01), upright, demo sounds
# on, keep the records ($08), difficulty "Normal 8" ($40)
DSW1, DSW2 = 0xFF, 0x49


def load(name):
    return (EXTRACTED / "hyperspt" / name).read_bytes()


def konami_pens(prom):
    """The 512 pens' RGB (MAME base_state::palette): PROM bits 0-2 red, 3-5 green (1k, 470, 220 ohm, 1k pulldown),
    6-7 blue (470, 220); lookup PROMs at $20 (sprites -> 0-15) and $120 (tiles -> 16-31)."""
    rw, gw, bw = G.resistor_weights(0, 255, -1.0, ([1000, 470, 220], 1000, 0), ([1000, 470, 220], 1000, 0),
                                    ([470, 220], 1000, 0))
    pal = []
    for i in range(32):
        bit = [(prom[i] >> k) & 1 for k in range(8)]
        pal.append((G.combine(rw, *bit[0:3]), G.combine(gw, *bit[3:6]), G.combine(bw, *bit[6:8])))
    pal = np.array(pal, np.uint8)
    idx = [prom[0x20 + i] & 15 for i in range(256)] + [(prom[0x120 + i] & 15) | 16 for i in range(256)]
    return pal[idx]


class Video:
    def __init__(self):
        prom = load("c03_c27.bin") + load("j12_c28.bin") + load("a09_c29.bin")
        spr = b"".join(load(n) for n in ("c14", "c13", "c12", "c11", "c18", "c17", "c16", "c15"))
        til = b"".join(load(n) for n in ("c26", "c24", "c22", "c20"))
        sx = [0, 1, 2, 3, 64, 65, 66, 67, 128, 129, 130, 131, 192, 193, 194, 195]
        sy = [0, 8, 16, 24, 32, 40, 48, 56, 256, 264, 272, 280, 288, 296, 304, 312]
        self.sprites = G.decode_gfx(spr, 16, 16, 512, [0x8000 * 8 + 4, 0x8000 * 8, 4, 0], sx, sy, 512)
        self.tiles = G.decode_gfx(til, 8, 8, 1024, [0x4000 * 8 + 4, 0x4000 * 8, 4, 0], [0, 1, 2, 3, 64, 65, 66, 67],
                                  list(range(0, 64, 8)), 128)
        self.pens = konami_pens(prom)
        self.lut = np.array([prom[0x20 + i] & 15 for i in range(256)], np.uint8)

    def render_raw(self, mem, flip=False):
        """The screen's pens [256 rows, 256] (rows 16-239 visible) from the main CPU's memory (64 KB image)."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        vram = np.frombuffer(bytes(mem[0x2000:0x2800]), np.uint8).reshape(32, 64).astype(np.int32)
        cram = np.frombuffer(bytes(mem[0x2800:0x3000]), np.uint8).reshape(32, 64)
        codes = vram + ((cram & 0x80).astype(np.int32) << 1) + ((cram & 0x40).astype(np.int32) << 3)
        pix, _ = G.tile_pixmap(self.tiles, codes, cram & 15, cram & 0x10, cram & 0x20, 32, 64, 256, 16)
        scroll = [mem[0x10C0 + 2 * r] + 256 * (mem[0x10C1 + 2 * r] & 1) for r in range(32)]
        bm = G.scroll_rows(pix, scroll, 256)[:, :256].astype(np.int16)
        sr = mem[0x1000:0x10C0]
        lut = self.lut
        for offs in range(0xBC, -1, -4):
            attr = sr[offs]
            code = sr[offs + 2] + 8 * (attr & 0x20)
            color = attr & 15
            x, y = sr[offs + 3], 240 - sr[offs + 1] + 1
            trans = lut[color * 16:color * 16 + 16] == 0
            for dx in (x, x - 256):
                G.draw_gfx(bm, VISIBLE, self.sprites, code, color * 16, not attr & 0x40, attr & 0x80, dx, y,
                           lambda s: trans[s])
        return bm

    def render_rgb(self, mem, flip=False):
        """The visible picture [224, 256, 3] as MAME's snapshot shows it."""
        return self.pens[self.render_raw(mem, flip)[VISIBLE[2]:VISIBLE[3] + 1]]


class HyperSports:
    def __init__(self, dsw1=DSW1, dsw2=DSW2):
        rom = bytearray(0x10000)
        for i, n in enumerate(("c01", "c02", "c03", "c04", "c05", "c06")):
            rom[0x4000 + i * 0x2000:0x6000 + i * 0x2000] = load(n)
        self.rom = bytes(rom)
        self.mem = bytearray(0x10000)
        self.mem[0x4000:] = self.rom[0x4000:]
        self.system = self.p1_p2 = self.p3_p4 = 0xFF
        self.dsw1, self.dsw2 = dsw1, dsw2
        self.latch = [0] * 8
        self.sound_latch = 0
        self.sound_log = []
        self.watchdog = 0
        self.frame = 0
        self.cpu = M6809(self.rd, self.wr, konami1_opcode(self.rd))
        self.video = None
        self.cpu.reset()
        self.next_vblank = VBLANK_LINE * LINE

    def rd(self, a):
        if a >= 0x2000 or 0x1000 <= a < 0x1100:
            return self.mem[a]
        if a == 0x1600:
            return self.dsw2
        if 0x1680 <= a <= 0x1683:
            return (self.system, self.p1_p2, self.p3_p4, self.dsw1)[a & 3]
        return 0

    def wr(self, a, v):
        if 0x1000 <= a < 0x1100 or 0x2000 <= a < 0x4000:
            self.mem[a] = v
        elif a == 0x1400:
            self.watchdog += 1
        elif 0x1480 <= a <= 0x1487:
            q, b = a & 7, v & 1
            old = self.latch[q]
            self.latch[q] = b
            if q == 1 and b and not old:
                self.sound_log.append((self.frame, self.sound_latch))
            elif q == 7 and not b:
                self.cpu.set_irq(False)
        elif a == 0x1500:
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
    m = HyperSports()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, sound commands %d" % (time.time() - t, m.cpu.pc, len(m.sound_log)))
