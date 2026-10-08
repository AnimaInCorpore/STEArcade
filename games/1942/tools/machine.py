"""1942 (Capcom 1984, Revision B) arcade machine model around the reference Z80.

MAME capcom/1942.cpp, main CPU (the sound CPU is not modelled: no sound, and the main CPU never reads it back):
  0000-7FFF ROM, 8000-BFFF ROM bank (4 x 16 KB, selected by C806 bits 0-1; bank 3 is empty = FF)
  C000-C004 SYSTEM, P1, P2, DSWA, DSWB (read)
  C800 sound command, C802-C803 background scroll x, C804 control (bit 7 flip, bit 4 sound CPU reset, bit 0 coin counter),
  C805 background palette bank, C806 ROM bank
  CC00-CC7F sprites (32 x 4 bytes), D000-D3FF character codes, D400-D7FF character attributes,
  D800-DBFF background (32 columns x 32 bytes: 16 codes, 16 attributes), E000-EFFF RAM
Interrupts (IM 0, RST vector from the device): the scanline PROM sb-1.k6 raises RST 08 at line 109 and RST 10 at line 240
(the vertical blank) of a 262 line frame, HOLD_LINE (pending until the CPU takes it).  3 MHz = 192 cycles a line.

Reference renderer: `render_raw` gives the 256 x 256 raw bitmap of palette indices (background 16 x 16 tiles scrolled in x,
sprites with the per scanline object logic of MAME's draw_sprites, characters on top); the screen is rows 16-239 rotated 270.
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "1942")

CYCLES_PER_LINE = 192
LINES = 262
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES      # 50304, 59.6 Hz


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def main_rom():
    """The 128 KB image of MAME's maincpu region: fixed ROM at 0, the banks at 10000 (unused space is FF)."""
    img = bytearray(b"\xff" * 0x20000)
    for off, name in ((0x00000, "srb-03.m3"), (0x04000, "srb-04.m4"), (0x10000, "srb-05.m5"),
                      (0x14000, "srb-06.m6"), (0x18000, "srb-07.m7")):
        d = load(name)
        img[off:off + len(d)] = d
    return img


def decode_gfx(data, width, height, planes, xoffs, yoffs, size, count=None):
    """MAME gfx layout decode (bit offsets count from the MSB of each byte, the first plane is the most significant
    bit of the pixel).  planes/xoffs/yoffs in bits, size = bits per object."""
    bits = np.unpackbits(np.frombuffer(bytes(data), np.uint8))
    n = count if count else len(data) * 8 // size
    base = (np.arange(n, dtype=np.int64) * size)[:, None, None]
    xo = np.array(xoffs, np.int64)[None, None, :]
    yo = np.array(yoffs, np.int64)[None, :, None]
    out = np.zeros((n, height, width), np.uint8)
    for p, po in enumerate(planes):
        out |= bits[base + po + xo + yo] << (len(planes) - 1 - p)
    return out


def rgb_of(r4, g4, b4):
    def comp(v):
        return 0x0e * (v & 1) + 0x1f * ((v >> 1) & 1) + 0x43 * ((v >> 2) & 1) + 0x8f * ((v >> 3) & 1)
    return comp(r4), comp(g4), comp(b4)


