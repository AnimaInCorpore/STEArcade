"""Pac-Man (Midway) arcade machine model around the reference Z80 (MAME pacman/pacman.cpp, pacman_v.cpp).

One Z80 at 3.072 MHz (18.432 MHz / 6); the screen is 384 x 264 pixel clocks at 6.144 MHz: 192 CPU cycles a line,
50688 a frame, 60.606 Hz.  Memory map (A15 is not connected: everything mirrors at +$8000; A13 is ignored above $4000):
  0000-3FFF ROM (pacman.6e/6f/6h/6j)
  4000-43FF video RAM (tile codes), 4400-47FF colour RAM, 4800-4BFF nothing (reads $BF), 4C00-4FEF RAM,
  4FF0-4FFF sprite RAM 1 (per sprite: code << 2 | flip y << 1 | flip x, colour)
  5000-5007 latch (write, D0; mirrored to 503F): 0 IRQ enable, 1 sound enable, 3 flip screen, 7 coin counter
  5040-505F Namco WSG registers (write; kept in .sound), 5060-506F sprite RAM 2 (write only: per sprite y, x)
  50C0 watchdog (write; not modelled)
  reads: 5000 IN0, 5040 IN1, 5080 DSW1, 50C0 DSW2 (each mirrored over 64 bytes)
  I/O port 00 (write): the byte the CPU's IM 2 acknowledge reads (the vector; $FA at boot -> $3000, $FC -> $008D)
Interrupt: IRQ0 at the vertical blank (line 224) while latch bit 0 is set; a level, held until the CPU writes bit 0 = 0
(the handler does at its start).

Reference renderer: 36 x 28 tiles (the Namco column/row mapping shared with Galaga), 8 sprites of 16 x 16, 2 bits a
pixel, ROT90.  Colours from MAME's resistor network weights (compute_resistor_weights, 1k/470/220 ohm); a sprite pen
is transparent where its colour lookup entry is 0 (MAME's transpen_mask), tiles are opaque.
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "pacman")

CYCLES_PER_LINE = 192           # 3.072 MHz / (6.144 MHz / 384)
LINES = 264
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES   # 50688, 60.606 Hz
VBLANK_LINE = 224
BLACK = 32                      # render_raw's index for the area outside the arcade picture (never drawn here)

# Inputs (active low).  IN0: up 01, left 02, right 04, down 08, rack test 10, coin1 20, coin2 40, service 80.
# IN1: P2 joystick 0F (cocktail), service mode 10, start1 20, start2 40, cabinet 80 (1 = upright).
UP, LEFT, RIGHT, DOWN = 0x01, 0x02, 0x04, 0x08
COIN1 = 0x20
START1, START2 = 0x20, 0x40
DSW1_DEFAULT = 0xC9             # 1 coin 1 credit, 3 lives, bonus at 10000, normal difficulty, normal ghost names


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def decode_gfx(data, width, height, planes, xoffs, yoffs, size):
    """MAME gfx layout decode: bit offsets count from the MSB of each byte, the first plane is the most significant bit
    of the pixel (as in games/galaga/tools/machine.py, checked against MAME there)."""
    n = len(data) // size
    out = np.zeros((n, height, width), np.uint8)
    for i in range(n):
        base = i * size * 8
        for y in range(height):
            for x in range(width):
                v = 0
                for p, po in enumerate(planes):
                    off = base + po + xoffs[x] + yoffs[y]
                    bit = (data[off >> 3] >> (7 - (off & 7))) & 1
                    v |= bit << (len(planes) - 1 - p)
                out[i, y, x] = v
    return out


def resistor_weights(nets, maxval=255):
    """MAME's compute_resistor_weights(0, maxval, -1.0, ...) without pull-ups / pull-downs: per net, the output of each
    resistor alone at Vcc against the others to ground, then all nets scaled by the largest net's sum."""
    out = []
    for res in nets:
        w = []
        for n in range(len(res)):
            r0 = 1.0 / 1e12
            r1 = 1.0 / 1e12
            for j, r in enumerate(res):
                if j == n:
                    r1 += 1.0 / r
                else:
                    r0 += 1.0 / r
            r0, r1 = 1.0 / r0, 1.0 / r1
            w.append(min(max(maxval * r0 / (r1 + r0), 0.0), float(maxval)))
        out.append(w)
    scale = maxval / max(sum(w) for w in out)
    return [[v * scale for v in w] for w in out]


def combine(weights, *bits):
    return int(sum(w * b for w, b in zip(weights, bits)) + 0.5)


