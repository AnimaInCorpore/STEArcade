"""Time Pilot (MAME `timeplt`, Konami 1982): the reference board, from MAME konami/timeplt.cpp.

CPU: main Z80 at 18.432 MHz / 6 = 3.072 MHz (engine/z80.py).  The sound board (a Z80 with two AY-3-8910, as Pooyan's)
only hears the command latch ($C000 write) and the trigger (latch Q2): sound_log keeps (frame, command).
Screen: 256 x 256 total, 256 x 224 visible (lines 16-239), 60 Hz, ROT90 (MAME's snapshot is 224 wide, 256 high): a
frame is 51200 cycles, a line 200.  VBLANK starts at line 240: the NMI is asserted while latch Q0 is 1 and stays
asserted until Q0 is written 0 (the handler does so at once).

Main CPU map: $0000-$5FFF ROM ($6000-$7FFF the empty diagnostics socket), $A000-$A3FF colour RAM, $A400-$A7FF video
    RAM, $A800-$AFFF RAM, $B000-$B0FF / $B400-$B4FF the two sprite RAMs (mirrored in $B000-$BFFF); reads $C000 the
    beam's line, $C200 DSW1, $C300 IN0 (SYSTEM), $C320 IN1 (P1), $C340 IN2 (P2), $C360 DSW0 (with mirrors); writes
    $C000 sound command, $C200 watchdog, $C300-$C30F the LS259 (Q0 NMI enable, Q1 flip (inverted), Q2 sound IRQ,
    Q3 sound mute, Q4 video enable, Q5/Q6 coin counters).

Video: a 32 x 32 tilemap of 8x8 2bpp tiles (512: code = video byte + 256 x colour bit 5; colour bits 0-4; bit 6 flip
x, bit 7 flip y; bit 4 the category); sprites 16x16 2bpp, 24 of them ($B010-$B03F: x, code; $B410-$B43F: attributes,
y), drawn from the last ($3E) to the first (the first on top), pen 0 transparent.  Order: the category 0 tiles, the
sprites, the category 1 tiles (opaque, over the sprites).  Colours: two 32 x 8 PROMs (5-5-5 weighted), sprite pens
0-255 -> palette 0-15 and tile pens through the lookup PROMs (tiles: 16-31).

The clouds are multiplexed: the NMI handler waits for the beam ($C000) to pass a cloud sprite in the upper half, then
moves it 128 lines down and 128 pixels across (16 sites $0FAC-$118D clear y bit 7).  MAME's picture shows the old
sprite above and the new one below; the port draws both (the old content captured just before the clear).
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from z80 import Z80
import mamegfx as G

FRAME = 51200
LINE = 200
VBLANK_LINE = 240
VISIBLE = (0, 255, 16, 239)

# MAME's defaults: DSW0 1 coin 1 credit both slots ($FF); DSW1 3 lives ($03), upright, bonus 10000 50000 ($08),
# difficulty 4 ($40), demo sounds on
DSW0, DSW1 = 0xFF, 0x4B

# the cloud slots' y clears: pc -> sprite RAM offset (the 16 sites before `ld ($B4xx),a`; F030Arcade generate.py)
CLOUD_CLEAR = dict(zip(
    (0x0FAC, 0x0FCC, 0x0FEC, 0x100C, 0x102C, 0x104C, 0x106C, 0x108C,
     0x10AD, 0x10CD, 0x10ED, 0x110D, 0x112D, 0x114D, 0x116D, 0x118D),
    (0x10, 0x12, 0x14, 0x36, 0x38, 0x3A, 0x3C, 0x3E) * 2))


def load(name):
    return (EXTRACTED / "timeplt" / name).read_bytes()


def palette_rgb():
    """The 32 colours (MAME timeplt_state::palette)."""
    p0, p1 = load("timeplt.b4"), load("timeplt.b5")
    w = (0x19, 0x24, 0x35, 0x40, 0x4D)
    out = []
    for i in range(32):
        r = (p1[i] >> 1) & 31
        g = (p1[i] >> 6) | ((p0[i] & 7) << 2)
        b = p0[i] >> 3
        out.append(tuple(sum(w[k] for k in range(5) if v >> k & 1) for v in (r, g, b)))
    return np.array(out, np.uint8)


def pens_rgb():
    """The 384 pens' RGB: tile pens 0-127 (colour c, pen p: 4 c + p) -> palette 16-31, sprite pens 128-383 -> 0-15."""
    pal = palette_rgb()
    e9, e12 = load("timeplt.e9"), load("timeplt.e12")
    idx = [(e12[i] & 15) + 16 for i in range(128)] + [e9[i] & 15 for i in range(256)]
    return pal[idx], np.array(idx)


