"""Trojan (MAME `trojanr`, Capcom 1986, Romstar set 1): the reference board, from MAME capcom/lwings.cpp (the
`trojan` machine).

Main CPU: Z80 at 12 MHz / 4 = 3 MHz: engine/z80mame.py (MAME's core, M-cycle for M-cycle) with the BUSREQ line added
(Z80Bus).  engine/z80.py is not enough here: its indexed instructions (ld r,(ix+d), ...) take 4 cycles more than
MAME's, the boot fell 40 lines behind by frame 7.
Screen: 6 MHz pixel clock, 384 x 282 total, 256 x 240 visible (x 0-255, lines 8-247), 55.4 Hz: a line is 192 CPU
cycles, a frame 54144.  MAME's time 0 is the start of the vertical blank (line 248): its k-th frame_done (where
engine/mame_frames.lua dumps) comes k frames later; the vertical blank lasts 34 lines (248-281, 0-7).
Interrupts (the scanline timer, every 8 lines): line 128 the IRQ (HOLD_LINE, vector $FF: RST 38), line 248 the NMI
while the mask (bankswitch bit 3) is 1.
Sprite DMA: a write to $F808 during the vertical blank asserts BUSREQ; at the end of that instruction the CPU grants
the bus, the 0x180 bytes of $DE00-$DF7F are copied to the sprite buffer (MAME's buffered_spriteram8) and the CPU waits
0x180 * 2 cycles of 6 MHz (384 of its own) until the release.  Outside the vertical blank the write does nothing.

Timing as MAME's scheduler makes it (cycle-exact against MAME's write log over 3600 frames, see ref/): times are kept
in attoseconds with MAME's truncated periods (the CPU cycle 333333333333, the pixel 166666666666, so a frame is 72192
as short of 54144 cycles and a line 256 as short of 192); the CPU runs in slices up to the next timer, the cycle count
by MAME's shifted division (device_scheduler::timeslice); a timer less than a cycle ahead fires before the CPU runs
again.  So an interrupt, the frame's end and the DMA's end land one cycle before their nominal cycle when an
instruction ends there, depending on where the slices start: every timer of the whole board ends a slice (the
scanline timer, the MSM5205's VCK and capture timers, the sound streams' 50 Hz update) and every synchronised write
of the main CPU (the sound latches, the sound CPU's reset line in $F80E, BUSREQ) ends one at once.

Main CPU map (unmapped reads $FF):
    $0000-$7FFF ROM (tbu_04.10n)            $8000-$BFFF bank: 4 x 16 KB of tbu_06.13n, tbu_05.12n
    $C000-$DDFF RAM, $DE00-$DF7F sprites (96 x 4: code, attr, y, x), $DF80-$DFFF RAM
    $E000-$E3FF fg codes, $E400-$E7FF fg attributes   $E800-$EBFF bg1 codes, $EC00-$EFFF bg1 attributes
    $F000-$F3FF palette high bytes (rrrrgggg), $F400-$F7FF low bytes (bbbb----): write only, 1024 pens RGBx_444
    w $F800/1 bg1 scroll x, $F802/3 bg1 scroll y, $F804 bg2 scroll x, $F805 bg2 image (row offset into the map ROM)
    r $F808 SERVICE (start 1/2, coins), $F809 P1, $F80A P2, $F80B DSWB, $F80C DSWA
    w $F808 sprite DMA, $F80C sound latch, $F80D ADPCM latch, $F80E bankswitch: bit 0 0 = flip screen, bits 1-2 ROM
      bank, bit 3 NMI enable, bit 5 sound CPU reset, bits 6-7 coin counters
Sound: a Z80 with two YM2203 (latch $F80C) and an ADPCM Z80 with an MSM5205 (latch $F80D); the main CPU never reads
anything back, so neither is emulated: sound_log / adpcm_log keep (frame, value) of each latch write.

Video (lwings_v / screen_update_trojan), from back to front:
    bg2   32 x 16 tiles 16x16 (gfx4, 512 tiles, pens 0-127), opaque, x scroll $F804; the tile map is the 32 KB ROM
          tb_23.9n: tile (col, row) at ((row * $800) | (col * 2)) + image * $20, bytes code, attribute (bit 7 code
          bit 8, bits 4-5 flip y/x, bits 0-2 colour)
    bg1   32 x 32 tiles 16x16 (gfx2, 2048 tiles, pens 256-383), column-major, 16-bit scroll x/y; attribute bits 5-7
          code bits 8-10, bit 4 flip x, bit 3 the split group, bits 0-2 colour.  Drawn twice: the back half (group 0:
          pen 0 transparent; group 1: pens 0 and 7-11 transparent) before the sprites, the front half (group 0:
          nothing; group 1: pens 7-11) after them
    sprites  96, from the last to the first, 16x16 (gfx3, 2048, pens 640-767), pen 15 transparent; attribute bits
          7/5/6 code bits 10/9/8, bit 4 flip x, bits 1-3 colour, bit 0 x bit 8 (x - 256); always flipped in y; y > $F8
          is y - 256.  From the sprite buffer.
    fg    32 x 32 chars 8x8 2bpp (gfx1, 1024, pens 768-831), pen 3 transparent; attribute bits 6-7 code bits 8-9,
          bits 4-5 flip x/y, bits 0-3 colour
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from z80mame import Z80Mame, OPS0, F_NMI, F_EI, SA_BUSREQ
from z80mame_ops import take_nmi, take_interrupt
import mamegfx as G

LINE = 192
LINES = 282
FRAME = LINE * LINES                       # 54144
VBLANK_LINES = 34                          # 248-281, 0-7
# MAME's clocks in attoseconds (HZ_TO_ATTOSECONDS truncates): the CPU's cycle, the screen's pixel, frame and line
APC = 10 ** 18 // 3000000                  # 333333333333
APX = 10 ** 18 // 6000000                  # 166666666666 (the pixel clock 12 MHz / 2)
FP = APX * 384 * LINES                     # the frame period: 18047999999927808, 72192 short of 54144 cycles
SCANTIME = FP // LINES
VBLANK_AS = SCANTIME * VBLANK_LINES
DMA_AS = 0x180 * 2 * APX                   # sprite_dma_start_w: from_ticks(0x300, 6 MHz), 384 cycles less 384
DIVSHIFT, DIVISOR = 8, APC >> 8            # device_execute_interface: cycles = (delta >> 8) / divisor
SCANLINES = list(range(256, LINES, 8)) + list(range(0, 248, 8))     # the scanline timer's lines after line 248
VISIBLE = (0, 255, 8, 247)

# MAME's defaults (INPUT_PORTS trojan): DSWA 1C1C both, 3 lives, no flip, continue; DSWB upright 1 player ($00),
# bonus 30000 60000 ($1C), starting level 1 ($E0)
DSWA, DSWB = 0xFF, 0xFC


def load(name):
    return (EXTRACTED / "trojan" / name).read_bytes()


GFX2 = ("tb13.bin", "tb09.bin", "tb12.bin", "tb08.bin", "tb11.bin", "tb07.bin", "tb14.bin", "tb10.bin")
GFX3 = ("tb18.bin", "tb16.bin", "tb17.bin", "tb15.bin", "tb22.bin", "tb20.bin", "tb21.bin", "tb19.bin")
GFX4 = ("tb25.bin", "tb24.bin")
X16 = [0, 1, 2, 3, 8, 9, 10, 11, 256, 257, 258, 259, 264, 265, 266, 267]


def pens_rgb(pal_hi, pal_lo):
    """RGBx_444 from palette_ext ($F000, rrrrgggg) and palette ($F400, bbbb----): [1024, 3]."""
    hi = np.frombuffer(bytes(pal_hi), np.uint8)
    lo = np.frombuffer(bytes(pal_lo), np.uint8)
    return (np.stack([hi >> 4, hi & 15, lo >> 4], axis=1) * 17).astype(np.uint8)


class Video:
    def __init__(self):
        gfx1 = load("tb03.bin")
        gfx2 = b"".join(load(n) for n in GFX2)
        gfx3 = b"".join(load(n) for n in GFX3)
        gfx4 = b"".join(load(n) for n in GFX4)
        self.chars = G.decode_gfx(gfx1, 8, 8, 1024, [0, 4], [0, 1, 2, 3, 8, 9, 10, 11], [16 * y for y in range(8)], 128)
        q = len(gfx2) * 8 // 4
        self.tiles = G.decode_gfx(gfx2, 16, 16, 2048, [3 * q, 2 * q, q, 0], list(range(8)) + list(range(128, 136)),
                                  [8 * y for y in range(16)], 256)
        h = len(gfx3) * 8 // 2
        self.sprites = G.decode_gfx(gfx3, 16, 16, 2048, [h + 4, h, 4, 0], X16, [16 * y for y in range(16)],
                                    512).astype(np.int16)    # (pens above 255: draw_gfx adds in this type)
        h = len(gfx4) * 8 // 2
        self.bg2tiles = G.decode_gfx(gfx4, 16, 16, 512, [h, h + 4, 0, 4], X16, [16 * y for y in range(16)], 512)
        self.map = load("tb23.bin")
        # bg1 transparency per group: (back half, front half) as pens -> transparent
        pen = np.arange(16)
        back = [pen == 0, (pen == 0) | ((pen >= 7) & (pen <= 11))]
        front = [np.ones(16, bool), ~((pen >= 7) & (pen <= 11))]
        self.bg1_back = np.array(back)
        self.bg1_front = np.array(front)

    def bg2(self, scrollx, image):
        """The bg2 layer's pens on the screen [256, 256]."""
        rows, cols = np.indices((16, 32))
        idx = (((rows * 0x800) | (cols * 2)) + image * 0x20) & 0x7FFF
        m = np.frombuffer(self.map, np.uint8)
        code = m[idx].astype(np.int32)
        attr = m[idx + 1]
        code += (attr & 0x80).astype(np.int32) << 1
        pix, _ = G.tile_pixmap(self.bg2tiles, code, attr & 7, attr & 0x10, attr & 0x20, 16, 32, 0, 16)
        return pix[:, (np.arange(256) + scrollx) % 512]

    def render_raw(self, mem, sprites, regs):
        """The screen's pens [256 rows, 256] (rows 8-247 visible) from the main CPU's memory (64 KB image: $E000-$EFFF),
        the sprite buffer (0x180 bytes) and the registers (dict: scroll1x, scroll1y, scroll2x, image, flip)."""
        if regs.get("flip"):
            raise NotImplementedError("flip screen (cocktail)")
        bm = self.bg2(regs["scroll2x"] & 0xFF, regs["image"]).astype(np.int16)
        # bg1: 32 x 32, column-major (tile index col * 32 + row)
        codes = np.frombuffer(bytes(mem[0xE800:0xEC00]), np.uint8).reshape(32, 32).T
        attrs = np.frombuffer(bytes(mem[0xEC00:0xF000]), np.uint8).reshape(32, 32).T
        code = codes.astype(np.int32) + ((attrs & 0xE0).astype(np.int32) << 3)
        pix, raw = G.tile_pixmap(self.tiles, code, attrs & 7, attrs & 0x10, np.zeros_like(attrs), 32, 32, 256, 16)
        group = np.repeat(np.repeat((attrs >> 3) & 1, 16, 0), 16, 1)
        ys = (np.arange(256) + regs["scroll1y"]) % 512
        xs = (np.arange(256) + regs["scroll1x"]) % 512
        pix, raw, group = pix[np.ix_(ys, xs)], raw[np.ix_(ys, xs)], group[np.ix_(ys, xs)]
        back = ~self.bg1_back[group, raw]
        front = ~self.bg1_front[group, raw]
        bm[back] = pix[back]
        for offs in range(0x17C, -1, -4):
            code, attr, y, x = sprites[offs:offs + 4]
            sx = x - 0x100 * (attr & 1)
            sy = y - 0x100 if y > 0xF8 else y
            n = code | ((attr >> 7 & 1) << 10) | ((attr >> 5 & 1) << 9) | ((attr >> 6 & 1) << 8)
            G.draw_gfx(bm, VISIBLE, self.sprites, n, 640 + ((attr & 0x0E) >> 1) * 16, attr & 0x10, True, sx, sy,
                       lambda s: s == 15)
        bm[front] = pix[front]
        vram = np.frombuffer(bytes(mem[0xE000:0xE400]), np.uint8).reshape(32, 32)
        cram = np.frombuffer(bytes(mem[0xE400:0xE800]), np.uint8).reshape(32, 32)
        code = vram.astype(np.int32) + ((cram & 0xC0).astype(np.int32) << 2)
        pix, raw = G.tile_pixmap(self.chars, code, cram & 15, cram & 0x10, cram & 0x20, 32, 32, 768, 4)
        keep = raw != 3
        bm[keep] = pix[keep]
        return bm

    def render_rgb(self, mem, sprites, regs, pens):
        """The visible picture [240, 256, 3] as MAME's snapshot shows it; pens: [1024, 3]."""
        return pens[self.render_raw(mem, sprites, regs)[VISIBLE[2]:VISIBLE[3] + 1]]