class Gfx:
    """Decoded characters (256), sprites (64), the 32 colours and the 64 x 4 colour lookup table."""

    def __init__(self):
        step4 = lambda s: [s, s + 1, s + 2, s + 3]
        step8 = lambda s, d: [s + d * i for i in range(8)]
        self.chars = decode_gfx(load("pacman.5e"), 8, 8, (0, 4), step4(64) + step4(0), step8(0, 8), 16)
        self.sprites = decode_gfx(load("pacman.5f"), 16, 16, (0, 4),
                                  step4(64) + step4(128) + step4(192) + step4(0),
                                  step8(0, 8) + step8(256, 8), 64)
        prom = load("82s123.7f")
        rw, gw, bw = resistor_weights([(1000, 470, 220), (1000, 470, 220), (470, 220)])
        self.palette = []
        for c in prom:
            bit = lambda n: (c >> n) & 1
            self.palette.append((combine(rw, bit(0), bit(1), bit(2)), combine(gw, bit(3), bit(4), bit(5)),
                                 combine(bw, bit(6), bit(7))))
        self.lut = [v & 0x0f for v in load("82s126.4a")]     # colour * 4 + pen -> palette (bank 0: the first 16)
        self.rgb = np.array(self.palette + [(0, 0, 0)], np.uint8)       # index 32: black