class Video:
    def __init__(self):
        sx = [0, 1, 2, 3, 64, 65, 66, 67, 128, 129, 130, 131, 192, 193, 194, 195]
        sy = list(range(0, 64, 8)) + list(range(256, 320, 8))
        self.tiles = G.decode_gfx(load("tm6"), 8, 8, 512, [4, 0], sx[:8], sy[:8], 128)
        self.sprites = G.decode_gfx(load("tm4") + load("tm5"), 16, 16, 256, [4, 0], sx, sy, 512).astype(np.int16)
        self.pens, self.pen_colour = pens_rgb()

    def render_raw(self, mem, extra=()):
        """The screen's pens [256 rows, 256] (rows 16-239 visible; unrotated) from the main CPU's memory; extra: the
        captured old cloud contents [(offset, x, code, attributes, y)], drawn in their slot's place too."""
        cram = np.frombuffer(bytes(mem[0xA000:0xA400]), np.uint8).reshape(32, 32)
        vram = np.frombuffer(bytes(mem[0xA400:0xA800]), np.uint8).reshape(32, 32).astype(np.int32)
        codes = ((cram & 0x20).astype(np.int32) << 3) | vram
        bm, _ = G.tile_pixmap(self.tiles, codes, cram & 31, cram & 0x40, cram & 0x80, 32, 32, 0, 4)
        bm = bm.astype(np.int16)
        front = np.repeat(np.repeat((cram & 0x10) != 0, 8, 0), 8, 1)
        tiles = bm.copy()
        old = {}
        for e in extra:
            old.setdefault(e[0], []).append(e[1:])
        clip = VISIBLE
        for offs in range(0x3E, 0x0E, -2):
            ents = old.get(offs, []) + [(mem[0xB000 + offs], mem[0xB001 + offs], mem[0xB400 + offs],
                                         mem[0xB401 + offs])]
            for x, code, attr, y in ents:
                x, code, attr, y = int(x), int(code), int(attr), int(y)
                G.draw_gfx(bm, clip, self.sprites, code, 128 + (attr & 0x3F) * 4, not attr & 0x40, attr & 0x80, x,
                           241 - y, lambda s: s == 0)
        bm[front] = tiles[front]
        return bm

    def render_rgb(self, mem, extra=(), rotate=True):
        """The visible picture as MAME's snapshot shows it: [256, 224, 3] rotated (ROT90), else [224, 256, 3]."""
        rgb = self.pens[self.render_raw(mem, extra)[VISIBLE[2]:VISIBLE[3] + 1]]
        return np.ascontiguousarray(np.rot90(rgb, -1)) if rotate else rgb


class Timeplt:
    def __init__(self, dsw0=DSW0, dsw1=DSW1):
        self.mem = bytearray(0x10000)
        self.mem[:0x6000] = b"".join(load(n) for n in ("tm1", "tm2", "tm3"))
        self.system = self.p1 = self.p2 = 0xFF
        self.dsw0, self.dsw1 = dsw0, dsw1
        self.latch = [0] * 8
        self.nmi_line = False
        self.sound_log = []
        self.frame = 0
        self.cpu = Z80(self.rd, self.wr)
        self.video = None

    def beam(self):
        return (self.cpu.cycles % FRAME) // LINE

    def rd(self, a):
        if a < 0xB000:
            return self.mem[a] if a < 0x6000 or a >= 0xA000 else 0xFF
        if a < 0xC000:
            return self.mem[0xB000 | (a & 0x4FF)]
        if a < 0xD000:
            a &= ~0x0C00
            if a & 0xFF00 == 0xC000:
                return self.beam()
            if a & 0xFF00 == 0xC200:
                return self.dsw1
            if a & 0xFF00 == 0xC300:
                return (self.system, self.p1, self.p2, self.dsw0)[(a >> 5) & 3]
        return 0xFF

    def wr(self, a, v):
        if 0xA000 <= a < 0xB000:
            self.mem[a] = v
        elif 0xB000 <= a < 0xC000:
            self.mem[0xB000 | (a & 0x4FF)] = v
        elif a & 0xF3FF == 0xC000:
            self.sound_cmd = v
        elif 0xC300 <= a <= 0xC30F:
            q, b = (a & 15) >> 1, v & 1
            if q == 2 and b and not self.latch[2]:
                self.sound_log.append((self.frame, getattr(self, "sound_cmd", 0)))
            self.latch[q] = b
            if q == 0 and not b:
                self.nmi_line = False

    def run_frame(self):
        """MAME's schedule: runs to the next VBLANK and starts it (the NMI)."""
        c = self.cpu
        target = (self.frame + 1) * FRAME - (FRAME - VBLANK_LINE * LINE)
        while c.cycles < target:
            c.step()
        if self.latch[0] and not self.nmi_line:
            self.nmi_line = True
            c.nmi()
        self.frame += 1


