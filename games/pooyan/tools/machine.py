"""Pooyan (MAME `pooyan`, Konami 1982): the reference board, from MAME konami/pooyan.cpp ("very similar to Time Pilot").

CPU: main Z80 at 18.432 MHz / 6 = 3.072 MHz (engine/z80.py).  The sound board is Time Pilot's (a Z80 with two
AY-3-8910, `timeplt_audio`); it only hears the command latch ($A100 write) and the trigger (latch Q1's rising edge):
sound_log keeps (frame, command).
Screen: 384 x 264 total (pixel clock 6.144 MHz: a line is 192 CPU cycles, a frame 50688, 60.6 Hz), 256 x 224 visible
(lines 16-239), ROT90 (MAME's snapshot is 224 wide, 256 high).  VBLANK starts at line 240: the NMI is asserted while
latch Q0 is 1 and stays asserted until Q0 is written 0.

Main CPU map: $0000-$7FFF ROM, $8000-$83FF colour RAM, $8400-$87FF video RAM, $8800-$8FFF RAM, $9000-$90FF /
    $9400-$94FF the two sprite RAMs (mirrored in $9000-$9FFF, bit 10 selects); reads (with mirrors, $A000-$FFFF):
    a & $A180 = $A000 DSW1, a & $A1E0 = $A080 IN0 (SYSTEM), $A0A0 IN1 (P1), $A0C0 IN2 (P2), $A0E0 DSW0; writes
    a & $A180 = $A000 watchdog, $A100 sound command, $A180 the LS259 (a & 7: Q0 NMI enable, Q1 sound IRQ, Q2 sound
    mute, Q3/Q4 coin counters, Q7 flip (inverted)).  No beam register (unlike Time Pilot).

Video: a 32 x 32 tilemap of 8x8 4bpp tiles (256: code = video byte; colour RAM bits 0-3 colour, bit 6 flip x, bit 7
flip y), no priority; sprites 16x16 4bpp (64 codes), 24 of them ($9010-$903F: x, code; $9410-$943F: attributes, 240 - y),
drawn from the first ($10) to the last (the last on top); a pen is transparent where its lookup entry is colour 0.
Colours: one 32 x 8 PROM through resistor networks (R, G: 1k/470/220; B: 470/220), two 256 x 4 lookup PROMs (tiles:
colours 16-31, sprites: 0-15).
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from z80 import Z80
import mamegfx as G

LINE = 192
LINES = 264
FRAME = LINE * LINES
VBLANK_LINE = 240
VISIBLE = (0, 255, 16, 239)
ROMS = ("1.4a", "2.5a", "3.6a", "4.7a")

# MAME's defaults: DSW0 1 coin 1 credit both slots ($FF); DSW1 3 lives ($03), upright ($00), bonus 50K 80K+ ($08),
# difficulty 1 (easy, $70), demo sounds on ($00)
DSW0, DSW1 = 0xFF, 0x7B


def load(name):
    return (EXTRACTED / "pooyan" / name).read_bytes()


def palette_rgb():
    """The 32 colours (MAME pooyan_state::palette)."""
    prom = load("pooyan.pr1")
    rw, gw, bw = G.resistor_weights(0, 255, -1.0, ([1000, 470, 220], 1000, 0), ([1000, 470, 220], 1000, 0),
                                    ([470, 220], 1000, 0))
    out = []
    for v in prom:
        b = [(v >> k) & 1 for k in range(8)]
        out.append((G.combine(rw, b[0], b[1], b[2]), G.combine(gw, b[3], b[4], b[5]), G.combine(bw, b[6], b[7])))
    return np.array(out, np.uint8)


def pens_rgb():
    """The 512 pens' RGB: tile pens 0-255 (colour c, pen p: 16 c + p) -> palette 16-31, sprite pens 256-511 -> 0-15;
    also each pen's palette index."""
    pal = palette_rgb()
    tl, sp = load("pooyan.pr3"), load("pooyan.pr2")
    idx = [(tl[i] & 15) | 16 for i in range(256)] + [sp[i] & 15 for i in range(256)]
    return pal[idx], np.array(idx)


