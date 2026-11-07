"""Super Basketball (MAME `sbasketb`, Konami GX405, 1984): the reference board, from MAME konami/sbasketb.cpp.

Main CPU: KONAMI-1 (MC6809E, opcodes encrypted, engine/m6809.py with konami1_opcode) at 18.432 MHz / 12 = 1.536 MHz.
Screen: 60 Hz, 256 x 256 total (no raw timing), 256 x 224 visible (lines 16-239) in the machine's own orientation;
the monitor is rotated (ROT90): MAME's snapshot and the STE picture are 224 wide, 256 high.  25600 CPU cycles a
frame, 100 a line.  The VBLANK (line 240) asserts IRQ (HOLD_LINE) while the LS259 latch's Q1 (INTST) is 1; clearing
Q1 clears the line.  No NMI, no FIRQ.

Memory map (main CPU, no mirrors):
    $2000-$2FFF RAM    $3000-$33FF colour RAM    $3400-$37FF video RAM    $3800-$39FF sprite RAM (two banks of 64 x 4)
    $3A00-$3BFF RAM (unused)    $3C00 w watchdog    $3C10 r (nop)    $3C20 w sprite palette bank
    $3C80-$3C87 w LS259 latch (bit 0 of the data): Q0 flip screen, Q1 IRQ enable, Q3/Q4 coin counters,
                Q5 sprite RAM bank (OBJ CHE)
    $3D00 w sound latch    $3D80 w sound IRQ trigger    $3E00 r SYSTEM  $3E01 r P1  $3E02 r P2    $3E80 r DSW2
    $3F00 r DSW1    $3F80 w column scroll    $6000-$FFFF ROM; anything else reads 0 (MAME's unmapped value)
Sound: a Z80 with an SN76489A, a VLM5030 and a DAC behind the latch (the Track & Field / Hyper Sports board); the main
CPU only writes the latch and the trigger, so it is not emulated here: sound_log keeps (frame, latch value) at each
trigger write.

Video: a 32 x 32 tilemap of 8x8 4bpp tiles (512), the columns 6-31 scrolled in y by $3F80 (columns 0-5 fixed: the
scoreboard); 64 sprites 16x16 4bpp (384 in ROM), in RAM order (the last on top), bank $3800 or $3900, none where x
and y are both 0.  Colours: three 256x4 palette PROMs (a 2k / 1k / 470 / 220 ohm network per gun) as indirect colours,
tiles through one lookup PROM (pens 0-255 -> entries $F0-$FF), sprites through the other with the palette bank in the
high nibble (4096 pens); a sprite pixel with the raw value 0 is transparent.
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
VISIBLE = (0, 255, 16, 239)                # MAME's visible area in the native orientation (x, y)

# MAME's defaults: DSW1 1 coin 1 credit both slots; DSW2 60 s game time, upright, starting score 100-115, the
# ranking data remains, easy ($60), demo sounds on
DSW1, DSW2 = 0xFF, 0x60

ROM_FILES = (("405g05.14j", 0x6000), ("405i03.11j", 0x8000), ("405i01.9j", 0xC000))


def load(name):
    return (EXTRACTED / "sbasketb" / name).read_bytes()


def prom_pens():
    """The 4352 pens' RGB: tiles 0-255 -> palette entry (lookup & 15) | $F0; sprites $100 + (bank << 8 | colour << 4 |
    pixel) -> entry bank << 4 | (lookup2 & 15)."""
    prom = load("405e17.5a") + load("405e16.4a") + load("405e18.6a") + load("405e20.19d") + load("405e19.16d")
    nets = ([2000, 1000, 470, 220], 1000, 0)
    rw, gw, bw = G.resistor_weights(0, 255, -1.0, nets, nets, nets)
    pal = np.zeros((256, 3), np.uint8)
    for i in range(256):
        for g, w in enumerate((rw, gw, bw)):
            v = prom[i + 0x100 * g]
            pal[i, g] = G.combine(w, *[(v >> k) & 1 for k in range(4)])
    idx = [(prom[0x300 + i] & 15) | 0xF0 for i in range(256)]
    for j in range(16):
        idx += [(j << 4) | (prom[0x400 + i] & 15) for i in range(256)]
    return pal[idx]


class Video:
    def __init__(self):
        gfx_t, gfx_s = load("405e12.22f"), load("405h06.14g") + load("405h08.17g") + load("405h10.20g")
        self.tiles = G.decode_gfx(gfx_t, 8, 8, len(gfx_t) // 32, [0, 1, 2, 3], list(range(0, 32, 4)),
                                  list(range(0, 256, 32)), 256)
        self.sprites = G.decode_gfx(gfx_s, 16, 16, len(gfx_s) // 128, [0, 1, 2, 3], list(range(0, 64, 4)),
                                    list(range(0, 1024, 64)), 1024).astype(np.int32)
        self.pens = prom_pens()

    def render_raw(self, mem, flip=False, select=0, pbank=None):
        """The native bitmap's pens [256 rows, 256] (rows 16-239 visible) from the main CPU's memory (64 KB image)."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        vram = np.frombuffer(bytes(mem[0x3400:0x3800]), np.uint8).reshape(32, 32)
        cram = np.frombuffer(bytes(mem[0x3000:0x3400]), np.uint8).reshape(32, 32)
        codes = vram.astype(np.int32) + ((cram & 0x20).astype(np.int32) << 3)
        pix, _ = G.tile_pixmap(self.tiles, codes, cram & 15, cram & 0x40, cram & 0x80, 32, 32, 0, 16)
        ys = (np.arange(256) + mem[0x3F80]) % 256
        bm = np.empty((256, 256), np.int32)
        bm[:, :48] = pix[:, :48]
        bm[:, 48:] = pix[ys, 48:]
        pb = mem[0x3C20] if pbank is None else pbank
        offs = 0x3800 + (0x100 if select else 0)
        for i in range(64):
            o = offs + 4 * i
            sx, sy = mem[o + 2], mem[o + 3]
            if sx or sy:
                at = mem[o + 1]
                code = mem[o] | ((at & 0x20) << 3)
                color = (at & 15) + 16 * pb
                G.draw_gfx(bm, VISIBLE, self.sprites, code, 0x100 + color * 16, at & 0x40, at & 0x80, sx, sy,
                           lambda s: s == 0)
        return bm

    def render_rgb(self, mem, flip=False, **kw):
        """The visible picture [256, 224, 3] as MAME's (ROT90) snapshot shows it."""
        raw = self.render_raw(mem, flip, **kw)[VISIBLE[2]:VISIBLE[3] + 1]
        return np.ascontiguousarray(np.rot90(self.pens[raw], -1))