class Pacman:
    def __init__(self, dsw1=DSW1_DEFAULT, frame_line=VBLANK_LINE):
        """frame_line: the screen line a frame starts at.  224, the start of the vertical blank, is MAME's phase: the
        frame ends where MAME draws the screen, so render_raw after run_frame is MAME's picture of that frame."""
        self.frame_line = frame_line
        self.rom = load("pacman.6e") + load("pacman.6f") + load("pacman.6h") + load("pacman.6j")
        self.ram = bytearray(0x1000)          # 4000-4FFF (4800-4BFF unused)
        self.sprite2 = bytearray(0x10)        # 5060-506F
        self.sound = bytearray(0x20)          # 5040-505F
        self.latch = [0] * 8
        self.vector = 0
        self.in0 = 0xff
        self.in1 = 0xff
        self.dsw1 = dsw1
        self.dsw2 = 0x00
        self.cpu = Z80(self.rd8, self.wr8, io_out=self.io_out)
        self.cpu.afmask = 0xC1                # as the translation keeps them (S Z C), like the other Z80 ports
        self.irq_line = False
        self.frame = 0
        self.gfx = None
        self.io_log = []
        self.sound_log = None                 # a list to collect (frame, cycle, register, value) of the WSG writes

    # ---- bus -----------------------------------------------------------
    def rd8(self, a):
        a &= 0x7fff
        if a < 0x4000:
            return self.rom[a]
        a &= 0x5fff
        if a < 0x5000:
            if 0x4800 <= a < 0x4c00:
                return 0xbf
            return self.ram[a - 0x4000]
        r = a & 0xc0
        if r == 0x00:
            return self.in0
        if r == 0x40:
            return self.in1
        if r == 0x80:
            return self.dsw1
        return self.dsw2

    def wr8(self, a, v):
        a &= 0x7fff
        if a < 0x4000:
            return
        a &= 0x5fff
        if a < 0x5000:
            if not 0x4800 <= a < 0x4c00:
                self.ram[a - 0x4000] = v
            return
        r = a & 0xff
        if r < 0x40:
            self.latch_w(r & 7, v & 1)
        elif r < 0x60:
            self.sound[r & 0x1f] = v & 0x0f
            if self.sound_log is not None:
                self.sound_log.append((self.frame, self.cpu.cycles, r & 0x1f, v & 0x0f))
        elif r < 0x70:
            self.sprite2[r & 0x0f] = v
        elif r >= 0xc0:
            pass                              # watchdog
        elif r >= 0x80 or r >= 0x70:
            pass                              # unmapped writes (MAME: nopw)

    def latch_w(self, bit, v):
        self.latch[bit] = v
        if bit == 0 and not v:
            self.irq_line = False

    def io_out(self, port, v):
        if port & 0xff == 0:
            self.vector = v
        else:
            self.io_log.append((self.frame, port & 0xff, v))

    # ---- inputs --------------------------------------------------------
    def set_inputs(self, joy=0, coin=False, start1=False, start2=False):
        """joy: UP / LEFT / RIGHT / DOWN bits pressed (active high here)."""
        self.in0 = (0xff & ~joy & ~(COIN1 if coin else 0)) & 0xff
        self.in1 = (0xff & ~(START1 if start1 else 0) & ~(START2 if start2 else 0)) & 0xff

    # ---- time ----------------------------------------------------------
    def run_frame(self):
        """One frame from line frame_line: the IRQ is raised at the vertical blank (line 224) and held until the program
        clears latch bit 0 (MAME: vblank_irq, irq_mask_w)."""
        cpu = self.cpu
        start = cpu.cycles
        vbl = start + ((VBLANK_LINE - self.frame_line) % LINES) * CYCLES_PER_LINE
        end = start + CYCLES_PER_FRAME
        raised = False
        while cpu.cycles < end:
            if not raised and cpu.cycles >= vbl:
                raised = True
                if self.latch[0]:
                    self.irq_line = True
            if self.irq_line and cpu.iff1:
                cpu.irq(self.vector)
            cpu.step()
        self.frame += 1

    # ---- rendering -----------------------------------------------------
    def render_raw(self):
        """288 x 224 (x, y) bitmap of palette indices, as MAME's screen before the rotation."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        bmp = np.zeros((224, 288), np.uint8)
        ram = self.ram
        lut = np.array(g.lut, np.uint8).reshape(64, 4)
        for row in range(28):
            for col in range(36):
                r, c = row + 2, col - 2
                if c & 0x20:
                    idx = r + ((c & 0x1f) << 5)
                else:
                    idx = c + (r << 5)
                code = ram[idx]
                color = ram[0x400 + idx] & 0x1f
                bmp[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = lut[color][g.chars[code]]
        # sprites: 7 down to 3, then 2 down to 0 one line lower (MAME's xoffsethack); clipped to x 16-271
        for offs in list(range(14, 4, -2)) + [4, 2, 0]:
            code = ram[0xff0 + offs] >> 2
            flags = ram[0xff0 + offs]
            color = ram[0xff0 + offs + 1] & 0x1f
            sx = 272 - self.sprite2[offs + 1]
            sy = self.sprite2[offs] - 31 + (1 if offs <= 4 else 0)
            tile = g.sprites[code]
            if flags & 1:
                tile = tile[:, ::-1]
            if flags & 2:
                tile = tile[::-1, :]
            pens = lut[color][tile]
            opaque = pens != 0
            for x0 in (sx, sx - 256):
                ys0, ys1 = max(sy, 0), min(sy + 16, 224)
                xs0, xs1 = max(x0, 16), min(x0 + 16, 272)
                if ys0 >= ys1 or xs0 >= xs1:
                    continue
                sub = pens[ys0 - sy:ys1 - sy, xs0 - x0:xs1 - x0]
                m = opaque[ys0 - sy:ys1 - sy, xs0 - x0:xs1 - x0]
                blk = bmp[ys0:ys1, xs0:xs1]
                blk[m] = sub[m]
        return bmp

    def render_rgb(self):
        bmp = self.render_raw()
        rgb = self.gfx.rgb[bmp]                  # [y][x][3], 224 x 288
        return rgb.transpose(1, 0, 2)[:, ::-1]   # ROT90: 288 tall, 224 wide


class PacmanPort(Pacman):
    """The STE runtime's schedule (src/pacman.s), one call of run_frame_port an arcade frame.

    The foreground waits at two places: the task loop's spin at IDLE ($238D: the task ring's read entry, ([$4C82]),
    has bit 7 set: empty) and the boot's `halt` ($234A, the only one).  There a frame ends; the next one delivers the
    IRQ (latch bit 0 and IFF1 set): the address the foreground waits at is pushed (IDLE, or the instruction after the
    halt) and the CPU goes to the IM 2 vector's target ($3FFA -> $3000 at boot, which does not return; $3FFC -> $008D
    the frame handler, which returns to IDLE with reti).  Then the foreground runs to its next wait: the instruction at
    IDLE runs again before the ring is looked at (as the 68000 dispatch to Z238D does).  Without the IRQ the frame
    passes and the foreground goes on.  A frame of the arcade's foreground that a task overruns becomes a longer one
    here: the IRQ waits for the spin.
    """
    IDLE = 0x238D
    HALT = 0x234A

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.irq_count = 0

    def waits(self):
        c = self.cpu
        if c.halted:
            return True
        if c.pc != self.IDLE:
            return False
        hl = self.ram[0xc82] | (self.ram[0xc83] << 8)
        return self.rd8(hl) & 0x80 != 0

    def run_to_wait(self, limit=20_000_000):
        """the foreground (at least one instruction) until it waits"""
        c = self.cpu
        for _ in range(limit):
            c.step()
            if self.waits():
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        if self.frame == 0 and not self.waits():
            self.run_to_wait()                    # the boot to its halt
        if self.latch[0] and c.iff1:
            c.halted = False
            c.iff1 = c.iff2 = 0
            c.push(c.pc)                          # (after the halt the pc is already the next instruction)
            c.pc = self.rd8(0x3f00 | self.vector) | (self.rd8(0x3f01 | self.vector) << 8)
            self.irq_count += 1
            self.run_to_wait()
        elif not c.halted:
            self.run_to_wait()
        self.frame += 1


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(np.ascontiguousarray(arr))
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)


if __name__ == "__main__":
    import time
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    out = sys.argv[2] if len(sys.argv) > 2 else "pacman.png"
    m = Pacman()
    t0 = time.time()
    for f in range(frames):
        m.run_frame()
        if f % 120 == 0:
            print("frame", f, "pc %04X" % m.cpu.pc, "latch", m.latch, "vector %02X" % m.vector)
    print("%.1f s, %.1f frames/s" % (time.time() - t0, frames / (time.time() - t0)))
    print("other port writes:", m.io_log[:10])
    save_png(m.render_rgb(), out)
    print("wrote", out)
