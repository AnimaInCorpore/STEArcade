"""Mikie (MAME `mikie`, Konami GX469, 1984): the reference board, from MAME konami/mikie.cpp.

Main CPU: an MC6809E (plain opcodes, unlike Track & Field's KONAMI-1) at 18.432 MHz / 12 = 1.536 MHz.
Screen: 256 x 256 total at 60.59 Hz (set_size, vblank time 0), visible lines 16-239; the VBLANK (line 240) asserts IRQ
while the INT latch bit (Q7) is 1; writing it 0 clears the line.  No NMI, no FIRQ.

Memory map (main CPU):
    $0000-$00FF RAM            $2000-$2007 w  LS259 latch (bit 0 of the data): Q0/Q1 coin counters, Q2 sound IRQ
                                              trigger (0->1), Q6 flip screen, Q7 IRQ enable
    $2100 w watchdog           $2200 w palette bank (bits 0-2)   $2400 w sound latch, r SYSTEM
    $2401 r P1  $2402 r P2  $2403 r DSW3  $2500 r DSW1  $2501 r DSW2
    $2800-$288F sprite RAM (36 x 4: attr, y, code, x)   $2890-$37FF RAM   $3800-$3BFF colour RAM
    $3C00-$3FFF video RAM      $4000-$5FFF ROM socket (empty here: reads 0)    $6000-$FFFF ROM
Sound: a Z80 with two SN76489A behind the latch; the main CPU only writes it, so it is not emulated here: sound_log keeps
(frame, latch value) at each trigger.

Video: a 32 x 32 tilemap of 8x8 4bpp tiles (512), drawn in two categories (colour RAM bit 4: the front layer, over the
sprites); 36 sprites 16x16 4bpp (256 in each of two ROM halves), the later entry on top.  Colours: three 256 x 4 palette
PROMs (resistor network 2.2k/1k/470/220), lookup PROMs for the tiles and sprites; the palette bank (0-7) selects a
group of 16 colour sets.  Pixel value 0 of sprites is transparent (transpen 0); the tilemap's tiles are opaque.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809
import mamegfx as G

CPU_HZ = 1536000
REFRESH = 60.59
LINES = 256
VBLANK_LINE = 240
FRAME_F = CPU_HZ / REFRESH                 # 25351.05 CPU cycles a frame
VISIBLE = (0, 255, 16, 239)                # MAME's visible area (min_x, max_x, min_y, max_y)

# MAME's defaults: DSW1 1 coin 1 credit both slots ($FF); DSW2 3 lives ($03), upright, bonus 20k 70k 50k+ ($18), easy
# ($60), demo sounds on ($00); DSW3 flip off, single controls, the rest high ($FE)
DSW1, DSW2, DSW3 = 0xFF, 0x7B, 0xFE


def load(name):
    return (EXTRACTED / "mikie" / name).read_bytes()


def mikie_pens(prom):
    """The 4096 pens' RGB (MAME's palette entries): tiles 0-$7FF, sprites $800-$FFF, pen = bank * 256 + colour * 16 + pixel
    (colour set 0-15 of the bank); the lookup PROM entry (the tiles' at $300, the sprites' at $400) gives the low 4 bits
    of the palette index, the bank bits 5-7, tiles bit 4."""
    rw, gw, bw = G.resistor_weights(0, 255, -1.0, *[([2200, 1000, 470, 220], 470, 0)] * 3)
    pal = np.array([(G.combine(rw, *[(prom[i] >> k) & 1 for k in range(4)]),
                     G.combine(gw, *[(prom[0x100 + i] >> k) & 1 for k in range(4)]),
                     G.combine(bw, *[(prom[0x200 + i] >> k) & 1 for k in range(4)])) for i in range(256)], np.uint8)
    idx = []
    for p in range(0x1000):
        i, spr = p & 0x7FF, p >= 0x800
        idx.append(((i >> 8) << 5) | (0 if spr else 0x10) | (prom[0x300 + (0x100 if spr else 0) + (i & 0xFF)] & 15))
    return pal[idx]


class Video:
    def __init__(self):
        prom = b"".join(load(n) for n in ("d19.1i", "d21.3i", "d20.2i", "d22.12h", "d18.f9"))
        tiles = load("o11.8i")
        spr = b"".join(load(n) for n in ("001.f1", "003.f3", "005.h1", "007.h3"))
        sx = [32 * 8 + 0, 32 * 8 + 1, 32 * 8 + 2, 32 * 8 + 3, 16 * 8 + 0, 16 * 8 + 1, 16 * 8 + 2, 16 * 8 + 3,
              0, 1, 2, 3, 48 * 8 + 0, 48 * 8 + 1, 48 * 8 + 2, 48 * 8 + 3]
        sy = [0, 16, 32, 48, 64, 80, 96, 112, 32 * 16, 33 * 16, 34 * 16, 35 * 16, 36 * 16, 37 * 16, 38 * 16, 39 * 16]
        half = 256 * 128 * 8
        planes = [0, 4, half, half + 4]
        self.sprites = [G.decode_gfx(spr, 16, 16, 256, planes, sx, sy, 128 * 8, start).astype(np.int16) for start in (0, 1)]
        self.tiles = G.decode_gfx(tiles, 8, 8, len(tiles) // 32, [0, 1, 2, 3], list(range(0, 32, 4)),
                                  list(range(0, 256, 32)), 256)          # gfx_8x8x4_packed_msb
        self.pens = mikie_pens(prom)

    def render_raw(self, mem, bank=0, flip=False):
        """The screen's pens [256 rows, 256] (rows 16-239 visible) from the main CPU's memory (64 KB image);
        bank: the palette bank latch."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        cram = np.frombuffer(bytes(mem[0x3800:0x3C00]), np.uint8).reshape(32, 32)
        vram = np.frombuffer(bytes(mem[0x3C00:0x4000]), np.uint8).reshape(32, 32)
        codes = vram.astype(np.int32) + ((cram & 0x20).astype(np.int32) << 3)
        pix, raw = G.tile_pixmap(self.tiles, codes, (cram & 15).astype(np.int32) + 16 * bank, cram & 0x40, cram & 0x80,
                                 32, 32, 0, 16)
        front = np.repeat(np.repeat((cram & 0x10) != 0, 8, 0), 8, 1)
        # category 0 first: the front tiles' pixels stay as they are (the bitmap's first fill), then the sprites,
        # then the front tiles, opaque (the tilemap has no transparent pen: a front tile covers its 8 x 8)
        bm = np.where(front, 0, pix).astype(np.int16)
        sr = mem[0x2800:0x2890]
        for offs in range(0, 0x90, 4):
            a0, a1, a2, a3 = sr[offs:offs + 4]
            gfx = self.sprites[1 if a2 & 0x40 else 0]
            code = (a2 & 0x3F) + ((a2 & 0x80) >> 1) + ((a0 & 0x40) << 1)
            color = (a0 & 15) + 16 * bank
            G.draw_gfx(bm, VISIBLE, gfx, code, 0x800 + color * 16, not a0 & 0x10, a0 & 0x20, a3, 244 - a1,
                       lambda s: s == 0)
        return np.where(front, pix, bm)

    def render_rgb(self, mem, bank=0, flip=False):
        """The visible picture [256, 224, 3] as MAME's snapshot shows it (ROT270: the raw 256 x 224 picture turned a
        quarter counter-clockwise)."""
        raw = self.render_raw(mem, bank, flip)[VISIBLE[2]:VISIBLE[3] + 1]
        return np.rot90(self.pens[raw])


