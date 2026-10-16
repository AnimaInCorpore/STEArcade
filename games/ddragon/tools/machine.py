"""Double Dragon (MAME `ddragonj`, Technos 1987, Japan set 1): the reference board, from MAME technos/ddragon.cpp and
ddragon_v.cpp (the `ddragon` machine).

CPUs, in MAME's device order (the scheduler runs them in this order each slice; a suspended one goes to the end):
    main   HD6309E at 12 MHz / 4 = 3 MHz: engine/m6809.py.  The program never leaves emulation mode and uses no 6309
           instruction (MAME traces of attract and play), and MAME's hd6309.lst takes the 6809's cycles in
           emulation mode for every 6809 instruction, so the 6809 core is the 6309 here.
    sub    HD63701Y0 at 6 MHz (1.5 MHz E clock): engine/hd63701.py HD63701Y0.  The sprite MCU: on an NMI from the
           main CPU it sorts the object list in the shared RAM and turns it into sprite entries there, then raises
           the main CPU's IRQ through port 6 (bit 1 rising) and drops its own NMI (bit 0 low).
    sound  MC6809 at 6 MHz (1.5 MHz): YM2151 (FIRQ, engine/namcos1.py's model of its timers) and two MSM5205
           (ADPCM from 21j-6 / 21j-7); the main CPU never reads anything from it, but its slices, its latch reads
           and the YM2151's and MSM5205's timers cut the slices of the others, so it runs here as in MAME.
MAME's quantum is 1/60000 s (set_maximum_quantum); all timers and every synchronised line change end a slice
(engine/namcos1.py has the same scheduler, verified against MAME instruction for instruction).  MAME's cores split
an instruction at a slice's end, engine/m6809.py runs whole ones; reads on an instruction's last bus cycle that can
see a timer take MAME's time: the vertical blank bit by the time alone, the YM2151's status and the ADPCM idle bits
after the YM2151 / MSM5205 timers that expire before the read cycle (fire_early).  Checked by ref/trace_cmp.py
(every instruction of each CPU against MAME's trace) and ref/mame_cmp_ddragon.py (memory and pictures).

Screen: 6 MHz pixel clock, 384 x 272, visible 256 x 240 (lines 0-239); a line is 192 main CPU cycles, a frame 52224
(57.44 Hz).  MAME's time 0 is the start of the vertical blank (line 240): frame k ends (frame_done, where
engine/mame_frames.lua dumps) at k frame periods.  The scanline timer runs every line: line 240 (vcount $F8) asserts
the NMI, the rising edge of vcount bit 3 the FIRQ (lines 0, 16, ..., 240, 264 count from vcount $08-$FF, $1E8-$1FF).
The vertical blank (EXTRA bit 3) lasts 32 lines.

Main CPU map:
    $0000-$0FFF RAM   $1000-$11FF palette (ggggrrrr)   $1200-$13FF palette (----bbbb): 512 pens xBGR_444
    $1800-$1FFF fg (32 x 32: attribute, code)   $2000-$21FF shared RAM (mirrored to $27FF; only while the sub CPU
    is held in reset or halted, else reads $FF and writes are lost)   $2800-$2FFF sprites   $3000-$37FF bg
    r $3800 P1, $3801 P2, $3802 EXTRA (bit 3 vblank, bit 4 low = the sub CPU's bus free), $3803 DSW0, $3804 DSW1
    w $3808 bank: bit 0/1 scroll x/y bit 8, bit 2 low = flip, bit 3 low = sub CPU reset, bit 4 = sub CPU halt,
      bits 5-7 the ROM bank at $4000 (16 KB pages of 21j-2-3 / 21j-3 / 21j-4-1)
    w $3809 scroll x, $380A scroll y; $380B-$380F (read or write): NMI, FIRQ, IRQ acknowledge, sound latch (+ the
      sound CPU's IRQ), the sub CPU's NMI
Sub CPU: $8000-$81FF the shared RAM.  Sound CPU: $0000-$0FFF RAM, r $1000 latch, r $1800 ADPCM idle bits, $2800/1
YM2151, w $3800-$3807 ADPCM (start, end, address, stop for chips 0/1), $8000 21j-0-1.

Video (back to front): bg 32 x 32 tiles 16x16 (512 x 512, MAME's background_scan, pens 256-383, opaque, 9-bit
scroll), sprites (pens 128-255, pen 0 transparent, 1-4 of 16x16, from the first to the last entry), fg 32 x 32
chars 8x8 (pens 0-127, pen 0 transparent).  Both tilemaps have scrolldy -8: screen line y shows tilemap line y + 8
(+ scroll).
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809
from hd63701 import HD63701Y0
from namcos1 import YM2151
import mamegfx as G

AS = 10 ** 18
MAIN_AS = AS // 3000000                  # the HD6309E's cycle
SUB_AS = AS // 1500000                   # the HD63701Y0's E clock (6 MHz / 4)
SND_AS = AS // 1500000                   # the MC6809's (6 MHz / 4)
PIXEL_AS = AS // 6000000
SCAN_AS = 384 * PIXEL_AS
LINES = 272
FRAME_AS = SCAN_AS * LINES
VBLANK_LINES = 32                        # lines 240-271
QUANTUM_AS = AS // 60000
YM_HZ = 3579545
MSM_AS = AS // 375000                    # the MSM5205's clock (12 MHz / 32)
VCK_HALF = 24 * MSM_AS                   # prescaler S48: VCK toggles every 24 clocks from time 0
CAPTURE = 6 * MSM_AS                     # its capture timer (the vck_legacy callback): 6 clocks after each low edge
STREAMS_AS = AS // 50                    # sound_manager's update timer
LINE = 192                               # main CPU cycles a line
FRAME = LINE * LINES
MAIN, SUB, SND = 0, 1, 2
HZ = (3000000, 1500000, 1500000)

DSW0, DSW1 = 0xFF, 0xFF                  # MAME's defaults: 1C1C, upright, no flip; medium, demo sounds, 2 lives


def _shift_div(per):
    s = 0
    while (per >> s) >= 1 << 32:
        s += 1
    return s, per >> s


PER = (MAIN_AS, SUB_AS, SND_AS)
SHIFTDIV = [_shift_div(p) for p in PER]


def load(name):
    return (EXTRACTED / "ddragon" / name).read_bytes()


def vcount(line):
    v = line + 8
    return v if v < 0x100 else (v - 0x18) | 0x100


def firq_lines():
    return [l for l in range(LINES) if not vcount((l - 1) % LINES) & 8 and vcount(l) & 8]


FIRQ_LINES = frozenset(firq_lines())


class Video:
    """MAME's ddragon_v.cpp screen_update (flip screen not modelled): pens [240, 256] from a main CPU memory image
    (64 KB: palette, fg, sprites, bg) and the scroll registers."""

    def __init__(self):
        chars = load("21j-5")
        sprites = b"".join(load("21j-" + c) for c in "abcdefgh")
        tiles = b"".join(load("21j-" + c) for c in "89ij")
        x16 = [3, 2, 1, 0, 131, 130, 129, 128, 259, 258, 257, 256, 387, 386, 385, 384]
        self.chars = G.decode_gfx(chars, 8, 8, 1024, [0, 2, 4, 6], [1, 0, 65, 64, 129, 128, 193, 192],
                                  [8 * y for y in range(8)], 256)
        h = len(sprites) * 4
        self.sprites = G.decode_gfx(sprites, 16, 16, 4096, [h, h + 4, 0, 4], x16, [8 * y for y in range(16)],
                                    512).astype(np.int16)
        h = len(tiles) * 4
        self.tiles = G.decode_gfx(tiles, 16, 16, 2048, [h, h + 4, 0, 4], x16, [8 * y for y in range(16)], 512)
        # background_scan: logical (col, row) -> tile index
        rows, cols = np.indices((32, 32))
        self.bg_index = (cols & 0x0F) | ((rows & 0x0F) << 4) | ((cols & 0x10) << 4) | ((rows & 0x10) << 5)

    def render_raw(self, mem, scrollx, scrolly):
        bg = np.frombuffer(bytes(mem[0x3000:0x3800]), np.uint8)
        attr = bg[2 * self.bg_index]
        code = bg[2 * self.bg_index + 1].astype(np.int32) | ((attr & 7).astype(np.int32) << 8)
        pix, _ = G.tile_pixmap(self.tiles, code, (attr >> 3) & 7, attr & 0x40, attr & 0x80, 32, 32, 256, 16)
        ys = (np.arange(240) + 8 + scrolly) % 512
        xs = (np.arange(256) + scrollx) % 512
        bm = pix[np.ix_(ys, xs)].astype(np.int16)
        spr = mem[0x2800:0x3000]
        clip = (0, 255, 0, 239)
        for i in range(0, 0x800 - 4, 5):
            a = spr[i + 1]
            if not a & 0x80:
                continue
            sx = 240 - spr[i + 4] + ((a & 2) << 7)
            sy = 232 - spr[i] + ((a & 1) << 8)
            size = (a & 0x30) >> 4
            fx, fy = a & 8, a & 4
            color = 128 + (spr[i + 2] >> 4) * 16
            which = (spr[i + 3] | ((spr[i + 2] & 0x0F) << 8)) & ~size
            parts = {0: [(0, 0, 0)], 1: [(0, 0, -16), (1, 0, 0)], 2: [(0, -16, 0), (2, 0, 0)],
                     3: [(0, -16, -16), (1, -16, 0), (2, 0, -16), (3, 0, 0)]}[size]
            for order, dx, dy in parts:
                G.draw_gfx(bm, clip, self.sprites, which + order, color, fx, fy, sx + dx, sy + dy, lambda s: s == 0)
        fg = np.frombuffer(bytes(mem[0x1800:0x2000]), np.uint8).reshape(32, 64)
        attr = fg[:, 0::2]
        code = fg[:, 1::2].astype(np.int32) | ((attr & 7).astype(np.int32) << 8)
        zero = np.zeros_like(attr)
        pix, raw = G.tile_pixmap(self.chars, code, attr >> 5, zero, zero, 32, 32, 0, 16)
        pix, raw = pix[8:248], raw[8:248]
        keep = raw != 0
        bm[keep] = pix[keep]
        return bm

    @staticmethod
    def pens(mem):
        lo = np.frombuffer(bytes(mem[0x1000:0x1200]), np.uint8)
        hi = np.frombuffer(bytes(mem[0x1200:0x1400]), np.uint8)
        return (np.stack([lo & 15, lo >> 4, hi & 15], axis=1) * 17).astype(np.uint8)

    def render_rgb(self, mem, scrollx, scrolly):
        return self.pens(mem)[self.render_raw(mem, scrollx, scrolly)]


class DDragon:
    def __init__(self, dsw0=DSW0, dsw1=DSW1):
        rom = bytearray(0x30000)
        rom[0x08000:0x10000] = load("21j-1-5.26")
        rom[0x10000:0x18000] = load("21j-2-3.25")
        rom[0x18000:0x20000] = load("21j-3.24")
        rom[0x20000:0x28000] = load("21j-4-1.23")
        self.rom = bytes(rom)
        self.snd_rom = load("21j-0-1")
        self.adpcm_rom = [load("21j-6"), load("21j-7")]
        self.mem = bytearray(0x10000)            # the main CPU's RAM areas in place ($0000-$37FF)
        self.comram = bytearray(0x200)
        self.snd_ram = bytearray(0x1000)
        self.inputs = [0xFF, 0xFF, 0x07, dsw0, dsw1]     # P1, P2, EXTRA's fixed bits, DSW0, DSW1
        self.scroll_lo = [0, 0]
        self.bankreg = 0
        self.bank = 0
        self.sub_port = 0                        # m_ddragon_sub_port
        self.latch = 0
        self.latch_written = False
        self.sound_log = []                      # (frame, command)
        self.adpcm_pos = [0, 0]
        self.adpcm_end = [0, 0]
        self.adpcm_idle = [True, True]
        self.adpcm_data = [-1, -1]
        self.adpcm_log = []                      # (frame, chip, start, end)
        self.frame = 0
        # the scheduler
        self.base = 0
        self.local = [0, 0, 0]
        self.suspend = [0, 0, 0]                 # m_suspend (bit 0 reset, bit 1 halt)
        self.nextsuspend = [0, 0, 0]
        self.eat = [False, False, False]
        self.nexteat = [False, False, False]
        self.suspend_changed = False
        self.order = [MAIN, SUB, SND]
        self.executing = None
        self.slice_start = 0
        self.captures = []
        self.timers = []
        self.seq = 0
        self.queues = {}
        self.deferred = []
        self.aborted = False
        self.stop = False
        self.main = M6809(self.main_rd, self.main_wr)
        self.sub = HD63701Y0(load("21jm-0.ic55"), self.sub_rd, self.sub_wr, out_p6=self.sub_port6)
        self.snd = M6809(self.snd_rd, self.snd_wr)
        self.cpus = [self.main, self.sub, self.snd]
        self.ym = YM2151(self)
        self.main.reset()
        self.snd.reset()
        self.local[MAIN] = self.main.cycles * MAIN_AS
        self.local[SND] = self.snd.cycles * SND_AS
        self.timer(FRAME_AS, self.vblank_begin)
        self.timer(VBLANK_LINES * SCAN_AS, self.vblank_end)
        self.timer(VBLANK_LINES * SCAN_AS, self.scanline0)
        self.timer(VBLANK_LINES * SCAN_AS, lambda: self.scanline(0))
        self.timer(STREAMS_AS, self.streams)
        self.timer(VCK_HALF, lambda: self.vck(0, 1))
        self.timer(VCK_HALF, lambda: self.vck(1, 1))
        self.video = None
        self.vdirty = True
        self.lines = []                          # (first line, fg, sprites + bg, scroll x, scroll y) of the picture

    # ---- main CPU ---------------------------------------------------------------
    def now(self):
        """machine().time(): the executing CPU's local time at the start of its current instruction"""
        i = self.executing
        if i is None:
            return self.base
        return self.local[i] + (self.cpus[i].cycles - self.slice_start) * PER[i]

    def sub_free(self):
        return bool(self.nextsuspend[SUB] & 3)

    def main_rd(self, a):
        if a < 0x2000:
            return self.mem[a]
        if a < 0x2800:
            return self.comram[a & 0x1FF] if self.sub_free() else 0xFF
        if a < 0x3800:
            return self.mem[a]
        if a < 0x4000:
            if a <= 0x3804:
                if a == 0x3802:
                    # LDA/LDB extended only: the read is the 5th and last bus cycle, MAME's time there is its end.
                    # MAME splits an instruction at the slice's end, so a read past the vertical blank's start
                    # happens after vblank_begin: the blank by the time alone
                    t = self.now() + 5 * MAIN_AS
                    vb = 1 if t % FRAME_AS < VBLANK_LINES * SCAN_AS else 0
                    return self.inputs[2] | (vb << 3) | (0 if self.sub_free() else 0x10)
                return self.inputs[a - 0x3800]
            if 0x380B <= a <= 0x380F:
                self.interrupt_ack(a - 0x380B, 0xFF)
            return 0xFF
        if a < 0x8000:
            return self.rom[0x10000 + self.bank * 0x4000 + a - 0x4000]
        return self.rom[a]

    def main_wr(self, a, v):
        if a < 0x1800:
            if a < 0x1400:
                self.mem[a] = v
        elif a < 0x2000:
            self.mem[a] = v
            self.vdirty = True
        elif a < 0x2800:
            if self.sub_free():
                self.comram[a & 0x1FF] = v
        elif a < 0x3800:
            self.mem[a] = v
            self.vdirty = True
        elif a == 0x3808:
            self.vdirty = True
            self.bankreg = v
            self.bank = v >> 5
            self.set_line(SUB, "reset", not v & 0x08)
            self.set_line(SUB, "halt", bool(v & 0x10))
        elif a == 0x3809 or a == 0x380A:
            self.scroll_lo[a - 0x3809] = v
            self.vdirty = True
        elif 0x380B <= a <= 0x380F:
            self.interrupt_ack(a - 0x380B, v)

    def interrupt_ack(self, k, v):
        if k == 0:
            self.set_line(MAIN, "nmi", False)
        elif k == 1:
            self.set_line(MAIN, "firq", False)
        elif k == 2:
            self.set_line(MAIN, "irq", False)
        elif k == 3:
            self.sound_log.append((self.frame, v))
            self.at_end(lambda: self.synchronize(lambda: self.latch_write(v)))
        else:
            self.set_line(SUB, "nmi", True)

    def latch_write(self, v):
        self.latch = v
        self.set_latch_written(True)

    def set_latch_written(self, state):
        if self.latch_written != state:
            self.latch_written = state
            self.set_line(SND, "irq", state)

    @property
    def scrollx(self):
        return ((self.bankreg & 1) << 8) | self.scroll_lo[0]

    @property
    def scrolly(self):
        return ((self.bankreg & 2) << 7) | self.scroll_lo[1]

    # ---- sub CPU ----------------------------------------------------------------
    def sub_rd(self, a):
        if 0x8000 <= a < 0x8200:
            return self.comram[a - 0x8000]
        return 0xFF

    def sub_wr(self, a, v):
        if 0x8000 <= a < 0x8200:
            self.comram[a - 0x8000] = v

    def sub_port6(self, v, ddr):
        if not v & 1:
            self.set_line(SUB, "nmi", False)
        if not self.sub_port & 2 and v & 2:
            self.set_line(MAIN, "irq", True)
        self.sub_port = v

    # ---- sound CPU --------------------------------------------------------------
    def snd_rd(self, a):
        if a < 0x1000:
            return self.snd_ram[a]
        if a == 0x1000:
            self.set_latch_written(False)
            return self.latch
        if a == 0x1800:
            self.fire_early(5)                 # (ANDA extended: the read is the 5th cycle)
            return (1 if self.adpcm_idle[0] else 0) | (2 if self.adpcm_idle[1] else 0)
        if a == 0x2800 or a == 0x2801:
            # the program reads it with LDA extended: the read is the 5th and last bus cycle, where MAME's busy
            # check takes the time
            self.fire_early(5)
            t = self.now() + 5 * SND_AS
            return (self.ym.status & 3) | (0x80 if t < self.ym.busy_end else 0)
        if a >= 0x8000:
            return self.snd_rom[a - 0x8000]
        return 0xFF

    def snd_wr(self, a, v):
        if a < 0x1000:
            self.snd_ram[a] = v
        elif a == 0x2800 or a == 0x2801:
            self.ym.write(a & 1, v)
        elif 0x3800 <= a <= 0x3807:
            chip = a & 1
            k = (a & 7) >> 1
            if k == 3:
                self.adpcm_idle[chip] = True
            elif k == 2:
                self.adpcm_pos[chip] = (v & 0x7F) << 9
            elif k == 1:
                self.adpcm_end[chip] = (v & 0x7F) << 9
            else:
                self.adpcm_idle[chip] = False
                self.adpcm_log.append((self.frame, chip, self.adpcm_pos[chip], self.adpcm_end[chip]))

    def adpcm_int(self, chip):
        """ddragon_adpcm_int at the MSM5205's capture time"""
        if self.adpcm_pos[chip] >= self.adpcm_end[chip] or self.adpcm_pos[chip] >= 0x10000:
            self.adpcm_idle[chip] = True
        elif self.adpcm_data[chip] != -1:
            self.adpcm_data[chip] = -1
        else:
            self.adpcm_data[chip] = self.adpcm_rom[chip][self.adpcm_pos[chip]]
            self.adpcm_pos[chip] += 1

    # ---- the scheduler (MAME's device_scheduler, as engine/namcos1.py) -----------
    def timer(self, expire, fn):
        t = [expire, self.seq, fn]
        self.seq += 1
        k = len(self.timers)
        while k and self.timers[k - 1][0] > expire:
            k -= 1
        self.timers.insert(k, t)
        if k == 0 and self.executing is not None:
            self.abort()
        return t

    def cancel(self, t):
        if t in self.timers:
            self.timers.remove(t)

    def synchronize(self, fn):
        return self.timer(self.now(), fn)

    def abort(self):
        i = self.executing
        c = self.cpus[i]
        self.aborted = True
        if i == SUB:
            c.icount = 0
        else:
            c.end = c.cycles

    def fire_early(self, p):
        """A read on the executing CPU's p-th bus cycle of the instruction.  MAME splits an instruction at each slice's
        end (one cycle runs in a slice that ends at or after the cycle's end), so a timer that expires before the read
        cycle's end has fired when the read happens, though the instruction began before it.  Fires those a read can
        see: the YM2151's timers (its status) and the MSM5205's capture timers (the ADPCM idle bits)."""
        r = self.now() + p * PER[self.executing]
        due = [t for t in self.timers if t[0] < r and
               (any(t is x for x in self.ym.timer) or any(t is x for x in self.captures))]
        for t in due:
            self.timers.remove(t)
            saved = self.executing, self.base
            self.executing, self.base = None, t[0]
            t[2]()
            self.executing, self.base = saved

    def at_end(self, fn):
        """fn() when the executing 6809's instruction is done (MAME's 6809 counts a bus cycle before its access, a
        store is an instruction's last cycle); at once for the MCU (MAME's 6801 counts the cycles after the
        instruction) and outside a CPU"""
        i = self.executing
        if i is not None and i != SUB:
            self.deferred.append(fn)
            c = self.cpus[i]
            c.end = c.cycles
        else:
            fn()

    def set_line(self, cpu, line, state):
        q = self.queues.setdefault((cpu, line), [])
        q.append(state)
        if len(q) == 1:
            self.at_end(lambda: self.synchronize(lambda: self.apply_line(cpu, line)))

    def set_suspend(self, cpu, reason, on):
        if on:
            self.nextsuspend[cpu] |= reason
            self.nexteat[cpu] = True
        else:
            self.nextsuspend[cpu] &= ~reason
        self.suspend_changed = True

    def apply_line(self, cpu, line):
        for state in self.queues.pop((cpu, line)):
            c = self.cpus[cpu]
            if line == "reset":
                if state:
                    self.set_suspend(cpu, 1, True)
                elif self.nextsuspend[cpu] & 1:
                    c.reset()
                    self.set_suspend(cpu, 1, False)
            elif line == "halt":
                self.set_suspend(cpu, 2, state)
            elif line == "nmi":
                c.set_nmi(state)
            elif line == "irq":
                c.set_irq(state)
            else:
                c.set_firq(state)

    def apply_suspend_changes(self):
        changed = False
        for i in range(3):
            if self.suspend[i] != self.nextsuspend[i]:
                changed = True
            self.suspend[i] = self.nextsuspend[i]
            self.eat[i] = self.nexteat[i]
        if changed:
            self.order = [i for i in (MAIN, SUB, SND) if not self.suspend[i]] + \
                         [i for i in (MAIN, SUB, SND) if self.suspend[i]]
        else:
            self.suspend_changed = False

    def timeslice(self):
        timers, local, cpus = self.timers, self.local, self.cpus
        while self.base < timers[0][0]:
            target = self.base + QUANTUM_AS
            if timers[0][0] < target:
                target = timers[0][0]
            if self.suspend_changed:
                self.apply_suspend_changes()
            for i in self.order:
                if self.suspend[i] and not self.eat[i]:
                    continue
                per = PER[i]
                delta = target - local[i]
                if delta < per:
                    continue
                sh, dv = SHIFTDIV[i]
                n = (delta >> sh) // dv
                if self.suspend[i]:
                    ran = n
                    cpus[i].cycles += n                # (MAME's total cycles count them too)
                else:
                    c = cpus[i]
                    self.executing = i
                    self.slice_start = start = c.cycles
                    if i == SUB:
                        c.icount = 0
                        c.run(n)
                    else:
                        end = start + n
                        while True:
                            c.run(end - c.cycles)
                            if not self.deferred:
                                break
                            d, self.deferred = self.deferred, []
                            self.aborted = False
                            for fn in d:
                                fn()
                            if self.aborted or c.cycles >= end:
                                break
                    self.executing = None
                    ran = c.cycles - start
                local[i] += ran * per
                if local[i] < target:
                    target = max(local[i], self.base)
            self.base = target
        while timers and timers[0][0] <= self.base and not self.stop:
            t = timers.pop(0)
            t[2]()

    # ---- timers ---------------------------------------------------------------------
    def vblank_begin(self):
        """screen_device::vblank_begin: frame_update (MAME's frame_done: run_frame returns here)"""
        self.timer(self.base + FRAME_AS, self.vblank_begin)
        self.timer(self.base + VBLANK_LINES * SCAN_AS, self.vblank_end)
        self.stop = True

    def vblank_end(self):
        pass

    def scanline0(self):
        self.timer(self.base + FRAME_AS, self.scanline0)

    def scanline(self, line):
        """the scanline timer device: line 240 (vcount $F8) the NMI, a rising vcount bit 3 the FIRQ"""
        nxt = (line + 1) % LINES
        self.timer(self.base + SCAN_AS, lambda: self.scanline(nxt))
        if 1 <= line <= 240:
            # update_partial(line - 1): MAME draws the line before with the video state of this moment
            if line == 1:
                self.lines = []
                self.vdirty = True
            if self.vdirty:
                self.vdirty = False
                self.lines.append((line - 1, bytes(self.mem[0x1800:0x2000]), bytes(self.mem[0x2800:0x3800]),
                                   self.scrollx, self.scrolly))
        if line == 240:
            self.set_line(MAIN, "nmi", True)
        if line in FIRQ_LINES:
            self.set_line(MAIN, "firq", True)

    def streams(self):
        self.timer(self.base + STREAMS_AS, self.streams)

    def vck(self, chip, level):
        self.timer(self.base + VCK_HALF, lambda: self.vck(chip, 1 - level))
        if not level:
            self.captures.append(self.timer(self.base + CAPTURE, lambda: self.adpcm_int(chip)))
            del self.captures[:-4]

    def run_frame(self):
        """One arcade frame, ending where MAME's frame_done comes (the vertical blank's start)."""
        self.stop = False
        while not self.stop:
            self.timeslice()
        self.frame += 1

    # ---- video ----------------------------------------------------------------------
    def render_rgb(self):
        """The picture [240, 256, 3] as MAME's snapshot shows it: each line drawn with the video state at its
        update_partial (the next line's scanline timer), the colours from the palette at the frame's end."""
        if self.video is None:
            self.video = Video()
        if not self.lines:
            return self.video.render_rgb(self.mem, self.scrollx, self.scrolly)
        img = bytearray(self.mem)
        out = None
        for k, (y, fg, rest, sx, sy) in enumerate(self.lines):
            y1 = self.lines[k + 1][0] if k + 1 < len(self.lines) else 240
            img[0x1800:0x2000] = fg
            img[0x2800:0x3800] = rest
            raw = self.video.render_raw(img, sx, sy)
            if out is None:
                out = raw
            else:
                out[y:y1] = raw[y:y1]
        return Video.pens(self.mem)[out]


