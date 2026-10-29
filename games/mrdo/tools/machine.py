"""Mr. Do! (Universal, 1982) arcade machine model around the reference Z80 (MAME universal/mrdo.cpp, mrdo_v.cpp, 0.286).

One Z80 at 4.1 MHz (8.2 MHz / 2).  The screen is 312 x 262 pixel clocks at 4.9 MHz (19.6 MHz / 4): 59.943 Hz,
68398.04 CPU cycles a frame (261.06 a line).  Visible: raw x 8-247, y 32-223 (240 x 192), ROT270.
Memory map (no mirrors; unmapped reads give 0):
  0000-7FFF ROM (a4-01, c4-02, e4-03, f4-04)
  8000-87FF background video RAM: 8000-83FF attributes (bit 7 code bit 8, bit 6 opaque, bits 0-5 colour), 8400-87FF codes
  8800-8FFF foreground video RAM, the same layout (its writes also latch the PAL U001: no effect in the `mrdo` set)
  9000-90FF sprite RAM (write only): 64 x (code, 256 - y, attr: colour 0-3, flip x 4, flip y 5, x)
  9800 flip screen (bit 0; bits 1-3 priority, unused), 9801 / 9802 SN76489 #1 / #2, 9803 read: the protection
       (MAME's stand-in for the PAL: the ROM byte at HL)
  A000 P1, A001 P2 (coins), A002 DSW1, A003 DSW2 (active low)
  E000-EFFF RAM; F000-F7FF background scroll x, F800-FFFF background scroll y (write)
Interrupt: IRQ0 at the vertical blank (line 224), irq0_line_hold: held until the CPU takes it (IM 1: RST 38).
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "mrdo")

CYCLES_PER_FRAME = 312 * 262 * 41 / 49        # 68398.04: 4.1 MHz CPU, 4.9 MHz pixel clock
LINES = 262
CYCLES_PER_LINE = CYCLES_PER_FRAME / LINES
VBLANK_LINE = 224
VIS_X0, VIS_X1, VIS_Y0, VIS_Y1 = 8, 248, 32, 224

# Inputs (active low).  P1: left 01, down 02, right 04, up 08, fire 10, start1 20, start2 40, tilt 80.
# P2: the cocktail player's 0F / fire 10, coin1 40, coin2 80.
LEFT, DOWN, RIGHT, UP, FIRE = 0x01, 0x02, 0x04, 0x08, 0x10
START1, START2 = 0x20, 0x40
COIN1, COIN2 = 0x40, 0x80
DSW1_DEFAULT = 0xDF             # easy, rack test off, special / extra easy, upright, 3 lives
DSW2_DEFAULT = 0xFF             # 1 coin 1 credit both slots

PROGRAM = ("a4-01.bin", "c4-02.bin", "e4-03.bin", "f4-04.bin")


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def decode_gfx(data, width, height, planes, xoffs, yoffs, size, n):
    """MAME gfx layout decode: bit offsets count from the MSB of each byte, the first plane is the most significant
    bit of the pixel."""
    out = np.zeros((n, height, width), np.uint8)
    bits = np.unpackbits(np.frombuffer(data, np.uint8))
    for p, po in enumerate(planes):
        for y in range(height):
            for x in range(width):
                off = po + xoffs[x] + yoffs[y] + np.arange(n) * size
                out[:, y, x] |= bits[off] << (len(planes) - 1 - p)
    return out


def palette_weights():
    """mrdo_state::palette_init's 16 levels, computed in single precision as the C++ (float) does."""
    f = np.float32
    R1, R2, R3, R4, pull, potadjust = 150, 120, 100, 75, 220, f(0.7)
    pot = [f(0)] * 16
    for i in range(15, -1, -1):
        par = f(0)
        if i & 1: par = f(par + f(1) / f(R1))
        if i & 2: par = f(par + f(1) / f(R2))
        if i & 4: par = f(par + f(1) / f(R3))
        if i & 8: par = f(par + f(1) / f(R4))
        if par:
            par = f(f(1) / par)
            pot[i] = f(f(f(pull) / f(f(pull) + par)) - potadjust)
    weight = []
    for i in range(16):
        w = int(f(f(f(255) * pot[i]) / pot[15]))          # truncation toward zero, then clamped at 0
        weight.append(max(w, 0))
    return weight