class SBasket:
    def __init__(self, dsw1=DSW1, dsw2=DSW2, hz=CPU_HZ):
        self.hz = hz                               # (WolfMAME 0.248 runs the board's CPU at 1.4 MHz: see ref/mame_cmp)
        rom = bytearray(0x10000)
        for n, a in ROM_FILES:
            d = load(n)
            rom[a:a + len(d)] = d
        self.rom = bytes(rom)
        self.mem = bytearray(0x10000)              # RAM areas (and the ROM copy, for render/compare convenience)
        self.mem[0x6000:] = self.rom[0x6000:]
        self.system = self.p1 = self.p2 = 0xFF
        self.dsw1, self.dsw2 = dsw1, dsw2
        self.latch = [0] * 8
        self.sound_latch = 0
        self.sound_log = []
        self.watchdog = 0
        self.frame = 0
        self.cpu = M6809(self.rd, self.wr, konami1_opcode(self.rd))
        self.video = None
        self.cpu.reset()
        self.next_vblank = self.vblank(0)

    def vblank(self, k):
        """the CPU cycle of frame k's VBLANK (line 240 of 256 of each 1/60 s)"""
        return (k * LINES + VBLANK_LINE) * self.hz // (60 * LINES)

    def rd(self, a):
        if a >= 0x6000 or 0x2000 <= a < 0x3C00:
            return self.mem[a]
        if a == 0x3E00: return self.system
        if a == 0x3E01: return self.p1
        if a == 0x3E02: return self.p2
        if a == 0x3E80: return self.dsw2
        if a == 0x3F00: return self.dsw1
        return 0

    def wr(self, a, v):
        if 0x2000 <= a < 0x3C00:
            self.mem[a] = v
        elif a == 0x3C00:
            self.watchdog += 1
        elif a == 0x3C20 or a == 0x3F80:
            self.mem[a] = v
        elif 0x3C80 <= a < 0x3C88:
            q, b = a & 7, v & 1
            self.latch[q] = b
            if q == 1 and not b:
                self.cpu.set_irq(False)
        elif a == 0x3D00:
            self.sound_latch = v
        elif a == 0x3D80:
            self.sound_log.append((self.frame, self.sound_latch))

    def run_frame(self):
        """Runs to the next VBLANK and starts it (IRQ when enabled): the state MAME's frame_done callback sees."""
        c = self.cpu
        c.run(self.next_vblank - c.cycles)
        if self.latch[1]:
            c.set_irq(True)
        self.frame += 1
        self.next_vblank = self.vblank(self.frame)

    def render_rgb(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, bool(self.latch[0]), select=self.latch[5])


if __name__ == "__main__":
    import time
    m = SBasket()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, sound commands %d" % (time.time() - t, m.cpu.pc, len(m.sound_log)))
