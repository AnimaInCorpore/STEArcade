"""Gyruss (MAME `gyruss`, Konami GX347, 1983): the reference board, from MAME konami/gyruss.cpp.

CPUs: main Z80 at 18.432 MHz / 6 = 3.072 MHz (engine/z80.py), sub KONAMI-1 at 1.536 MHz (engine/m6809.py with
konami1_opcode), sound Z80 at 3.58 MHz with five AY-3-8910 and an i8039 (DAC) - the main CPU only writes the sound
latch and triggers the sound CPU's IRQ, so the sound side is not emulated: sound_log keeps (frame, latch value).
Screen: 6.144 MHz pixel clock, 396 x 256 total, 256 x 224 visible (lines 16-239), 60.606 Hz, ROT90 (MAME's snapshot
is 224 wide, 256 high): a frame is 50688 main / 25344 sub cycles, a line 198 / 99.  MAME interleaves the CPUs at
least every 1/6000 s; here they take turns every line.
At VBLANK (line 240): the main CPU's NMI is asserted while its mask (latch Q0) is 1 - the line stays asserted until
the mask is written 0, so the Z80 sees one edge a frame when the game re-arms it; the sub CPU's IRQ is asserted
while its mask ($2000 bit 0) is 1, cleared by writing 0.

Main CPU map: $0000-$5FFF ROM ($6000-$7FFF the empty diagnostics socket: 0), $8000-$83FF colour RAM, $8400-$87FF
    video RAM, $9000-$9FFF RAM, $A000-$A7FF RAM shared with the sub CPU ($6000-$67FF there); reads $C000 DSW2,
    $C080 SYSTEM, $C0A0 P1, $C0C0 P2, $C0E0 DSW1, $C100 DSW3; writes $C000 watchdog, $C080 sound IRQ trigger,
    $C100 sound latch, $C180-$C187 LS259 (bit 0: Q0 NMI mask, Q2/Q3 coin counters, Q5 flip screen).
Sub CPU map: $0000 r the beam's line (vpos), $2000 w IRQ mask, $4000-$47FF RAM ($4040-$40FF the 48 sprites: x,
    code/bank, attributes, y), $6000-$67FF shared RAM, $E000-$FFFF ROM.  Anything else reads 0.

Video: a 32 x 32 tilemap of 8x8 2bpp tiles (512), no scroll; sprites 8x16 4bpp (2 x 256: the two halves of each
64-byte cell), drawn from the last to the first (the first on top), pen 0 transparent.  Order: all tiles, the
sprites, then the tiles whose colour byte has bit 4 again (over the sprites).  MAME redraws the screen up to the
current line before every sprite RAM write (the sub CPU writes sprites until about line 36): render_raw takes the
sprite RAM per band of lines.  Colours: a 32-entry palette PROM (3-3-2, 470 ohm pulldowns), sprite pens 0-255 ->
palette 0-15 and tile pens 256-319 -> 16-31 through the lookup PROMs.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809, konami1_opcode
from z80 import Z80
import mamegfx as G

MAIN_LINE, SUB_LINE = 198, 99              # cycles a line (396 pixels / 2, / 4)
LINES = 256
VBLANK_LINE = 240
VISIBLE = (0, 255, 16, 239)

# MAME's defaults: DSW1 1 coin 1 credit both slots; DSW2 3 lives ($03), upright, bonus 30k 90k 60k+ ($08),
# difficulty 5 ($30), demo sounds on; DSW3 demo music on ($00), unused bits 1
DSW1, DSW2, DSW3 = 0xFF, 0x3B, 0xFE


def load(name):
    return (EXTRACTED / "gyruss" / name).read_bytes()


def gyruss_pens(prom):
    """The 320 pens' RGB (MAME gyruss_state::palette): PROM bits 0-2 red, 3-5 green (1k, 470, 220 ohm), 6-7 blue (470,
    220), 470 ohm pulldowns; sprite pens 0-255 -> lookup $20 (0-15), tile pens 256-319 -> lookup $120 (16-31)."""
    rg, b = G.resistor_weights(0, 255, -1.0, ([1000, 470, 220], 470, 0), ([470, 220], 470, 0))
    pal = []
    for i in range(32):
        bit = [(prom[i] >> k) & 1 for k in range(8)]
        pal.append((G.combine(rg, *bit[0:3]), G.combine(rg, *bit[3:6]), G.combine(b, *bit[6:8])))
    pal = np.array(pal, np.uint8)
    idx = [prom[0x20 + i] & 15 for i in range(256)] + [(prom[0x120 + i] & 15) | 16 for i in range(64)]
    return pal[idx]


def sprite_bands(s0, writes):
    """MAME's partial updates: [(first line, last line, sprite RAM)] for the visible lines, from the sprite RAM at the
    previous VBLANK (s0, 0xC0 bytes from $4040) and the writes since [(line, offset from $4040, value)] in time order
    (line: the beam position; >= 240 is still the previous VBLANK).  A write at line v comes after the lines up to v
    were drawn."""
    ram = bytearray(s0)
    bands = []
    top = VISIBLE[2]
    for line, off, v in writes:
        e = int(line) if line < VBLANK_LINE else -1
        if e >= top:
            bands.append((top, min(e, VISIBLE[3]), bytes(ram)))
            top = e + 1
        if top > VISIBLE[3]:
            break
        ram[off] = v
    if top <= VISIBLE[3]:
        bands.append((top, VISIBLE[3], bytes(ram)))
    return bands


class Video:
    def __init__(self):
        prom = load("gyrussk.pr3") + load("gyrussk.pr1") + load("gyrussk.pr2")
        spr = b"".join(load(n) for n in ("gyrussk.6", "gyrussk.5", "gyrussk.8", "gyrussk.7"))
        sx = [0, 1, 2, 3, 64, 65, 66, 67]
        sy = [0, 8, 16, 24, 32, 40, 48, 56, 256, 264, 272, 280, 288, 296, 304, 312]
        planes = [0x4000 * 8 + 4, 0x4000 * 8, 4, 0]
        self.sprites = [G.decode_gfx(spr, 8, 16, 256, planes, sx, sy, 512, start=s) for s in (0, 0x10)]
        self.tiles = G.decode_gfx(load("gyrussk.4"), 8, 8, 512, [4, 0], sx, list(range(0, 64, 8)), 128)
        self.pens = gyruss_pens(prom)

    def render_raw(self, mem, bands, flip=False):
        """The screen's pens [256 rows, 256] (rows 16-239 visible; unrotated) from the main CPU's memory (tiles) and
        the sprite RAM bands (sprite_bands; or one 0xC0-byte block for all lines)."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        if isinstance(bands, (bytes, bytearray)):
            bands = [(VISIBLE[2], VISIBLE[3], bytes(bands))]
        cram = np.frombuffer(bytes(mem[0x8000:0x8400]), np.uint8).reshape(32, 32)
        vram = np.frombuffer(bytes(mem[0x8400:0x8800]), np.uint8).reshape(32, 32).astype(np.int32)
        codes = ((cram & 0x20).astype(np.int32) << 3) | vram
        bm, _ = G.tile_pixmap(self.tiles, codes, cram & 15, cram & 0x40, cram & 0x80, 32, 32, 256, 4)
        bm = bm.astype(np.int16)
        front = np.repeat(np.repeat((cram & 0x10) != 0, 8, 0), 8, 1)
        tiles = bm.copy()
        for y0, y1, sr in bands:
            clip = (VISIBLE[0], VISIBLE[1], y0, y1)
            for offs in range(0xBC, -1, -4):
                a = sr[offs + 2]
                G.draw_gfx(bm, clip, self.sprites[sr[offs + 1] & 1], ((a & 0x20) << 2) | (sr[offs + 1] >> 1),
                           (a & 15) * 16, not a & 0x40, a & 0x80, sr[offs], 241 - sr[offs + 3], lambda s: s == 0)
        bm[front] = tiles[front]
        return bm

    def render_rgb(self, mem, bands, flip=False, rotate=True):
        """The visible picture as MAME's snapshot shows it: [256, 224, 3] rotated (ROT90), else [224, 256, 3]."""
        rgb = self.pens[self.render_raw(mem, bands, flip)[VISIBLE[2]:VISIBLE[3] + 1]]
        return np.ascontiguousarray(np.rot90(rgb, -1)) if rotate else rgb