class Gfx:
    """Decoded characters (512 x 8x8, 2 bit), background tiles (512 x 16x16, 3 bit), sprites (512 x 16x16, 4 bit),
    and the pens: 256 palette entries (PROM resistor weights) behind the three lookup tables."""

    def __init__(self):
        g1 = load("sr-02.f2")
        self.chars = decode_gfx(g1, 8, 8, (4, 0), [0, 1, 2, 3, 8, 9, 10, 11], [16 * y for y in range(8)], 16 * 8)
        g2 = b"".join(load(n) for n in ("sr-08.a1", "sr-09.a2", "sr-10.a3", "sr-11.a4", "sr-12.a5", "sr-13.a6"))
        third = len(g2) // 3 * 8
        self.tiles = decode_gfx(g2, 16, 16, (0, third, 2 * third), list(range(8)) + [16 * 8 + i for i in range(8)],
                                [8 * y for y in range(16)], 32 * 8, third // (32 * 8))
        g3 = b"".join(load(n) for n in ("sr-14.l1", "sr-15.l2", "sr-16.n1", "sr-17.n2"))
        half = len(g3) // 2 * 8
        xo = [0, 1, 2, 3, 8, 9, 10, 11, 256, 257, 258, 259, 264, 265, 266, 267]
        self.sprites = decode_gfx(g3, 16, 16, (half + 4, half, 4, 0), xo, [16 * y for y in range(16)], 64 * 8, half // (64 * 8))
        pr, pg, pb = load("sb-5.e8"), load("sb-6.e9"), load("sb-7.e10")
        self.palette = [rgb_of(pr[i] & 15, pg[i] & 15, pb[i] & 15) for i in range(256)]
        self.char_lut = [0x80 | (v & 15) for v in load("sb-0.f1")]                 # colour*4+pen -> palette entry
        tl = [v & 15 for v in load("sb-4.d6")]
        self.tile_lut = [[(b << 4) | tl[i] for i in range(256)] for b in range(4)]   # [bank][colour*8+pen]
        self.sprite_lut = [0x40 | (v & 15) for v in load("sb-8.k3")]               # colour*16+pen
        self.rgb = np.array(self.palette, np.uint8)


class Machine1942:
    def __init__(self):
        self.rom = main_rom()
        self.ram = bytearray(0x1000)           # E000-EFFF
        self.sprram = bytearray(0x80)          # CC00-CC7F
        self.fg = bytearray(0x800)             # D000-D7FF (codes, attributes)
        self.bg = bytearray(0x400)             # D800-DBFF
        self.irqprom = load("sb-1.k6")
        self.sys_in = 0xFF
        self.p1 = 0xFF
        self.p2 = 0xFF
        self.dswa = 0xF7                       # upright, 20K 80K 80K+, 3 lives, 1 coin 1 credit
        self.dswb = 0xFF                       # normal, no freeze, no flip
        self.scroll = [0, 0]
        self.palette_bank = 0
        self.bank = 0
        self.control = 0
        self.latch = 0
        self.latch_log = []
        self.pending = []                      # vectors of the interrupts being held
        self.cpu = Z80(self.rd8, self.wr8)
        self.cpu.afmask = 0xC1
        self.cpu.im = 0
        self.frame = 0
        self.line = 0
        self.gfx = None
        self.booted = False
        self.io_log = []
        self.watch_hook = None

    # ---- bus -----------------------------------------------------------
    def rd8(self, a):
        if a < 0x8000:
            return self.rom[a]
        if a < 0xC000:
            return self.rom[0x10000 + self.bank * 0x4000 + a - 0x8000]
        if a >= 0xE000:
            return self.ram[a - 0xE000] if a < 0xF000 else 0xFF
        if a < 0xC005:
            return (self.sys_in, self.p1, self.p2, self.dswa, self.dswb)[a - 0xC000]
        if 0xCC00 <= a < 0xCC80:
            return self.sprram[a - 0xCC00]
        if 0xD000 <= a < 0xD800:
            return self.fg[a - 0xD000]
        if 0xD800 <= a < 0xDC00:
            return self.bg[a - 0xD800]
        return 0xFF

    def wr8(self, a, v):
        if a >= 0xE000:
            if a < 0xF000:
                self.ram[a - 0xE000] = v
            return
        if a < 0xC000:
            return
        if a < 0xCC00:
            if a == 0xC800:
                self.latch = v
                self.latch_log.append((self.frame, v))
            elif a == 0xC802 or a == 0xC803:
                self.scroll[a - 0xC802] = v
            elif a == 0xC804:
                self.control = v
            elif a == 0xC805:
                self.palette_bank = v & 3
            elif a == 0xC806:
                self.bank = v & 3
            return
        if a < 0xCC80:
            self.sprram[a - 0xCC00] = v
        elif 0xD000 <= a < 0xD800:
            self.fg[a - 0xD000] = v
        elif 0xD800 <= a < 0xDC00:
            self.bg[a - 0xD800] = v

    @property
    def flip(self):
        return self.control >> 7

    @property
    def scrollx(self):
        return self.scroll[0] | (self.scroll[1] << 8)

    # ---- running -------------------------------------------------------
    def take_irq(self):
        """HOLD_LINE: the oldest held interrupt is taken when the CPU has interrupts enabled."""
        c = self.cpu
        if self.pending and c.iff1:
            vec = self.pending.pop(0)
            c.halted = False
            c.iff1 = c.iff2 = 0
            c.push(c.pc)
            c.pc = vec & 0x38
            c.cycles += 13
            return True
        return False

    def step(self):
        c = self.cpu
        if self.pending and not c.ei_delay:
            self.take_irq()
        c.step()
        if c.ei_delay:
            if c.iff1 and self.pending:      # the instruction after EI runs first
                c.step()
            c.ei_delay = False

    def run_frame(self):
        """One frame in real time: 262 lines of 192 cycles, the interrupts from the PROM at the line starts."""
        c = self.cpu
        for line in range(LINES):
            self.line = line
            irq = self.irqprom[line & 0xFF]
            if irq & 8:
                self.pending.append(0xC7 | ((irq << 3) & 0x18))
            target = c.cycles + CYCLES_PER_LINE
            while c.cycles < target:
                self.step()
            if self.watch_hook:
                self.watch_hook(self, line)
        self.frame += 1

    IDLE_PC = 0x009A          # the scheduler's scan found no ready task (jr $0087): the foreground has nothing to do
    IRQ_VECTORS = (0xCF, 0xD7)  # RST 08 (line 109), RST 10 (vertical blank)

    def run_to_idle(self, limit=2000000):
        """Foreground until the scheduler's idle scan finds no ready task (interrupts stay enabled and
        are not taken: port mode delivers them itself)."""
        c = self.cpu
        n = 0
        while c.pc != self.IDLE_PC:
            c.step()
            n += 1
            assert n < limit, "foreground does not reach the idle loop (pc %04X)" % c.pc
        return n

    def deliver(self, vec):
        """The device supplies RST vec; taken when the CPU has interrupts enabled (the idle loop has: `ei` at 0087)."""
        c = self.cpu
        assert c.iff1, "interrupts are disabled at the idle point"
        c.iff1 = c.iff2 = 0
        c.push(self.TOKEN)
        c.pc = vec & 0x38

    TOKEN = 0xBFFE            # what the runtime pushes as the interrupt's return address (never a real address)

    def run_frame_port(self):
        """The runtime's schedule: the interrupts of the frame (RST 08, RST 10) run to completion at the foreground's idle
        point, then the foreground (tasks woken by them) runs until idle again.  A handler that hands the CPU to another
        task (the scheduler's `jp $0084`) ends there: the handler's frame is dropped, the stack is reset by the scheduler."""
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        for vec in self.IRQ_VECTORS:
            self.deliver(vec)
            n = 0
            while True:
                c.step()
                n += 1
                assert n < 2000000
                if c.pc == self.TOKEN:                  # the handler returned (to the idle point)
                    c.pc = self.IDLE_PC
                    break
                if c.pc == self.IDLE_PC:                # the handler handed the CPU over: the idle loop again
                    break
        self.run_to_idle()
        self.frame += 1

    # ---- rendering -----------------------------------------------------
    def render_raw(self):
        """256 x 256 bitmap of palette indices (row = raw y, column = raw x)."""
        assert not self.flip, "flip screen is not modelled"
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        bmp = np.zeros((256, 256), np.uint8)
        # background: 32 x 16 tiles of 16 x 16, column major attribute layout, scrolled in x over 512 pixels
        wide = np.zeros((256, 512), np.uint8)
        lut = g.tile_lut[self.palette_bank]
        for col in range(32):
            for row in range(16):
                off = row | (col << 5)
                code = self.bg[off]
                attr = self.bg[off + 0x10]
                t = g.tiles[code + ((attr & 0x80) << 1)]
                if attr & 0x20:
                    t = t[:, ::-1]
                if attr & 0x40:
                    t = t[::-1, :]
                base = (attr & 0x1F) * 8
                m = np.array([lut[base + p] for p in range(8)], np.uint8)
                wide[row * 16:row * 16 + 16, col * 16:col * 16 + 16] = m[t]
        sx = self.scrollx & 0x1FF
        bmp[:, :] = np.roll(wide, -sx, axis=1)[:, :256]
        # sprites, line by line as the hardware fetches them
        self.draw_sprites(bmp)
        # characters
        for idx in range(1024):
            code = self.fg[idx]
            attr = self.fg[idx + 0x400]
            ch = g.chars[code + ((attr & 0x80) << 1)]
            base = (attr & 0x3F) * 4
            m = np.array([0] + [g.char_lut[base + p] for p in (1, 2, 3)], np.uint8)
            r, c = divmod(idx, 32)
            tgt = bmp[r * 8:r * 8 + 8, c * 8:c * 8 + 8]
            tgt[ch != 0] = m[ch][ch != 0]
        return bmp

    def sprite_list(self):
        return [tuple(self.sprram[i * 4:i * 4 + 4]) for i in range(32)]

    def draw_sprites(self, bmp):
        """MAME 1942_v.cpp draw_sprites for flip off: per scanline the 24 slots h = 496 .. 128 (step 16) fetch an
        object (sprites 0-15 always, 16-23 while v bit 7 is 0, else 24-31) and decide with the vertical comparator
        whether the line is inside it; the parts of such an object are drawn clipped to the line (opaque pixels of
        later slots, i.e. lower slot numbers, win)."""
        g = self.gfx
        sp = self.sprite_list()
        for y in range(16, 240):
            v = (y - 1) & 0xFF
            for h in range(496, 127, -16):
                b8, b7 = (h >> 8) & 1, (h >> 7) & 1
                objcnt4 = b8 != (b7 ^ 1)
                objcnt3 = (((v >> 7) & 1) and objcnt4) != (b7 ^ 1)
                idx = ((h >> 4) & 7) | (8 if objcnt3 else 0) | (16 if objcnt4 else 0)
                d0, d1, d2, d3 = sp[idx]
                valpha = d2
                v2c = ((~v) & 0xFF) + 0xFF & 0xFF
                lvbeta = (v2c + valpha) & 0xFF
                vbeta = (~lvbeta) & 0xFF
                vleq = vbeta <= ((~valpha) & 0xFF)
                vlen = d1 >> 6
                if vlen == 0:
                    vinlen = (lvbeta >> 4) == 0xF
                elif vlen == 1:
                    vinlen = (lvbeta >> 5) == 7
                elif vlen == 2:
                    vinlen = (lvbeta >> 6) == 3
                else:
                    vinlen = True
                if not (vleq and vinlen):
                    continue
                code = (d0 & 0x7F) + ((d1 & 0x20) << 2) + ((d0 & 0x80) << 1)
                col = d1 & 0x0F
                sx = d3 - 0x10 * (d1 & 0x10)
                n = (d1 & 0xC0) >> 6
                if n == 2:
                    n = 3
                while True:
                    top = d2 + 16 * n
                    row = y - top
                    if 0 <= row < 16:
                        s = g.sprites[code + n][row]
                        for x in range(16):
                            p = s[x]
                            xx = sx + x
                            if p != 15 and 0 <= xx < 256:
                                bmp[y, xx] = g.sprite_lut[col * 16 + p]
                    if n == 0:
                        break
                    n -= 1

    def render_rgb(self):
        """The 224 x 256 screen: raw rows 16-239 rotated 270 (screen row = 255 - raw x, screen column = raw y - 16)."""
        bmp = self.render_raw()
        rgb = self.gfx.rgb[bmp]                 # [y][x][3]
        arr = rgb[16:240, :, :]                 # [y-16][x]
        return arr.transpose(1, 0, 2)[::-1]       # [255-x][y-16], as Donkey Kong (ROT270)


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)


if __name__ == "__main__":
    import time
    m = Machine1942()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    t = time.time()
    for i in range(n):
        m.run_frame()
    print("frames", n, "pc %04X" % m.cpu.pc, "%.1fs" % (time.time() - t))