class DDragonPort(DDragon):
    """The STE runtime's schedule (src/ddragon.s), which the translated main program follows too (tools/logic_test.py
    compares the two frame by frame).  No CPU interleaves; one call of run_frame_port is one arcade frame:

      1. the NMI (the vertical blank) at the foreground's idle point: its handler runs to its RTI
      2. the FIRQ once, unless the foreground masks it (the coin and service inputs, debounced; the board runs it
         17 times a frame)
      3. the foreground from the idle point on (at least one instruction) until an idle hook says it waits

    Idle hooks (HOOKS): $83E9 / $8541 / $864C wait for the NMI's update (DP $22 bit 1), $B7AD / $EEB0 for the vertical
    blank (the frame's end).  The vertical blank bit (EXTRA bit 3) reads 1 from the frame's start until the
    foreground reaches $B7A5 (the wait for the blank's end).
    A coin (or service: `coin(bits)`) stays pressed until the FIRQ has taken it: the FIRQ debounces it inside the
    handler and then waits for its release ($89C7), where the port releases it.  On the first coin of the attract mode the FIRQ restarts the
    foreground itself (LDS #$0FFF ... JMP $8156): an interrupt also ends at an idle hook that waits.
    The sprite MCU runs at once: a write to $380F runs its NMI handler to completion (the HD63701Y0 interpreter
    here, src/mcu.s on the STE) and sets $0E3E as the main CPU's IRQ handler would (the IRQ itself is not taken).
    The shared RAM is always reachable (the MCU never runs while the main CPU works); EXTRA bit 4 (bus free) follows
    the bank register's halt and reset bits."""
    HOOKS = {
        0x83E9: lambda m: not m.mem[0x22] & 2,
        0x8541: lambda m: not m.mem[0x22] & 2,
        0x864C: lambda m: not m.mem[0x22] & 2,
        0xB7AD: lambda m: True,
        0xEEB0: lambda m: True,
    }
    VBLANK_END = 0xB7A5
    COIN_WAIT = 0x89C7                    # the FIRQ's wait for the coins' release: the port's coin is released there

    def __init__(self, dsw0=DSW0, dsw1=DSW1):
        super().__init__(dsw0, dsw1)
        self.main = M6809(self.port_rd, self.port_wr)
        self.main.reset()
        self.mcu = HD63701Y0(load("21jm-0.ic55"), self.sub_rd, self.sub_wr)
        self.port_vblank = 1
        self.coins = 0                           # pressed: bit 6 coin 1, bit 7 coin 2 ($3801), bit 0 service ($3802)
        self.booted = False
        self.idle_pc = None
        self.mcu_jobs = 0

    # ---- memory: as the board's, without the sub CPU's timing ---------------------
    def port_rd(self, a):
        if a < 0x2000:
            return self.mem[a]
        if a < 0x2800:
            return self.comram[a & 0x1FF]
        if a < 0x3800:
            return self.mem[a]
        if a < 0x4000:
            if a == 0x3802:
                free = self.bankreg & 0x10 or not self.bankreg & 0x08
                return (self.inputs[2] & ~(self.coins & 1)) | (self.port_vblank << 3) | (0 if free else 0x10)
            if a == 0x3801:
                return self.inputs[1] & ~(self.coins & 0xC0)
            if a <= 0x3804:
                return self.inputs[a - 0x3800]
            return 0xFF
        if a < 0x8000:
            return self.rom[0x10000 + self.bank * 0x4000 + a - 0x4000]
        return self.rom[a]

    def port_wr(self, a, v):
        if a < 0x1800:
            if a < 0x1400:
                self.mem[a] = v
        elif a < 0x2000:
            self.mem[a] = v
        elif a < 0x2800:
            self.comram[a & 0x1FF] = v
        elif a < 0x3800:
            self.mem[a] = v
        elif a == 0x3808:
            self.bankreg = v
            self.bank = v >> 5
        elif a == 0x3809 or a == 0x380A:
            self.scroll_lo[a - 0x3809] = v
        elif a == 0x380E:
            self.sound_log.append((self.frame, v))
        elif a == 0x380F:
            self.mcu_job()

    def coin(self, bits):
        """press coin 1 ($40), coin 2 ($80) or service ($01) until the FIRQ took it"""
        self.coins |= bits

    def mcu_job(self):
        """the MCU's NMI handler to its RTI (back in its idle loop at $C02B), then $0E3E = 1"""
        c = self.mcu
        if not self.mcu_jobs:
            for _ in range(32):                      # (its reset code up to the idle loop)
                if c.pc == 0xC02B:
                    break
                c.step()
        c.set_nmi(True)
        c.set_nmi(False)
        c.check_irq_lines()
        for _ in range(2000000):
            if c.pc == 0xC02B:
                break
            c.step()
        else:
            raise RuntimeError("the MCU did not finish (pc %04X)" % c.pc)
        self.mcu_jobs += 1
        self.mem[0x0E3E] = 1

    # ---- the schedule -------------------------------------------------------------
    def run_to_idle(self, first=True, limit=5000000):
        c = self.main
        hooks = self.HOOKS
        for _ in range(limit):
            if not first:
                pc = c.pc
                if pc == self.VBLANK_END:
                    self.port_vblank = 0
                elif pc == self.COIN_WAIT:
                    self.coins = 0
                h = hooks.get(pc)
                if h is not None and h(self):
                    self.idle_pc = pc
                    return
            first = False
            c.step()
        raise RuntimeError("the foreground did not wait (pc %04X, frame %d)" % (c.pc, self.frame))

    def interrupt(self, vec, mask, set_bits):
        """the 6809's interrupt entry at the idle point, its handler up to the RTI back there"""
        c = self.main
        c.cc = (c.cc | 0x80) if mask == 0xFF else (c.cc & 0x7F)
        c.push_regs(mask)
        c.cc |= set_bits
        c.vector(vec)
        s0 = c.s
        hooks = self.HOOKS
        for _ in range(3000000):
            c.step()
            pc = c.pc
            if c.s == (s0 + (12 if mask == 0xFF else 3)) & 0xFFFF and pc == self.idle_pc:
                return True
            if pc == self.COIN_WAIT:
                self.coins = 0
            h = hooks.get(pc)
            if h is not None and h(self):         # (the handler restarted the foreground, which waits now)
                self.idle_pc = pc
                return False
        raise RuntimeError("the interrupt %04X did not return (frame %d)" % (vec, self.frame))

    def run_frame_port(self):
        if not self.booted:
            self.run_to_idle(first=False)
            self.booted = True
        self.port_vblank = 1
        if self.interrupt(0xFFFC, 0xFF, 0x50):        # NMI: E, I and F set
            if not self.main.cc & 0x40:
                if not self.interrupt(0xFFF6, 0x81, 0x50):     # FIRQ: PC and CC (E clear), I and F set
                    self.frame += 1
                    return
            self.run_to_idle()
        self.frame += 1