class Gyruss:
    def __init__(self, dsw1=DSW1, dsw2=DSW2, dsw3=DSW3):
        self.rom = bytearray(0x10000)
        for i, n in enumerate(("gyrussk.1", "gyrussk.2", "gyrussk.3")):
            self.rom[i * 0x2000:(i + 1) * 0x2000] = load(n)
        self.sub_rom = bytearray(0x10000)
        self.sub_rom[0xE000:] = load("gyrussk.9")
        self.mem = bytearray(0x10000)              # main CPU view (its RAM; $A000-$A7FF is the shared RAM)
        self.mem[:0x8000] = self.rom[:0x8000]
        self.sub_mem = bytearray(0x10000)          # sub CPU view ($6000-$67FF unused: shared RAM is self.mem)
        self.sub_mem[0xE000:] = self.sub_rom[0xE000:]
        self.system = self.p1 = self.p2 = 0xFF
        self.dsw1, self.dsw2, self.dsw3 = dsw1, dsw2, dsw3
        self.latch = [0] * 8
        self.nmi_line = False
        self.sub_irq_mask = 0
        self.sound_latch = 0
        self.sound_log = []
        self.frame = 0
        self.line = 0                              # the beam's line (vpos) during the current line's slice
        self.sprite_s0 = bytes(0xC0)               # sprite RAM at the last VBLANK, and the writes since
        self.sprite_writes = []
        self.main = Z80(self.rd, self.wr)
        self.sub = M6809(self.srd, self.swr, konami1_opcode(self.srd))
        self.sub.reset()
        self.video = None

    # ---- main CPU ----
    def rd(self, a):
        if a < 0x8800 or 0x9000 <= a < 0xA800:
            return self.mem[a]
        if 0xC000 <= a < 0xC200:
            if a == 0xC000: return self.dsw2
            if a == 0xC080: return self.system
            if a == 0xC0A0: return self.p1
            if a == 0xC0C0: return self.p2
            if a == 0xC0E0: return self.dsw1
            if a == 0xC100: return self.dsw3
        return 0

    def wr(self, a, v):
        if 0x8000 <= a < 0x8800 or 0x9000 <= a < 0xA800:
            self.mem[a] = v
        elif 0xC180 <= a <= 0xC187:
            q, b = a & 7, v & 1
            self.latch[q] = b
            if q == 0 and not b:
                self.nmi_line = False
        elif a == 0xC080:
            self.sound_log.append((self.frame, self.sound_latch))
        elif a == 0xC100:
            self.sound_latch = v

    # ---- sub CPU ----
    def srd(self, a):
        if a >= 0xE000 or 0x4000 <= a < 0x4800:
            return self.sub_mem[a]
        if 0x6000 <= a < 0x6800:
            return self.mem[a + 0x4000]
        if a == 0:
            return self.line & 0xFF
        return 0

    def swr(self, a, v):
        if 0x4000 <= a < 0x4800:
            if 0x4040 <= a < 0x4100:
                self.sprite_writes.append((self.line + self.sub_frac(), a - 0x4040, v))
            self.sub_mem[a] = v
        elif 0x6000 <= a < 0x6800:
            self.mem[a + 0x4000] = v
        elif a == 0x2000:
            self.sub_irq_mask = v & 1
            if not self.sub_irq_mask:
                self.sub.set_irq(False)

    def sub_frac(self):
        return min(max(0.0, 1.0 - (self.sub.end - self.sub.cycles) / SUB_LINE), 0.999)

    # ---- schedule ----
    def run_line(self):
        m = self.main
        target = m.cycles + MAIN_LINE - getattr(self, "_main_over", 0)
        while m.cycles < target:
            m.step()
        self._main_over = m.cycles - target
        self.sub.run(SUB_LINE - getattr(self, "_sub_over", 0))
        self._sub_over = self.sub.cycles - self.sub.end if self.sub.cycles > self.sub.end else 0

    def vblank(self):
        if self.latch[0] and not self.nmi_line:
            self.nmi_line = True
            m = self.main
            if m.halted:
                m.pc = (m.pc + 1) & 0xFFFF         # (MAME pushes the address after the HALT)
            m.nmi()
        if self.sub_irq_mask:
            self.sub.set_irq(True)

    def run_frame(self):
        """Runs to the next VBLANK (line 240) and starts it: the state MAME's frame_done callback sees.  The sprite RAM
        at the previous VBLANK and the writes since are kept for render_rgb (bands_s0, bands_writes)."""
        self.sprite_s0 = bytes(self.sub_mem[0x4040:0x4100])
        self.sprite_writes = []
        while True:
            self.run_line()
            self.line = (self.line + 1) % LINES
            if self.line == VBLANK_LINE:
                break
        self.vblank()
        self.frame += 1
        self.bands_s0, self.bands_writes = self.sprite_s0, self.sprite_writes

    def render_rgb(self, rotate=True):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, sprite_bands(self.bands_s0, self.bands_writes), bool(self.latch[5]),
                                     rotate)


if __name__ == "__main__":
    import time
    g = Gyruss()
    t = time.time()
    for _ in range(300):
        g.run_frame()
    print("300 frames in %.1f s, main pc %04X sub pc %04X, sound commands %d" % (time.time() - t, g.main.pc, g.sub.pc,
                                                                               len(g.sound_log)))