class Mikie:
    def __init__(self, dsw1=DSW1, dsw2=DSW2, dsw3=DSW3):
        rom = bytearray(0x10000)
        rom[0x6000:0x8000] = load("n14.11c")
        rom[0x8000:0xC000] = load("o13.12a")
        rom[0xC000:0x10000] = load("o17.12d")
        self.rom = bytes(rom)
        self.mem = bytearray(0x10000)              # RAM areas (and the ROM copy, for render/compare convenience)
        self.mem[0x6000:] = self.rom[0x6000:]
        self.system = self.in0 = self.in1 = 0xFF
        self.dsw1, self.dsw2, self.dsw3 = dsw1, dsw2, dsw3
        self.latch = [0] * 8
        self.palbank = 0
        self.sound_latch = 0
        self.sound_log = []
        self.watchdog = 0
        self.frame = 0
        self.cpu = M6809(self.rd, self.wr)
        self.video = None
        self.cpu.reset()
        self.next_vblank = VBLANK_LINE / LINES * FRAME_F

    def rd(self, a):
        if a >= 0x6000 or a < 0x100 or 0x2800 <= a < 0x4000:
            return self.mem[a]
        if 0x2400 <= a < 0x2404:
            return (self.system, self.in0, self.in1, self.dsw3)[a & 3]
        if a == 0x2500:
            return self.dsw1
        if a == 0x2501:
            return self.dsw2
        return 0

    def wr(self, a, v):
        if a < 0x100 or 0x2800 <= a < 0x4000:
            self.mem[a] = v
        elif 0x2000 <= a < 0x2008:
            q, b = a & 7, v & 1
            old = self.latch[q]
            self.latch[q] = b
            if q == 2 and b and not old:
                self.sound_log.append((self.frame, self.sound_latch))
            elif q == 7 and not b:
                self.cpu.set_irq(False)
        elif a == 0x2100:
            self.watchdog += 1
        elif a == 0x2200:
            self.palbank = v & 7
        elif a == 0x2400:
            self.sound_latch = v

    def run_frame(self):
        """Runs to the next VBLANK and starts it (IRQ when enabled): the state MAME's frame_done callback sees."""
        c = self.cpu
        c.run(int(self.next_vblank) - c.cycles)
        if self.latch[7]:
            c.set_irq(True)
        self.frame += 1
        self.next_vblank = (self.frame * LINES + VBLANK_LINE) / LINES * FRAME_F

    def render_rgb(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, self.palbank, bool(self.latch[6]))


