"""Roc'n Rope (MAME `rocnrope`, Konami KT-A207, 1983): the reference board, from MAME konami/rocnrope.cpp.

Main CPU: KONAMI-1 (MC6809E, opcodes encrypted, engine/m6809.py with konami1_opcode) at 18.432 MHz / 12 = 1.536 MHz.
Screen: 256 x 256 total, 256 x 224 visible (lines 16-239), 60 Hz, ROT270 (MAME's snapshot is 224 wide, 256 high): a
frame is 25600 CPU cycles, a line 100.  The VBLANK (line 240) asserts IRQ while latch Q7 is 1; writing Q7 0 clears it.
No NMI, no FIRQ.  The IRQ vector is in RAM ($FFF2-$FFFD, written through $8182-$818D; the ROM has $FFFF there).

Memory map (main CPU):
    $3000 r DSW2   $3080 SYSTEM  $3081 P1  $3082 P2  $3083 DSW1   $3100 r DSW3
    $4000-$402F sprite RAM 1 (attribute, y)   $4400-$442F sprite RAM 0 (x, code)   $4000-$5FFF RAM (all of it)
    $4800-$4BFF colour RAM, $4C00-$4FFF video RAM (32 x 32 tilemap)
    $8000 w watchdog, $8080-$8087 w LS259 latch (bit 0 of the data: Q0 flip screen (inverted), Q1 sound IRQ trigger,
    Q2 sound mute, Q3/Q4 coin counters, Q7 IRQ enable), $8100 w sound command, $6000-$FFFF ROM
    (MAME's driver init patches the byte at $703D: raw 0x98 ^ 0x22); anything else reads 0.
Sound: a Z80 with two AY-3-8910s (Time Pilot's board) behind the command latch; the main CPU only writes (the command
and the trigger, Q1 rising), so it is not emulated here: sound_log keeps (frame, command) at each trigger.

Video: a 32 x 32 tilemap of 8x8 4bpp tiles (code = video byte + 256 x colour bit 7, colour bits 0-3, bit 6 flip x,
bit 5 flip y); 24 sprites 16x16 4bpp (256), drawn from the last entry to the first (the first on top): x = 240 -
RAM0[offs], y = RAM1[offs + 1], flip x = attribute bit 6, flip y = NOT attribute bit 7.  Colours: a 32-entry palette PROM
(3-3-2 resistor network, only entries 0-15 are used), 16 sprite and 16 tile colour sets of 16 pens through two 256x4
lookup PROMs (pens 0-255 sprites, 256-511 tiles; the lookup value is the palette entry).  Sprite lookup 0 = transparent.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809, konami1_opcode
import mamegfx as G

CPU_HZ = 1536000
LINE = 100                                 # CPU cycles a line
LINES = 256
FRAME = LINE * LINES                       # 25600
VBLANK_LINE = 240
VISIBLE = (0, 255, 16, 239)                # MAME's visible area (min_x, max_x, min_y, max_y)

# MAME's defaults: DSW1 1 coin 1 credit ($FF), DSW2 3 lives, upright, difficulty 5, demo sounds on ($5B),
# DSW3 first bonus 20000, repeated 60000, granted ($96)
DSW1, DSW2, DSW3 = 0xFF, 0x5B, 0x96


def load(name):
    return (EXTRACTED / "rocnrope" / name).read_bytes()


def konami_pens(prom, rg_pulldown=1000):
    """The 512 pens' RGB: palette PROM bits 0-2 red, 3-5 green (1k, 470, 220 ohm), 6-7 blue (470, 220); the lookup
    PROMs at $20 (sprites) and $120 (tiles) give the palette entry (low 4 bits)."""
    rw, gw, bw = G.resistor_weights(0, 255, -1.0, ([1000, 470, 220], rg_pulldown, 0), ([1000, 470, 220], rg_pulldown, 0),
                                    ([470, 220], rg_pulldown, 0))
    pal = []
    for i in range(32):
        v = prom[i]
        bit = [(v >> k) & 1 for k in range(8)]
        pal.append((G.combine(rw, *bit[0:3]), G.combine(gw, *bit[3:6]), G.combine(bw, *bit[6:8])))
    pal = np.array(pal, np.uint8)
    idx = [prom[0x20 + i] & 15 for i in range(256)] + [prom[0x120 + i] & 15 for i in range(256)]
    return pal[idx]


def rom_image():
    rom = bytearray(0x10000)
    for i, n in enumerate(("rr1.1h", "rr2.2h", "rr3.3h", "rr4.4h", "rnr_h5.vid")):
        rom[0x6000 + i * 0x2000:0x8000 + i * 0x2000] = load(n)
    rom[0x703D] = 0x98 ^ 0x22                  # MAME init_rocnrope: "fix one instruction"
    return bytes(rom)


class Video:
    def __init__(self):
        prom = load("a17_prom.bin") + load("b16_prom.bin") + load("rocnrope.pr3")
        gfx0 = b"".join(load(n) for n in ("rnr_a11.vid", "rnr_a12.vid", "rnr_a9.vid", "rnr_a10.vid"))
        gfx1 = load("rnr_h12.vid") + load("rnr_h11.vid")
        sx = [0, 1, 2, 3, 64, 65, 66, 67, 128, 129, 130, 131, 192, 193, 194, 195]
        sy = list(range(0, 64, 8)) + list(range(256, 320, 8))
        self.sprites = G.decode_gfx(gfx0, 16, 16, 256, [256 * 64 * 8 + 4, 256 * 64 * 8, 4, 0], sx, sy, 512)
        self.tiles = G.decode_gfx(gfx1, 8, 8, 512, [0x2000 * 8 + 4, 0x2000 * 8, 4, 0], sx[:8], list(range(0, 64, 8)), 128)
        self.pens = konami_pens(prom)
        self.lut = np.array([prom[0x20 + i] & 15 for i in range(256)] + [prom[0x120 + i] & 15 for i in range(256)], np.uint8)

    def render_raw(self, mem, flip=False):
        """The screen's pens [256 rows, 256] (rows 16-239 visible; unrotated) from the main CPU's memory (64 KB image)."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        cram = np.frombuffer(bytes(mem[0x4800:0x4C00]), np.uint8).reshape(32, 32)
        vram = np.frombuffer(bytes(mem[0x4C00:0x5000]), np.uint8).reshape(32, 32).astype(np.int32)
        codes = vram + 2 * (cram & 0x80).astype(np.int32)
        bm, _ = G.tile_pixmap(self.tiles, codes, cram & 15, cram & 0x40, cram & 0x20, 32, 32, 256, 16)
        bm = bm.astype(np.int16)
        r1, r0 = mem[0x4000:0x4030], mem[0x4400:0x4430]
        lut = self.lut
        for offs in range(0x2E, -1, -2):
            attr = r1[offs]
            color = attr & 15
            trans = lut[color * 16:color * 16 + 16] == 0
            G.draw_gfx(bm, VISIBLE, self.sprites, int(r0[offs + 1]), color * 16, attr & 0x40, not attr & 0x80,
                       240 - int(r0[offs]), int(r1[offs + 1]), lambda s: trans[s])
        return bm

    def render_rgb(self, mem, flip=False, rotate=True):
        """The visible picture as MAME's snapshot shows it: [256, 224, 3] rotated (ROT270), else [224, 256, 3]."""
        rgb = self.pens[self.render_raw(mem, flip)[VISIBLE[2]:VISIBLE[3] + 1]]
        return np.ascontiguousarray(np.rot90(rgb, 1)) if rotate else rgb