class Gfx:
    """Decoded characters (two sets of 512, 2 bits), sprites (128 of 16 x 16, 2 bits) and the 256 + 64 pens."""

    def __init__(self):
        step = lambda s, d, n: [s + d * i for i in range(n)]
        char = lambda a, b: decode_gfx(load(a) + load(b), 8, 8, (0, 0x1000 * 8), step(7, -1, 8), step(0, 8, 8), 64, 512)
        self.fg_chars = char("s8-09.bin", "u8-10.bin")       # gfx1: the foreground
        self.bg_chars = char("r8-08.bin", "n8-07.bin")       # gfx2: the background
        self.sprites = decode_gfx(load("h5-05.bin") + load("k5-06.bin"), 16, 16, (4, 0),
                                  step(3, -1, 4) + step(11, -1, 4) + step(19, -1, 4) + step(27, -1, 4),
                                  step(0, 32, 16), 64 * 8, 128)
        hi, lo, lut = load("u02--2.bin"), load("t02--3.bin"), load("f10--1.bin")
        w = palette_weights()
        colors = []
        for i in range(256):
            a1 = ((i >> 3) & 0x1c) + (i & 3)          # t02 (low bits)
            a2 = (i & 0x1c) + (i & 3)                 # u02 (high bits)
            comp = lambda s: w[((lo[a1] >> s) & 3) + (((hi[a2] >> s) & 3) << 2)]
            colors.append((comp(0), comp(2), comp(4)))
        self.colors = colors                          # the 256 indirect colours
        pens = list(range(256))                       # characters: pen i = colour i
        for i in range(64):                           # sprites: pens 256-319 through the lookup PROM
            e = lut[i & 0x1f]
            e = e >> 4 if i & 0x20 else e & 0x0f
            pens.append(e + ((e & 0x0c) << 3))
        self.pens = pens
        self.rgb = np.array([colors[p] for p in pens] + [(0, 0, 0)], np.uint8)    # 320 pens, index 320 black
        self.sprite_pen = np.array(pens[256:], np.uint16)