VCK_HALF = 48 * (10 ** 18 // 384000)     # MSM5205 at 384 kHz, prescaler 96: VCK toggles every 48 clocks from time 0
CAPTURE = 6 * (10 ** 18 // 384000)       # its capture timer: 6 clocks after each VCK low edge
STREAMS = 10 ** 18 // 50                 # sound_manager's update timer, 50 Hz from time 0


def other_timers(t0, t1):
    """The times in [t0, t1) of the timers outside the main board that MAME runs anyway (they end the main CPU's
    slices): the MSM5205's VCK and capture timers (the ADPCM CPU never changes the prescaler: it writes $80 or the
    nibble to port 1, S1 stays 0) and the sound streams' update.  (The YM2203 timers are not modelled.)"""
    out = []
    k = -(-t0 // VCK_HALF)
    while k * VCK_HALF < t1:
        out.append(k * VCK_HALF)
        k += 1
    k = max(1, -(-(t0 - CAPTURE) // (2 * VCK_HALF)))
    while 2 * k * VCK_HALF + CAPTURE < t1:
        out.append(2 * k * VCK_HALF + CAPTURE)
        k += 1
    k = max(1, -(-t0 // STREAMS))
    while k * STREAMS < t1:
        out.append(k * STREAMS)
        k += 1
    return [t for t in out if t >= t0]


class Z80Bus(Z80Mame):
    """engine/z80mame.py with the BUSREQ line (z80.lst "ffff": a held BUSREQ grants the bus (busack callback) and
    swallows the rest of the slice until the line is cleared)."""

    def __init__(self, *args, busack=None):
        self.busack_cb = busack
        super().__init__(*args)

    def set_busreq(self, state):
        if not self.busreq and state:
            self.sa |= 1 << SA_BUSREQ
        self.busreq = 1 if state else 0

    def _loop(s):
        while True:
            while s.icount <= 0:
                yield
            if s.sa:
                if s.busreq:
                    if not s.busack:
                        s.busack = 1
                        s.busack_cb()
                    if s.icount > 0:
                        s.icount = 0
                    continue
                s.sa &= ~(1 << SA_BUSREQ)
                s.busack = 0
                if s.sa & F_NMI:
                    yield from take_nmi(s)
                elif s.irq_state and s.iff1 and not s.sa & F_EI:
                    yield from take_interrupt(s)
                s.sa &= ~F_EI
                if s.halt_:
                    s.TL = s._rd(s.PC)
                    s.icount -= 2
                    if s.icount <= 0:
                        yield
                    s.icount -= 2
                    if s.icount <= 0:
                        yield
                    s.R = (s.R + 1) & 0xFF
                    s.q = s.qt
                    s.qt = 0x28
                    continue
            s.PRVPC = s.PC
            if s.hook is not None:
                s.hook()
            s.TL = s._rd(s.PC)
            s.icount -= 2
            if s.icount <= 0:
                yield
            s.icount -= 2
            if s.icount <= 0:
                yield
            s.PC = (s.PC + 1) & 0xFFFF
            s.R = (s.R + 1) & 0xFF
            s.q = s.qt
            s.qt = 0x28
            r = OPS0[s.TL](s)
            if r is not None:
                yield from r


class Trojan:
    """The board as MAME's scheduler runs the main CPU: slices up to the next event (the line 128 IRQ, the frame's
    end with the NMI, the sprite DMA's end); a synchronised line change (BUSREQ) ends the slice at once (MAME's
    abort_timeslice), the rest of the instruction runs in the next one."""

    def __init__(self, dswa=DSWA, dswb=DSWB):
        rom = bytearray(0x20000)
        rom[0x00000:0x08000] = load("tb04.bin")
        rom[0x10000:0x18000] = load("tb06.bin")
        rom[0x18000:0x20000] = load("tb05.bin")
        self.rom = bytes(rom)
        self.mem = bytearray(0x10000)           # RAM $C000-$EFFF (the rest unused)
        self.pal_hi = bytearray(0x400)
        self.pal_lo = bytearray(0x400)
        self.pal_written = np.zeros(0x400, bool)    # pens the game wrote (MAME's others keep its default colours)
        self.sprites = bytearray(0x180)         # the DMA's buffer
        self.inputs = [0xFF, 0xFF, 0xFF, dswb, dswa]      # $F808-$F80C
        self.regs = dict(scroll1x=0, scroll1y=0, scroll2x=0, image=0, flip=False)
        self.scroll = bytearray(4)
        self.bankreg = 0
        self.bank = 0
        self.nmi_mask = 0
        self.sound_log = []
        self.adpcm_log = []
        self.dma_log = []                       # (frame, cycle in the frame) of each sprite DMA
        self.busreq_sync = False
        self.dma_end = None
        self.frame = 0
        self.cycles = 0                         # cycles at the start of the running slice (MAME's local time / APC)
        self.vblank_end = VBLANK_AS
        self.cpu = Z80Bus(self.rd, self.wr, lambda p: 0xFF, lambda p, v: None, self.irq_ack, busack=self.busack)
        self.video = None

    def time(self):
        """machine().time() at an access, in cycles"""
        return self.cycles + self.cpu.executed()

    def time_as(self):
        return self.time() * APC

    def rd(self, a):
        if a < 0x8000:
            return self.rom[a]
        if a < 0xC000:
            return self.rom[0x10000 + self.bank * 0x4000 + a - 0x8000]
        if a < 0xF000:
            return self.mem[a]
        if 0xF808 <= a <= 0xF80C:
            return self.inputs[a - 0xF808]
        return 0xFF

    def wr(self, a, v):
        if 0xC000 <= a < 0xF000:
            self.mem[a] = v
        elif a >= 0xF800:
            if a <= 0xF803:
                self.scroll[a - 0xF800] = v
                self.regs["scroll1x"] = self.scroll[0] | self.scroll[1] << 8
                self.regs["scroll1y"] = self.scroll[2] | self.scroll[3] << 8
            elif a == 0xF804:
                self.regs["scroll2x"] = v
            elif a == 0xF805:
                self.regs["image"] = v
            elif a == 0xF808:
                if self.time_as() < self.vblank_end:   # sprite_dma_trigger_w: only in the vertical blank
                    self.busreq_sync = True            # set_input_line: synchronised (the slice ends)
                    self.cpu.abort()
            elif a == 0xF80C:
                self.sound_log.append((self.frame, v))
                self.cpu.abort()                       # generic_latch_8: synchronize()
            elif a == 0xF80D:
                self.adpcm_log.append((self.frame, v))
                self.cpu.abort()
            elif a == 0xF80E:
                self.cpu.abort()                       # the sound CPU's reset line: set_input_line, synchronised
                self.bankreg = v
                self.regs["flip"] = not v & 1
                self.bank = v >> 1 & 3
                self.nmi_mask = v >> 3 & 1
        elif a >= 0xF400:
            self.pal_lo[a - 0xF400] = v
            self.pal_written[a - 0xF400] = True
        elif a >= 0xF000:
            self.pal_hi[a - 0xF000] = v
            self.pal_written[a - 0xF000] = True

    def irq_ack(self):
        self.cpu.set_input("irq", 0)            # HOLD_LINE: released by the acknowledge
        return 0xFF

    def busack(self):
        """sprite_dma_start_w: the buffer copy, BUSREQ released 0x180 * 2 ticks of 6 MHz later (a new head timer: the
        slice ends)"""
        t = self.time()
        self.sprites[:] = self.mem[0xDE00:0xDF80]
        self.dma_log.append((self.frame, t - self.frame * FRAME))
        self.dma_end = t * APC + DMA_AS
        self.cpu.abort()

    def run_until(self, event):
        """device_scheduler::timeslice for the main CPU up to the event (attoseconds): a slice runs the whole cycles
        that fit before the next timer (none when less than one fits: the timer fires first); the DMA's end timer
        releases BUSREQ."""
        c = self.cpu
        while True:
            dma = self.dma_end is not None and self.dma_end <= event
            end = self.dma_end if dma else event
            delta = end - self.cycles * APC
            if delta < APC:
                if not dma:
                    return
                self.dma_end = None
                c.set_busreq(0)
                continue
            self.cycles += c.run((delta >> DIVSHIFT) // DIVISOR)
            if self.busreq_sync:
                self.busreq_sync = False
                c.set_busreq(1)

    def run_frame(self):
        """Runs to the end of the frame (the next vertical blank: where MAME's frame_done sees the machine).  Every timer
        of the board ends a slice: the scanline timer every 8 lines (line 128 asserts the IRQ, line 248 at the frame's
        end pulses the NMI) and the sound board's (other_timers)."""
        vstart = self.frame * FP                 # the vertical blank's start (MAME's vblank_begin timer)
        vend = vstart + FP
        self.vblank_end = vstart + VBLANK_AS
        events = [(vstart + ((line + VBLANK_LINES) % LINES) * SCANTIME, line) for line in SCANLINES]
        events += [(t, None) for t in other_timers(vstart, vend)]
        for t, line in sorted(events):
            self.run_until(t)
            if line == 128:
                self.cpu.set_input("irq", 1)
        self.run_until(vend)
        self.frame += 1
        if self.nmi_mask:
            self.cpu.set_input("nmi", 1)
            self.cpu.set_input("nmi", 0)

    def pens(self):
        return pens_rgb(self.pal_hi, self.pal_lo)

    def render_rgb(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, self.sprites, self.regs, self.pens())


IDLE_PC = 0x0491                           # the idle loop: ei / call $0498 (bank 0, jp $A000: the task queue) / jp $0491
QUEUE = 0xCD82                             # the task queue's read pointer: (it) = $FF when empty
NMI_TOKEN = 0xBFFE                         # the return address the port's NMI pushes (never a real address)


class TrojanPort(Trojan):
    """The board as the STE runtime schedules it (engine/z80.py, flags as the translation keeps them): the foreground
    runs until it idles (at IDLE_PC with the task queue empty); then a frame is the NMI handler run to its return,
    then the foreground until it idles again.  The line-128 IRQ is not delivered: its handler is `di / ret` (the idle
    loop's `ei` enables it again), nothing else.  The sprite DMA ($F808) happens in the NMI handler (the arcade's
    vertical blank), the palette and the registers are kept in mem too (the translated program's image)."""

    def __init__(self, dswa=DSWA, dswb=DSWB):
        super().__init__(dswa, dswb)
        from z80 import Z80
        self.cpu = Z80(self.rd, self.wr)
        self.cpu.afmask = 0xC1                 # (push af keeps S Z C: what the translation keeps)
        self.in_nmi = False
        self.booted = False

    def rd(self, a):
        if a < 0x8000:
            return self.rom[a]
        if a < 0xC000:
            return self.rom[0x10000 + self.bank * 0x4000 + a - 0x8000]
        if 0xF808 <= a <= 0xF80C:
            return self.inputs[a - 0xF808]
        if a >= 0xF000:
            return 0xFF
        return self.mem[a]

    def wr(self, a, v):
        if a >= 0xF000:
            if a == 0xF808:
                if self.in_nmi:
                    self.sprites[:] = self.mem[0xDE00:0xDF80]
                    self.dma_log.append((self.frame, 0))
                return
            self.mem[a] = v
            if a == 0xF80C:
                self.sound_log.append((self.frame, v))
            elif a == 0xF80D:
                self.adpcm_log.append((self.frame, v))
            elif a >= 0xF800:
                Trojan.wr(self, a, v) if a != 0xF80E else self._bank(v)
            else:
                Trojan.wr(self, a, v)
        elif a >= 0xC000:
            self.mem[a] = v

    def _bank(self, v):
        self.bankreg = v
        self.regs["flip"] = not v & 1
        self.bank = v >> 1 & 3
        self.nmi_mask = v >> 3 & 1

    def idle(self):
        c = self.cpu
        return c.pc == IDLE_PC and self.mem[self.mem[QUEUE] | self.mem[QUEUE + 1] << 8] == 0xFF

    def run_to_idle(self, limit=3000000):
        c = self.cpu
        for _ in range(limit):
            if self.idle():
                return
            c.step()
        raise RuntimeError("the foreground does not idle: pc %04X bank %d" % (c.pc, self.bank))

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        if self.nmi_mask:
            c.halted = False
            c.iff2 = c.iff1
            c.iff1 = 0
            c.push(NMI_TOKEN)
            c.pc = 0x66
            self.in_nmi = True
            for _ in range(3000000):
                c.step()
                if c.pc == NMI_TOKEN:
                    break
            else:
                raise RuntimeError("the NMI handler does not return")
            self.in_nmi = False
            c.pc = IDLE_PC
        c.step()                               # (out of the idle point, then the tasks)
        self.run_to_idle()
        self.frame += 1


if __name__ == "__main__":
    import time
    from PIL import Image
    from paths import build_dir
    m = Trojan()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    t = time.time()
    while m.frame < n:
        m.run_frame()
    print("%d frames in %.1f s, pc %04X, bank %d, sound commands %d, adpcm %d, DMAs %d" % (
        n, time.time() - t, m.cpu.PC, m.bank, len(m.sound_log), len(m.adpcm_log), len(m.dma_log)))
    out = build_dir("trojan") / "reference.png"
    Image.fromarray(m.render_rgb()).save(out)
    print(out)