class Video:
    def __init__(self):
        planes = [0x8000 + 4, 0x8000, 4, 0]
        sx = [0, 1, 2, 3, 64, 65, 66, 67, 128, 129, 130, 131, 192, 193, 194, 195]
        sy = list(range(0, 64, 8)) + list(range(256, 320, 8))
        self.tiles = G.decode_gfx(load("8.10g") + load("7.9g"), 8, 8, 256, planes, sx[:8], sy[:8], 128)
        self.sprites = G.decode_gfx(load("6.9a") + load("5.8a"), 16, 16, 64, planes, sx, sy, 512).astype(np.int16)
        self.pens, self.pen_colour = pens_rgb()
        # transmask: per sprite colour the pixel values whose pen maps to colour 0
        self.trans = [np.array([self.pen_colour[256 + 16 * c + p] == 0 for p in range(16)]) for c in range(16)]

    def render_raw(self, mem):
        """The screen's pens [256 rows, 256] (rows 16-239 visible; unrotated) from the main CPU's memory."""
        cram = np.frombuffer(bytes(mem[0x8000:0x8400]), np.uint8).reshape(32, 32)
        vram = np.frombuffer(bytes(mem[0x8400:0x8800]), np.uint8).reshape(32, 32).astype(np.int32)
        bm, _ = G.tile_pixmap(self.tiles, vram, cram & 15, cram & 0x40, cram & 0x80, 32, 32, 0, 16)
        bm = bm.astype(np.int16)
        for offs in range(0x10, 0x40, 2):
            x, code = int(mem[0x9000 + offs]), int(mem[0x9001 + offs])
            attr, y = int(mem[0x9400 + offs]), int(mem[0x9401 + offs])
            c = attr & 15
            t = self.trans[c]
            G.draw_gfx(bm, VISIBLE, self.sprites, code, 256 + 16 * c, not attr & 0x40, attr & 0x80, x, 240 - y,
                       lambda s, t=t: t[s])
        return bm

    def render_rgb(self, mem, rotate=True):
        """The visible picture as MAME's snapshot shows it: [256, 224, 3] rotated (ROT90), else [224, 256, 3]."""
        rgb = self.pens[self.render_raw(mem)[VISIBLE[2]:VISIBLE[3] + 1]]
        return np.ascontiguousarray(np.rot90(rgb, -1)) if rotate else rgb


class Pooyan:
    def __init__(self, dsw0=DSW0, dsw1=DSW1):
        self.mem = bytearray(0x10000)
        self.mem[:0x8000] = b"".join(load(n) for n in ROMS)
        self.system = self.p1 = self.p2 = 0xFF
        self.dsw0, self.dsw1 = dsw0, dsw1
        self.latch = [0] * 8
        self.nmi_line = False
        self.sound_cmd = 0
        self.sound_log = []
        self.frame = 0
        self.cpu = Z80(self.rd, self.wr)
        self.video = None

    def rd(self, a):
        if a < 0x9000:
            return self.mem[a]
        if a < 0xA000:
            return self.mem[0x9000 | (a & 0x4FF)]
        if a & 0xA180 == 0xA000:
            return self.dsw1
        if a & 0xA180 == 0xA080:
            return (self.system, self.p1, self.p2, self.dsw0)[(a >> 5) & 3]
        return 0x00                           # (unmapped: MAME's default unmap value)

    def wr(self, a, v):
        if 0x8000 <= a < 0x9000:
            self.mem[a] = v
        elif a < 0xA000:
            if a >= 0x9000:
                self.mem[0x9000 | (a & 0x4FF)] = v
        else:
            s = a & 0xA180
            if s == 0xA100:
                self.sound_cmd = v
            elif s == 0xA180:
                q, b = a & 7, v & 1
                if q == 1 and b and not self.latch[1]:
                    self.sound_log.append((self.frame, self.sound_cmd))
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

    def render_rgb(self, rotate=True):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, rotate)


class PooyanPort(Pooyan):
    """The STE runtime's schedule, one call of run_frame_port an arcade frame.

    The foreground is a task loop: $020F reads the queue entry at $8800 + [$88A1]; one with bit 7 set is empty, and
    the loop calls $0254 (the idle work: the ROM check $208C, or the blinking 1UP / 2UP labels rewritten from RAM: the
    same bytes on every pass) and goes round ($021C jr $020F).  The NMI handler ($0066 -> $066D) plays the game.  The
    port's hook is $021C, reached after one idle pass with an empty queue: there the NMI is delivered (while latch Q0
    allows it) with TOKEN as its return address; on its return the foreground goes on at the hook (jr $020F) until the
    queue is empty again and the idle work has run once more.
    """
    TOKEN = 0xB000                         # (the I/O block: never code)
    IDLE = 0x021C

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.booted = False
        self.nmi_count = 0

    def run_to_idle(self, limit=20000000):
        """the foreground (at least one instruction) until it reaches the hook (the queue was empty at $020F)"""
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc == self.IDLE:
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
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
        self.frame += 1


if __name__ == "__main__":
    import time
    g = PooyanPort()
    t = time.time()
    for _ in range(600):
        g.run_frame_port()
    print("600 frames in %.1f s, pc %04X, NMIs %d, sound commands %d, latch %s" % (
        time.time() - t, g.cpu.pc, g.nmi_count, len(g.sound_log), g.latch))