class MrDo:
    def __init__(self, dsw1=DSW1_DEFAULT, dsw2=DSW2_DEFAULT, frame_line=VBLANK_LINE):
        """frame_line: the line a frame starts at; 224 (the vertical blank) is MAME's phase, so render_raw after
        run_frame is MAME's picture of that frame."""
        self.frame_line = frame_line
        self.rom = b"".join(load(n) for n in PROGRAM)
        self.vram = bytearray(0x1000)        # 8000-8FFF
        self.spriteram = bytearray(0x100)    # 9000-90FF
        self.ram = bytearray(0x1000)         # E000-EFFF
        self.flip = 0
        self.scrollx = 0
        self.scrolly = 0
        self.p1 = 0xff
        self.p2 = 0xff
        self.dsw1 = dsw1
        self.dsw2 = dsw2
        self.cpu = Z80(self.rd8, self.wr8)
        self.cpu.afmask = 0xC1               # S Z C, as the translation keeps them
        self.irq_line = False
        self.frame = 0
        self.cycle0 = 0.0                    # the frame's start in CPU cycles (fractional frames)
        self.gfx = None
        self.sound_log = None                # a list to collect (frame, cycle, chip, value)
        self.io_log = []

    # ---- bus -----------------------------------------------------------
    def rd8(self, a):
        if a < 0x8000:
            return self.rom[a]
        if a < 0x9000:
            return self.vram[a - 0x8000]
        if a >= 0xE000:
            return self.ram[a - 0xE000] if a < 0xF000 else 0
        if a == 0x9803:
            hl = (self.cpu.h << 8) | self.cpu.l
            return self.rom[hl] if hl < 0x8000 else 0
        if 0xA000 <= a <= 0xA003:
            return (self.p1, self.p2, self.dsw1, self.dsw2)[a - 0xA000]
        return 0

    def wr8(self, a, v):
        if a < 0x8000:
            return
        if a < 0x9000:
            self.vram[a - 0x8000] = v
        elif a < 0x9100:
            self.spriteram[a - 0x9000] = v
        elif a >= 0xE000:
            if a < 0xF000:
                self.ram[a - 0xE000] = v
            elif a < 0xF800:
                self.scrollx = v
            else:
                self.scrolly = v
        elif a == 0x9800:
            self.flip = v & 1
        elif a in (0x9801, 0x9802):
            if self.sound_log is not None:
                self.sound_log.append((self.frame, self.cpu.cycles, a - 0x9801, v))
        else:
            self.io_log.append((self.frame, a, v))

    # ---- inputs --------------------------------------------------------
    def set_inputs(self, joy=0, fire=False, coin=False, start1=False, start2=False):
        """joy: LEFT / DOWN / RIGHT / UP bits pressed (active high here)."""
        self.p1 = 0xff & ~(joy | (FIRE if fire else 0) | (START1 if start1 else 0) | (START2 if start2 else 0))
        self.p2 = 0xff & ~(COIN1 if coin else 0)

    # ---- time ----------------------------------------------------------
    def run_frame(self):
        """One frame from line frame_line; the IRQ is raised at the vertical blank and held until taken."""
        cpu = self.cpu
        start = self.cycle0
        vbl = start + ((VBLANK_LINE - self.frame_line) % LINES) * CYCLES_PER_LINE
        end = start + CYCLES_PER_FRAME
        raised = False
        while cpu.cycles < end:
            if not raised and cpu.cycles >= vbl:
                raised = True
                self.irq_line = True
            if self.irq_line and cpu.iff1:
                cpu.irq()
                self.irq_line = False
            cpu.step()
        self.cycle0 = end
        self.frame += 1

    # ---- rendering -----------------------------------------------------
    def layer(self, base, chars):
        """a 256 x 256 tilemap (pens, and the opaque mask) from video RAM at base"""
        v = self.vram
        attr = np.frombuffer(bytes(v[base:base + 0x400]), np.uint8).astype(np.int32)
        code = np.frombuffer(bytes(v[base + 0x400:base + 0x800]), np.uint8).astype(np.int32) + ((attr & 0x80) << 1)
        tiles = chars[code]                                   # [1024][8][8]
        pens = tiles.astype(np.uint16) + ((attr & 0x3f) * 4)[:, None, None].astype(np.uint16)
        opaque = (tiles != 0) | ((attr & 0x40) != 0)[:, None, None]
        pens = pens.reshape(32, 32, 8, 8).transpose(0, 2, 1, 3).reshape(256, 256)
        opaque = opaque.reshape(32, 32, 8, 8).transpose(0, 2, 1, 3).reshape(256, 256)
        return pens, opaque

    def render_raw(self):
        """the 256 x 256 raw bitmap of pens (0-319) as MAME's before the rotation; the visible part is
        [VIS_Y0:VIS_Y1, VIS_X0:VIS_X1].  Upright only (the flip screen is not drawn)."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        bmp = np.zeros((256, 256), np.uint16)
        pens, opaque = self.layer(0x000, g.bg_chars)
        pens = np.roll(pens, (-self.scrolly, -self.scrollx), (0, 1))
        opaque = np.roll(opaque, (-self.scrolly, -self.scrollx), (0, 1))
        bmp[opaque] = pens[opaque]
        pens, opaque = self.layer(0x800, g.fg_chars)
        bmp[opaque] = pens[opaque]
        sr = self.spriteram
        for offs in range(0xfc, -4, -4):
            if sr[offs + 1] == 0:
                continue
            attr = sr[offs + 2]
            tile = g.sprites[sr[offs] & 0x7f]
            if attr & 0x10:
                tile = tile[:, ::-1]
            if attr & 0x20:
                tile = tile[::-1, :]
            sx, sy = sr[offs + 3], 256 - sr[offs + 1]
            x0, x1 = max(sx, VIS_X0), min(sx + 16, VIS_X1)
            y0, y1 = max(sy, VIS_Y0), min(sy + 16, VIS_Y1)
            if x0 >= x1 or y0 >= y1:
                continue
            sub = tile[y0 - sy:y1 - sy, x0 - sx:x1 - sx]
            m = sub != 0
            blk = bmp[y0:y1, x0:x1]
            blk[m] = 256 + (attr & 0x0f) * 4 + sub[m].astype(np.uint16)
        return bmp

    def render_rgb(self):
        """the visible picture as MAME shows it: ROT270, 192 wide, 240 tall"""
        bmp = self.render_raw()[VIS_Y0:VIS_Y1, VIS_X0:VIS_X1]
        rgb = self.gfx.rgb[bmp]                    # [192][240][3]
        return np.ascontiguousarray(rgb.transpose(1, 0, 2)[::-1, :])    # ROT270: raw x 247 at the top


class MrDoPort(MrDo):
    """The STE runtime's schedule (src/mrdo.s), one call of run_frame_port an arcade frame.

    All the game runs from the IRQ (RST 38, $00B8): the objects, the sound, the screen.  Its end looks at $E001: bit 0
    restarts the maze search (54EC, which runs on into 558E and 5647) on a fresh stack at $0138, bit 2 runs the search
    558E at $0141 and returns to the interrupted code through the IRQ's saved registers, bit 4 restarts the search 5647
    at $014D; bits 1 / 3 (a search runs) return to it.  The searches run with interrupts enabled; on the arcade the
    next IRQ cuts into them (about 75 frames in 4000 of attract and play: they take up to 0.9 frame each).  The
    foreground otherwise spins at $00AC (after the boot) or $0154 (after a search): the idle hooks.

    Here the IRQ is delivered only at a hook: TOKEN pushed as the interrupted pc, $0038 entered; the handler runs to
    its return (to TOKEN: the foreground goes on at the hook) or to a search, which runs to its end at a hook.  So a
    search never sees an IRQ in its middle (the arcade's restart of a running search cannot happen) and a frame whose
    search overruns the arcade's frame is a longer one.  Without input on the hook nothing else differs."""
    HOOKS = (0x00AC, 0x0154)
    TOKEN = 0xFFFE              # (no code there: the dispatch maps it to the runtime's return)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.booted = False
        self.irq_count = 0
        self.idle_pc = None

    def run_to_idle(self, limit=20_000_000):
        """the foreground (at least one instruction) until it reaches a hook"""
        c = self.cpu
        hooks = self.HOOKS
        for _ in range(limit):
            c.step()
            if c.pc in hooks:
                self.idle_pc = c.pc
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.run_to_idle()                    # the boot to its spin at $00AC
            self.booted = True
        if c.iff1:
            c.iff1 = c.iff2 = 0
            c.halted = False
            c.push(self.TOKEN)
            c.pc = 0x38
            hooks = self.HOOKS
            for _ in range(20_000_000):
                c.step()
                if c.pc == self.TOKEN:
                    c.pc = self.idle_pc
                    self.run_to_idle()
                    break
                if c.pc in hooks:                 # (a search started by the handler ended)
                    self.idle_pc = c.pc
                    break
            else:
                raise RuntimeError('the interrupt did not return (frame %d)' % self.frame)
            self.irq_count += 1
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
    out = sys.argv[2] if len(sys.argv) > 2 else "mrdo.png"
    m = MrDo()
    t0 = time.time()
    for f in range(frames):
        m.run_frame()
        if f % 120 == 0:
            print("frame", f, "pc %04X" % m.cpu.pc, "scroll %02X %02X" % (m.scrollx, m.scrolly))
    print("%.1f s, %.1f frames/s" % (time.time() - t0, frames / (time.time() - t0)))
    print("other writes:", m.io_log[:10])
    save_png(m.render_rgb(), out)
    print("wrote", out)
