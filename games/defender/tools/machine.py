"""Defender (MAME `defender`, Williams 1980, Red label): the reference board, from MAME 0.286 midway/williams.cpp,
williams_m.cpp, williams_v.cpp and devices/machine/6821pia.cpp.

Main CPU: MC6809E at 12 MHz / 3 / 4 = 1 MHz (engine/m6809.py).  Screen: 8 MHz pixel clock, 512 x 260 total, visible
x 12-303, y 7-246 (292 x 240), 60.10 Hz, ROT0: 64 CPU cycles a line, 16,640 a frame.  No blitter on this board: the
CPU draws every pixel.

Memory map (main CPU):
    $0000-$BFFF  RAM: the video RAM (a 304 x 256 bitmap of 4 bpp, column-major: byte = (x / 2) * 256 + y, the even x
                 in the high nibble; $0000-$97FF) and the work RAM above it
    $C000-$CFFF  a view chosen by a write to $D000-$DFFF (data & 15): view 0 is the I/O below, views 1-7 are the 4 KB
                 banks of the "banked" ROM region (defend.9/.12, .8/.11, .7/.10, zero, zero, zero, .6 + zero), views
                 8-15 unmapped (read 0)
        $C000-$C00F  w  the palette, one byte a pen: bits 0-2 red, 3-5 green (1200, 560, 330 ohm), 6-7 blue (560, 330)
                        (mirror $03E0)
        $C010-$C01F  w  video control: bit 0 cocktail flip (mirror $03E0; upright: never set)
        $C3FF        w  watchdog ($39)
        $C400-$C4FF  rw CMOS, 4 bits: a write stores data | $F0 (mirror $0300; power-on all 0)
        $C800-$CBFF  r  the video counter: vpos & $FC (vpos < 256), else $FC
        $CC00-$CC03  rw PIA 1 (MAME's m_pia[1]): A = IN2 (coins, service), B = the sound command (out), CA1 = COUNT240
                        (1 from line 240), CB1 = VA11 (scanline bit 5, set at every 32nd line but 256); IRQA / IRQB ->
                        the CPU's IRQ
        $CC04-$CC07  rw PIA 0: A = IN0 (fire, thrust, smart bomb, hyperspace, starts, reverse, down), B = IN1 (up)
                        (mirror $03E0 for both PIAs)
    $D000-$FFFF  ROM (defend.1, .4, .2, .3); writes to $D000-$DFFF select the view
Sound: an M6808 with video_sound_rom_1.ic12 behind PIA 2; the main CPU only writes its port B (the command | $C0):
not emulated here, the commands are logged (frame, value).
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809
import mamegfx as G

CPU_HZ = 1000000
LINE = 64                                  # CPU cycles a line (512 pixels at 8 MHz)
LINES = 260
FRAME = LINE * LINES                       # 16640
START_LINE = 247                           # the beam at power-on: MAME's screen starts at its vertical blank (line 247), so
                                           # frame_done (the vertical blank) is at every FRAME cycles and the first line 0
                                           # at cycle 13 * LINE.  With the beam at line 0 instead the RAM was 832 cycles
                                           # behind MAME's at frame 60 and video RAM differed now and then from frame 11,500
VIS_X = (12, 303)
VIS_Y = (7, 246)


def load(name):
    return (EXTRACTED / "defender" / name).read_bytes()


PROGRAM = (("defend.1", 0xD000), ("defend.4", 0xD800), ("defend.2", 0xE000), ("defend.3", 0xF000))
BANKED = (("defend.9", 0x0000), ("defend.12", 0x0800), ("defend.8", 0x1000), ("defend.11", 0x1800),
          ("defend.7", 0x2000), ("defend.10", 0x2800), ("defend.6", 0x6000))


def palette_rgb():
    """The 256 colours of a palette byte (williams_state::palette_init: relative resistor weights, 0-255)."""
    rw, gw, bw = G.resistor_weights(0, 255, -1.0, ([1200, 560, 330], 0, 0), ([1200, 560, 330], 0, 0),
                                    ([560, 330], 0, 0))
    out = []
    for v in range(256):
        bit = [(v >> k) & 1 for k in range(8)]
        out.append((G.combine(rw, *bit[0:3]), G.combine(gw, *bit[3:6]), G.combine(bw, *bit[6:8])))
    return np.array(out, np.uint8)


PALETTE = palette_rgb()


class PIA:
    """MC6821 (MAME's pia6821_device), the parts Defender uses: ports with DDRs, C1 edges and IRQ flags, the C2
    pins' IRQ2 flags never set (no C2 inputs are wired)."""

    def __init__(self, in_a=lambda: 0xFF, in_b=None, out_b=None, irq=None):
        self.in_a, self.in_b, self.out_b_cb, self.irq_cb = in_a, in_b, out_b, irq
        self.out_a = self.out_b = self.ddr_a = self.ddr_b = self.ctl_a = self.ctl_b = 0
        self.irq_a1 = self.irq_b1 = False
        self.ca1, self.cb1 = 1, 0               # m_in_ca1(true), m_in_cb1(0)
        self.irq_a = self.irq_b = 0

    def _update(self):
        a = int(self.irq_a1 and self.ctl_a & 1)
        b = int(self.irq_b1 and self.ctl_b & 1)
        if (a, b) != (self.irq_a, self.irq_b):
            self.irq_a, self.irq_b = a, b
            if self.irq_cb:
                self.irq_cb()

    def read(self, r):
        r &= 3
        if r == 0:
            if not self.ctl_a & 4:
                return self.ddr_a
            v = (~self.ddr_a & self.in_a()) | (self.ddr_a & self.out_a)
            self.irq_a1 = False
            self._update()
            return v & 0xFF
        if r == 1:
            return self.ctl_a | (0x80 if self.irq_a1 else 0)
        if r == 2:
            if not self.ctl_b & 4:
                return self.ddr_b
            if self.ddr_b == 0xFF:
                v = self.out_b
            else:
                v = (self.out_b & self.ddr_b) | ((self.in_b() if self.in_b else 0) & ~self.ddr_b)
            self.irq_b1 = False
            self._update()
            return v & 0xFF
        return self.ctl_b | (0x80 if self.irq_b1 else 0)

    def write(self, r, v):
        r &= 3
        if r == 0:
            if self.ctl_a & 4:
                self.out_a = v
            else:
                self.ddr_a = v
        elif r == 1:
            self.ctl_a = v & 0x3F
            self._update()
        elif r == 2:
            if self.ctl_b & 4:
                self.out_b = v
                if self.out_b_cb:
                    self.out_b_cb(v)
            else:
                self.ddr_b = v
        else:
            self.ctl_b = v & 0x3F
            self._update()

    def set_ca1(self, s):
        if s != self.ca1 and ((s and self.ctl_a & 2) or (not s and not self.ctl_a & 2)):
            self.irq_a1 = True
            self._update()
        self.ca1 = s

    def set_cb1(self, s):
        if s != self.cb1 and ((s and self.ctl_b & 2) or (not s and not self.ctl_b & 2)):
            self.irq_b1 = True
            self._update()
        self.cb1 = s


def render_pixels(mem):
    """The visible picture's pen numbers [240, 292] from the main CPU's video RAM (64 KB image)."""
    v = np.frombuffer(bytes(mem[0:0x9800]), np.uint8).reshape(152, 256)     # [x / 2, y]
    px = np.empty((256, 304), np.uint8)
    px[:, 0::2] = (v >> 4).T
    px[:, 1::2] = (v & 15).T
    return px[VIS_Y[0]:VIS_Y[1] + 1, VIS_X[0]:VIS_X[1] + 1]


def render_rgb(mem, palette_ram):
    return PALETTE[np.array(palette_ram, np.uint8)][render_pixels(mem)]


def factory_cmos():
    """The CMOS a blank board writes on its first boot (factory settings, the high score table; MAME's nvram is all 0
    at first, so it opens the bookkeeping menu once): booting with it goes to the attract mode."""
    m = Defender()
    for _ in range(1200):                          # (written after the power-on tests, between frames 600 and 1200)
        m.run_frame()
    return bytes(m.cmos)


class Defender:
    def __init__(self, cmos=None):
        self.rom = bytearray(0x10000)
        for n, a in PROGRAM:
            d = load(n)
            self.rom[a:a + len(d)] = d
        self.banked = bytearray(0x7000)
        for n, a in BANKED:
            d = load(n)
            self.banked[a:a + len(d)] = d
        self.mem = bytearray(0x10000)              # RAM $0000-$BFFF (and the ROM copy above, for convenience)
        self.mem[0xD000:] = self.rom[0xD000:]
        self.palette = bytearray(16)
        self.cmos = bytearray(cmos or 0x100)       # nvram DEFAULT_ALL_0 unless given (factory_cmos)
        self.view = 0
        self.cocktail = 0
        self.in0 = self.in1 = self.in2 = 0         # active high
        self.sound_log = []
        self.frame = 0
        self.pia0 = PIA(in_a=lambda: self.in0, in_b=lambda: self.in1)
        self.pia1 = PIA(in_a=lambda: self.in2, out_b=self._snd, irq=self._irq)
        self.cpu = M6809(self.rd, self.wr)
        self.cpu.reset()
        self.events = self._events()
        self.next_event = next(self.events)
        self.next_done = FRAME

    # ---- board -------------------------------------------------------------
    def _irq(self):
        self.cpu.set_irq(bool(self.pia1.irq_a or self.pia1.irq_b))

    def _snd(self, v):
        self.sound_log.append((self.frame, v | 0xC0))

    def _events(self):
        """(cycle, kind, value): VA11 into CB1 at lines 0, 32, ... 224 (scanline bit 5; never at 256), COUNT240 into
        CA1 at lines 0 (0) and 240 (1).  The beam is at line START_LINE at cycle 0."""
        base = (LINES - START_LINE) * LINE
        while True:
            for line in range(0, 256, 32):
                yield (base + line * LINE, "cb1", (line >> 5) & 1)
                if line == 0:
                    yield (base, "ca1", 0)
                if line == 224:
                    yield (base + 240 * LINE, "ca1", 1)
            base += FRAME

    def vpos(self):
        """The beam's line at a read of the video counter.  The program reads it only with LDA $C800 (extended, $DF26
        and $DF3C): MAME's core counts all 5 of its cycles before the read, the reference's cycles are the
        instruction's start."""
        return ((self.cpu.cycles + 5 + START_LINE * LINE) % FRAME) // LINE

    def rd(self, a):
        if a < 0xC000 or a >= 0xD000:
            return self.mem[a]
        if self.view:
            if self.view <= 7:
                return self.banked[(self.view - 1) * 0x1000 + (a & 0xFFF)]
            return 0
        o = a & 0xFFF
        if 0x400 <= o < 0x800:
            return self.cmos[o & 0xFF]
        if 0x800 <= o < 0xC00:
            v = self.vpos()
            return v & 0xFC if v < 0x100 else 0xFC
        if o >= 0xC00:
            r = o & 0x1F
            if r < 4:
                return self.pia1.read(r)
            if r < 8:
                return self.pia0.read(r)
        return 0

    def wr(self, a, v):
        if a < 0xC000:
            self.mem[a] = v
            return
        if a >= 0xD000:
            if a < 0xE000:
                self.view = v & 15
            return
        if self.view:
            return                                  # ROM
        o = a & 0xFFF
        if o < 0x400:
            if o == 0x3FF:
                return                              # watchdog
            r = o & 0x1F
            if r < 0x10:
                self.palette[r] = v
            else:
                self.cocktail = v & 1
        elif o < 0x800:
            self.cmos[o & 0xFF] = v | 0xF0
        elif o >= 0xC00:
            r = o & 0x1F
            if r < 4:
                self.pia1.write(r, v)
            elif r < 8:
                self.pia0.write(r, v)

    # ---- time --------------------------------------------------------------
    def run_until(self, t):
        c = self.cpu
        while True:
            et = self.next_event[0]
            if et > t:
                break
            if c.cycles < et:
                c.run(et - c.cycles)
            _, kind, val = self.next_event
            if kind == "cb1":
                self.pia1.set_cb1(val)
            else:
                self.pia1.set_ca1(val)
            self.next_event = next(self.events)
        if c.cycles < t:
            c.run(t - c.cycles)

    def run_frame(self):
        """Runs to the next vertical blank (line 247): the state MAME's frame_done callback sees."""
        self.run_until(self.next_done)
        self.next_done += FRAME
        self.frame += 1

    def render_rgb(self):
        return render_rgb(self.mem, self.palette)


if __name__ == "__main__":
    import time
    m = Defender()
    t = time.time()
    for _ in range(600):
        m.run_frame()
    print("600 frames in %.1f s, pc %04X, sound commands %d" % (time.time() - t, m.cpu.pc, len(m.sound_log)))
    from PIL import Image
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("defender_ref.png")
    Image.fromarray(m.render_rgb()).save(out)
    print(out)


class DefenderPort(Defender):
    """The STE runtime's schedule (src/defender.s), one call of run_frame_port an arcade frame.

    The foreground waits at $E7C3 (LDA <$5D; BEQ $E7C3) for the IRQ's frame count; the IRQ ($DF17, by the RAM vector's
    JMP at $A08F) does its work in two passes a frame, told apart by the video counter: at line 0 (beam < $80: the count
    $A05D raised, the palette copied while the beam is <= 8, the lower half drawn) and at line 128 (beam >= $80: the
    upper half, its boundary $A2 from a second read at $DF3C); the IRQs at lines 64 and 192 do nothing.  The port's idle
    point is $E7C3 with $A05D = 0: there the line-128 pass is delivered (the counter reads $80, then $98: the arcade's
    $DF3C read is line 151-152 in most frames of play), then the line-0 pass (the counter reads 0), each with $E7C3 as
    the return address; after the second the foreground runs the frame and comes back to the idle point.  No IRQ is
    delivered while CC's I is set.  The PIAs' interrupt lines are not used (no line events); their registers are.
    The boot: the power-on tests are skipped (12.2 million cycles; they keep their state in DP, which the translation
    keeps only as data): the CPU starts at $D738 (ORCC #$FF; LDS #$BFFF; DP = $A0; the PIAs, the RAM $9C00-$BFFF
    cleared), where the tests go when they pass; the video RAM is then 0, not the tests' patterns.
    """
    START = 0xD738
    IDLE = 0xE7C3
    IRQ = 0xDF17
    FLAG = 0xA05D
    PASS_LOW = (0x80, 0x98)
    PASS_TOP = (0x00,)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cpu.pc = self.START
        self.booted = False
        self.vq = []
        self.irqs = 0

    def _irq(self):
        pass

    def vpos(self):
        if not self.vq:
            raise RuntimeError('a video counter read the schedule does not answer (pc %04X, frame %d)' %
                               (self.cpu.pc, self.frame))
        return self.vq.pop(0)

    def run_to_idle(self, limit=50000000):
        """the foreground (at least one instruction) until it waits at the idle point"""
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc == self.IDLE and self.mem[self.FLAG] == 0:
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def irq(self, reads):
        c = self.cpu
        if c.cc & 0x10:
            return False
        self.vq = list(reads)
        c.set_irq(True)
        c.step()                                  # (the entry: the state pushed, I set, PC = the vector: $A08F)
        c.set_irq(False)
        c.step()                                  # (JMP $DF17)
        assert c.pc == self.IRQ, hex(c.pc)
        self.irqs += 1
        self.run_to_idle()
        if self.vq:
            raise RuntimeError('video counter reads left over: %s (frame %d)' % (self.vq, self.frame))
        return True

    def run_frame_port(self):
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        if self.irq(self.PASS_LOW):
            self.irq(self.PASS_TOP)
        self.frame += 1