class TimepltPort(Timeplt):
    """The STE runtime's schedule (src/timeplt.s), one call of run_frame_port an arcade frame.

    The foreground is a task loop: $0B93 reads the queue entry at $AC00 + [$A9B3]; one with bit 7 set is empty and the
    loop goes round ($0B90 jp $0B93).  The NMI handler ($0066 -> $00D8) plays the game.  The port's hook is $0B93 with
    an empty queue: there the NMI is delivered (while latch Q0 allows it) with TOKEN as its return address; on its
    return the foreground goes on at the hook until the queue is empty again.
    The beam ($C000) reads 255: the cloud waits ($1098: until the beam passed the old sprite) end at once; the old
    contents are captured at the clears (CLOUD_CLEAR: the first per slot and frame) for the picture: extra.
    `ld a,r` reads the port's shift register (rnd).
    """
    TOKEN = 0x6001                         # (the empty diagnostics socket: never code)
    IDLE = 0x0B93

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cpu.r_hook = self.rnd
        self.rnd_state = 0xACE1
        self.booted = False
        self.nmi_count = 0
        self.extra = []
        self._capt = {}
        step0 = self.cpu.step

        def step():
            pc = self.cpu.pc
            if pc in CLOUD_CLEAR:
                off = CLOUD_CLEAR[pc]
                if off not in self._capt:
                    m = self.mem
                    self._capt[off] = (off, m[0xB000 + off], m[0xB001 + off], m[0xB400 + off], m[0xB401 + off])
            return step0()
        self.cpu.step = step

    def beam(self):
        return 255

    def rnd(self):
        s = self.rnd_state
        s = (s >> 1) ^ (0xB400 if s & 1 else 0)
        self.rnd_state = s
        return s & 0xFF

    def waits(self):
        m = self.mem
        return m[0xAC00 | m[0xA9B3]] & 0x80 != 0

    def run_to_idle(self, limit=20000000):
        """the foreground (at least one instruction) until the task queue is empty at the hook"""
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc == self.IDLE and self.waits():
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        self._capt = {}
        if self.latch[0]:
            c.iff2, c.iff1 = c.iff1, 0
            c.halted = False
            c.push(self.TOKEN)
            c.pc = 0x66
            for _ in range(5000000):
                c.step()
                if c.pc == self.TOKEN:
                    break
            else:
                raise RuntimeError('the NMI did not return (frame %d)' % self.frame)
            self.nmi_count += 1
            c.pc = self.IDLE
        self.run_to_idle()
        self.extra = self.valid_extra()
        self.frame += 1

    def valid_extra(self):
        """the captured old contents whose slot did move as a reuse does (y bit 7 cleared, x + 128, the rest kept)"""
        out = []
        m = self.mem
        for off, (o, x, code, attr, y) in sorted(self._capt.items()):
            if y & 0x80 and m[0xB401 + off] == y & 0x7F and m[0xB000 + off] == (x + 128) & 255 and \
                    m[0xB001 + off] == code and m[0xB400 + off] == attr:
                out.append((off, x, code, attr, y))
        return out

    def render_rgb(self, rotate=True):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, self.extra, rotate)


if __name__ == "__main__":
    import time
    g = TimepltPort()
    t = time.time()
    for _ in range(600):
        g.run_frame_port()
    print("600 frames in %.1f s, pc %04X, NMIs %d, sound commands %d, clouds reused %d" % (
        time.time() - t, g.cpu.pc, g.nmi_count, len(g.sound_log), len(g.extra)))