if __name__ == "__main__":
    import time
    m = Mikie()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, sound commands %d" % (time.time() - t, m.cpu.pc, len(m.sound_log)))


class MikiePort(Mikie):
    """The STE runtime's schedule (src/mikie.s), one call of run_frame_port an arcade frame.

    The boot self-tests (RAM and ROM checks, the test grid: 692 frames) are skipped: the program starts at $6093 (the game's
    own initialisation, DP $29, S $37FE) with a cleared RAM.  The foreground is a task loop ($61BC: LDX <$14; LDD ,X; ASLA;
    BCC task; BSR $61C7; BRA $61BC: the queue at $2A40-$2A7F, an entry with bit 7 set is empty; $61C7 draws the
    blinking cursor cells); some tasks wait for the next frame with CWAI #$EF ($6FFF).  The IRQ handler ($620A: at the
    VBLANK while latch Q7 is 1) plays the game and queues the tasks.  The port's idle points: $61C5 (the BRA, reached
    after $61C7, with the queue empty: an RTI can return there with tasks queued), where the IRQ is delivered with $61C5 as its return address, and the CWAI,
    where the state is pushed already and the IRQ is taken.  The boot: from $6093 to the first idle point.
    """
    START = 0x6093
    IDLE = 0x61C5
    CWAI_PC = 0x6FFF
    IRQ = 0x620A

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        c = self.cpu
        c.pc, c.s, c.dp, c.cc = self.START, 0x3000, 0x30, 0x50
        self.booted = False
        self.irqs = 0

    QPTR = 0x2914               # <$14 with DP $29

    def waits(self):
        """the task queue's entry at [<$14] has bit 7: empty"""
        m = self.mem
        return m[(m[self.QPTR] << 8) | m[self.QPTR + 1]] & 0x80 != 0

    def run_to_idle(self, limit=20000000):
        """the foreground (at least one instruction) until it waits: at the idle point or in a CWAI"""
        from m6809 import CWAI
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc == self.IDLE and self.waits() or c.wait == CWAI:
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        from m6809 import CWAI
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        if self.latch[7] and (c.wait == CWAI or not c.cc & 0x10):
            c.set_irq(True)
            c.step()                                  # (the entry: the state pushed, I set, PC = the vector)
            assert c.pc == self.IRQ, hex(c.pc)
            self.irqs += 1
            self.run_to_idle()
        self.frame += 1