class RocnRope:
    def __init__(self, dsw1=DSW1, dsw2=DSW2, dsw3=DSW3):
        self.rom = rom_image()
        self.mem = bytearray(0x10000)              # RAM areas (and the ROM copy, for render/compare convenience)
        self.mem[0x6000:] = self.rom[0x6000:]
        self.system = self.in0 = self.in1 = 0xFF
        self.dsw1, self.dsw2, self.dsw3 = dsw1, dsw2, dsw3
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
        if a >= 0x6000 or 0x4000 <= a < 0x6000:
            return self.mem[a]
        if a == 0x3000:
            return self.dsw2
        if a == 0x3100:
            return self.dsw3
        if 0x3080 <= a < 0x3084:
            return (self.system, self.in0, self.in1, self.dsw1)[a & 3]
        return 0

    def wr(self, a, v):
        if 0x4000 <= a < 0x6000 or 0xFFF2 <= a < 0xFFFE:
            self.mem[a] = v
        elif a == 0x8000:
            self.watchdog += 1
        elif 0x8080 <= a < 0x8088:
            q, b = a & 7, v & 1
            old = self.latch[q]
            self.latch[q] = b
            if q == 1 and b and not old:
                self.sound_log.append((self.frame, self.sound_latch))
            elif q == 7 and not b:
                self.cpu.set_irq(False)
        elif a == 0x8100:
            self.sound_latch = v
        elif 0x8182 <= a < 0x818E:
            self.mem[0xFFF2 + a - 0x8182] = v

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
        return self.video.render_rgb(self.mem)       # (flip screen, Q0 inverted: cocktail only, not drawn)


if __name__ == "__main__":
    import time
    m = RocnRope()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, sound commands %d, latch %s" % (time.time() - t, m.cpu.pc, len(m.sound_log), m.latch))


class RocnRopePort(RocnRope):
    """The STE runtime's schedule (src/rocnrope.s), one call of run_frame_port an arcade frame.

    The foreground is a task loop: $6065 CLRA; STA $8082; $6069 LDX <$1A; LDD ,X; ASLA; BCC $604D (the queue at
    $5100-$513F, its read pointer at $501A; an entry with bit 7 set is empty); with the queue empty `BSR $6094` (it
    blinks the coin text from the frame counter $504F: idempotent, so once a frame is as good as the arcade's
    thousands) and round again.  The IRQ handler ($70A0, at the VBLANK while latch Q7 is 1) plays the game and queues
    the tasks.  The port's idle point is $6070 (the BSR) with an empty queue: the foreground runs one empty round
    from there, then the IRQ is delivered (while Q7 is 1) with $6070 as its return address; after its RTI the
    foreground runs the queued tasks until the queue is empty again.  The boot: from the reset to the first idle.
    """
    IDLE = 0x6070
    IRQ = 0x70A0
    QPTR = 0x501A

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.booted = False
        self.irqs = 0

    def waits(self):
        m = self.mem
        return m[(m[self.QPTR] << 8) | m[self.QPTR + 1]] & 0x80 != 0

    def run_to_idle(self, limit=20000000):
        """the foreground (at least one instruction) until the task queue is empty at the idle point, or until it
        waits in a CWAI (the intro's screen clears and some other tasks wait for the next interrupt that way)"""
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.wait or c.pc == self.IDLE and self.waits():
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        if self.latch[7] and (c.wait or not c.cc & 0x10):
            if not c.wait:
                self.run_to_idle()                    # (the empty round: BSR $6094)
            c.set_irq(True)
            c.step()                                  # (the entry: the state pushed, I set, PC = the vector)
            assert c.pc == self.IRQ, hex(c.pc)
            self.irqs += 1
            self.run_to_idle()
        self.frame += 1
