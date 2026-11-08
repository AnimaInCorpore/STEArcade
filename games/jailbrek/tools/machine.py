"""Jail Break (MAME `jailbrek`, Konami GX507, 1986): the reference board, from MAME konami/jailbrek.cpp + k005849.cpp.

Main CPU: KONAMI-1 (MC6809E, opcodes encrypted, engine/m6809.py with konami1_opcode) at 18.432 MHz / 12 = 1.536 MHz.
Screen: 6.144 MHz pixel clock, 384 x 264 total, 240 x 224 visible (x 8-247, lines 16-239), 60.606 Hz: 25344 CPU
cycles a frame, 96 a line.  The Konami 005849 video chip runs a timer every 16 lines (0, 16, ..., 256):
    NMI   (ctrl $2044 bit 0) at the lines 16, 48, ..., 240 (8 a frame)
    IRQ   (bit 1) at line 240, FIRQ (bit 2) at line 240 of every other frame
    writing ctrl 4 with an enable bit 1 -> 0 clears that line.  flip screen = bit 3.
Memory map (main CPU):
    $0000-$07FF colour RAM   $0800-$0FFF video RAM   $1000-$10BF sprite RAM (48 x code, attr, x, y)
    $10C0-$1FFF RAM          $2000-$203F scroll RAM (r/w)   $2040-$2047 ctrl (w)   $3000 w coin counters
    $3100 r DSW2, w SN76489A   $3200 r DSW3   $3300 r SYSTEM, w watchdog   $3301 r P1  $3302 r P2  $3303 r DSW1
    $4000 w VLM5030 pins (bit 1 ST, bit 2 RST)   $5000 w VLM5030 data   $6000 r VLM5030 BSY   $8000-$FFFF ROM
    anything else reads 0 (MAME's unmapped value)
Video: a 64 x 32 tilemap of 8x8 4bpp tiles (1024: colour RAM bits 6-7 are code bits 8-9), scrolled per tile row in x
(ctrl 2 bit 2 clear; scroll RAM $00-$1F low byte, $20-$3F bit 0 = x bit 8) or per 16-pixel column in y (bit 2 set);
48 sprites 16x16 4bpp (512), x signed by attr bit 7, drawn first to last (the last on top).  Colours: a 32-entry
palette PROM (4-4-4 bits, pal4bit), 16 tile and 16 sprite colour sets through two 256x4 lookup PROMs; a sprite pixel
whose lookup entry is 0 is transparent.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809, konami1_opcode
import mamegfx as G

CPU_HZ = 1536000
LINE = 96
LINES = 264
FRAME = LINE * LINES                       # 25344
VBLANK_LINE = 240
VISIBLE = (8, 247, 16, 239)                # MAME's visible area (min_x, max_x, min_y, max_y)

# MAME's defaults: DSW1 1 coin 1 credit ($FF); DSW2 3 lives ($01), upright, bonus 30K 70K+ ($08), difficult ($10),
# unused bit 6, demo sounds on; DSW3 flip off, single controls
DSW1, DSW2, DSW3 = 0xFF, 0x59, 0x0F


def load(name):
    return (EXTRACTED / "jailbrek" / name).read_bytes()


def pens_rgb(prom):
    """The 512 pens' RGB (MAME jailbrek_state::palette): pal4bit of the PROM nibbles (red, green; blue at $20); the
    lookup PROMs at $40 (tiles -> palette 16-31, pens 0-255) and $140 (sprites -> 0-15, pens 256-511)."""
    pal = np.array([[(prom[i] & 15) * 17, (prom[i] >> 4) * 17, (prom[0x20 + i] & 15) * 17] for i in range(32)], np.uint8)
    idx = [(prom[0x40 + i] & 15) | 16 for i in range(256)] + [prom[0x140 + i] & 15 for i in range(256)]
    return pal[idx]


class Video:
    def __init__(self):
        prom = load("507j10.1f") + load("507j11.2f") + load("507j13.7f") + load("507j12.6f")
        tiles = load("507l08.4f") + load("507j09.5f")
        spr = b"".join(load(n) for n in ("507j04.3e", "507j05.4e", "507j06.5e", "507j07.3f"))
        self.tiles = G.decode_gfx(tiles, 8, 8, len(tiles) // 32, [0, 1, 2, 3], list(range(0, 32, 4)),
                                  list(range(0, 256, 32)), 256)                       # gfx_8x8x4_packed_msb
        sx = list(range(0, 32, 4)) + list(range(256, 288, 4))
        sy = list(range(0, 256, 32)) + list(range(512, 768, 32))
        self.sprites = G.decode_gfx(spr, 16, 16, len(spr) // 128, [0, 1, 2, 3], sx, sy, 1024)  # ..row_2x2_group_packed_msb
        self.sprites = self.sprites.astype(np.int16)
        self.pens = pens_rgb(prom)
        self.lut = np.array([prom[0x140 + i] & 15 for i in range(256)], np.uint8)

    def render_raw(self, mem, flip=False):
        """The screen's pens [256 rows, 256] (rows 16-239, columns 8-247 visible) from the main CPU's memory (the
        scroll RAM at $2000 and ctrl 2 at $2042 included, as the machine keeps them)."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        cram = np.frombuffer(bytes(mem[0x0000:0x0800]), np.uint8).reshape(32, 64)
        vram = np.frombuffer(bytes(mem[0x0800:0x1000]), np.uint8).reshape(32, 64)
        codes = vram.astype(np.int32) + 4 * (cram & 0xC0).astype(np.int32)
        zero = np.zeros_like(cram)
        pix, _ = G.tile_pixmap(self.tiles, codes, cram & 15, zero, zero, 32, 64, 0, 16)
        sc = mem[0x2000:0x2040]
        scr = [sc[i] | (sc[i | 0x20] & 1) << 8 for i in range(32)]
        if mem[0x2042] & 4:                    # column scroll: 16-pixel columns, y
            xs = np.arange(512)
            cols = np.array(scr)[xs // 16]
            bm = np.empty((256, 512), pix.dtype)
            for y in range(256):
                bm[y] = pix[(y + cols) % 256, xs]
            bm = bm[:, :256].astype(np.int16)
        else:
            bm = G.scroll_rows(pix, scr, 256)[:, :256].astype(np.int16)
        sr = mem[0x1000:0x10C0]
        lut = self.lut
        for i in range(0, 0xC0, 4):
            attr = sr[i + 1]
            code = sr[i] + ((attr & 0x40) << 2)
            color = attr & 15
            x = sr[i + 2] - ((attr & 0x80) << 1)
            y = sr[i + 3]
            trans = lut[color * 16:color * 16 + 16] == 0
            G.draw_gfx(bm, VISIBLE, self.sprites, code, 256 + color * 16, attr & 0x10, attr & 0x20, x, y,
                       lambda s: trans[s])
        return bm

    def render_rgb(self, mem, flip=False):
        """The visible picture [224, 240, 3] as MAME's snapshot shows it."""
        raw = self.render_raw(mem, flip)[VISIBLE[2]:VISIBLE[3] + 1, VISIBLE[0]:VISIBLE[1] + 1]
        return self.pens[raw]


VLM_RATE = 3579545 / 440                   # the VLM5030's sample rate (MAME: clock / 440)


class Vlm:
    """The VLM5030's BSY pin as MAME's vlm5030.cpp drives it (the speech itself is not made here): ST low -> high
    raises BSY; ST high -> low starts the phrase at the address of the table entry the data latch names; BSY falls
    when the phrase's frames (6 bytes each, silent frames and the end mark by their command byte) have run their
    samples, on MAME's sample grid (clock / 440).  RST high -> low latches the speed parameter, low -> high resets a
    busy chip."""
    def __init__(self, rom):
        self.rom = rom                     # 8 KB (the address bus has 13 bits)
        self.latch = 0
        self.st = self.rst = 0
        self.bsy_on = False
        self.end_sample = None             # the sample at which BSY falls
        self.frame_size = 40               # 160 / 4 samples per interpolator (the normal speed)
        self.step = 1

    @staticmethod
    def sample(cycles):
        return int(cycles * VLM_RATE / CPU_HZ)

    def bsy(self, cycles):
        if self.bsy_on and self.end_sample is not None and self.sample(cycles) >= self.end_sample:
            self.bsy_on = False
            self.end_sample = None
        return int(self.bsy_on)

    def setup(self, param):
        self.step = 4 if param & 2 else 2 if param & 1 else 1
        self.frame_size = (40, 30, 20, 20, 40, 60, 50, 50)[(param >> 3) & 7]      # MAME's vlm5030_speed_table

    def pins(self, cycles, v):
        self.bsy(cycles)
        self.st_w(cycles, v >> 1 & 1)
        self.rst_w(cycles, v >> 2 & 1)

    def rst_w(self, cycles, state):
        if state != self.rst:
            self.rst = state
            if not state:
                self.setup(self.latch)
            elif self.bsy_on:                  # reset
                self.bsy_on, self.end_sample = False, None
                self.setup(0)

    def st_w(self, cycles, state):
        if state == self.st:
            return
        self.st = state
        if state:
            self.bsy_on = True
            self.end_sample = None
            return
        table = (self.latch & 0xFE) + ((self.latch & 1) << 8)
        addr = (self.rom[table & 0x1FFF] << 8) | self.rom[(table + 1) & 0x1FFF]
        f, step = self.frame_size, self.step
        periods, interp, phase = 1, 4, 'run'
        while True:
            if phase == 'stop':
                break
            if interp == 0:
                cmd = self.rom[addr & 0x1FFF]
                if cmd & 1:
                    addr += 1
                    if cmd & 2:
                        interp, phase = 4, 'stop'
                    else:
                        interp = ((cmd >> 2) + 1) * 2 * 4
                else:
                    addr += 6
                    interp = 4
            interp -= step
            periods += 1
            if periods > 100000:
                break
        self.end_sample = self.sample(cycles) + periods * f
        self.bsy_on = True

    def data_w(self, v):
        self.latch = v


class JailBreak:
    def __init__(self, dsw1=DSW1, dsw2=DSW2, dsw3=DSW3, firq_parity=1, slack=0):
        rom = bytearray(0x10000)
        rom[0x8000:0xC000] = load("507p03.11d")
        rom[0xC000:0x10000] = load("507p02.9d")
        self.rom = bytes(rom)
        self.mem = bytearray(0x10000)      # RAM, the scroll RAM at $2000 and the ctrl registers at $2040, the ROM
        self.mem[0x8000:] = self.rom[0x8000:]
        self.system = self.p1 = self.p2 = 0xFF
        self.dsw1, self.dsw2, self.dsw3 = dsw1, dsw2, dsw3
        self.ctrl = [0] * 8
        self.sound_log = []                # (frame, 'sn' | 'pins' | 'vlm', value)
        self.watchdog = 0
        self.frame = 0
        self.firq_parity = firq_parity
        self.trace = None                  # a list: (line since power-on, ctrl register, value) of every ctrl write
        self.mame248 = False               # the 0.248 binary's interrupt schedule (run_frame_248)
        self.nmi_next = 3072
        self.slack = slack                 # CPU cycles run after line 240's events before the frame is taken
        self.cpu = M6809(self.rd, self.wr, konami1_opcode(self.rd))
        self.video = None
        self.cpu.reset()
        self.line = 0                      # the next 005849 timer event's line
        self.base = 0                      # the cycle at which the current frame's line 0 starts
        self.vlm_rom = load('507l01.8c')[:0x2000]
        self.vlm = Vlm(self.vlm_rom)

    def rd(self, a):
        if a < 0x2040 or a >= 0x8000:
            return self.mem[a]
        if 0x3100 <= a <= 0x3303:
            if a == 0x3100:
                return self.dsw2
            if a == 0x3200:
                return self.dsw3
            if a >= 0x3300:
                return (self.system, self.p1, self.p2, self.dsw1)[a & 3]
        if a == 0x6000:
            return self.vlm.bsy(self.cpu.cycles)
        return 0

    def wr(self, a, v):
        if a < 0x2040:
            self.mem[a] = v
        elif a < 0x2048:
            self.ctrl_w(a & 7, v)
        elif a == 0x3100:
            self.sound_log.append((self.frame, 'sn', v))
        elif a == 0x3300:
            self.watchdog += 1
        elif a == 0x4000:
            self.sound_log.append((self.frame, 'pins', v))
            self.vlm.pins(self.cpu.cycles, v)
        elif a == 0x5000:
            self.sound_log.append((self.frame, 'vlm', v))
            self.vlm.data_w(v)

    def ctrl_w(self, n, v):
        c = self.cpu
        if n == 4:
            old = self.ctrl[4]
            if ~v & old & 2:
                c.set_irq(False)
            if ~v & old & 4:
                c.set_firq(False)
            if ~v & old & 1:
                c.set_nmi(False)
        self.ctrl[n] = v
        self.mem[0x2040 + n] = v
        if self.trace is not None:
            self.trace.append((self.cpu.cycles / LINE, n, v))

    def timer(self, line):
        """the 005849's scanline timer at a line"""
        c = self.cpu
        if self.ctrl[4] & 1 and line & 0x1F == 0x10:
            c.set_nmi(True)
        if line == VBLANK_LINE:
            if self.ctrl[4] & 4 and (self.frame + self.firq_parity) & 1:
                c.set_firq(True)
            if self.ctrl[4] & 2:
                c.set_irq(True)

    def run_frame_248(self):
        """The behaviour of the MAME 0.248 binary (measured, ref/mame_ctrl_trace.py; the 0.286 source differs): the NMI
        every 32 lines (3072 cycles) from power-on, not tied to the frame, while ctrl 4 bit 0 is set; the IRQ at the
        frame's end (the screen's time origin is its vblank start: the timer's line 0 is 24 lines after it) while
        bit 1 is set.  Runs to the frame_done callback's instant, the IRQ's."""
        c = self.cpu
        end = (self.frame + 1) * FRAME
        while True:
            t = min(self.nmi_next, end)
            c.run(t - c.cycles)
            if t == self.nmi_next:
                self.nmi_next += 3072
                if self.ctrl[4] & 1:
                    c.set_nmi(True)
                    c.set_nmi(False)               # (a pulse)
            if t == end:
                break
        if self.ctrl[4] & 2:
            c.set_irq(True)
        self.frame += 1

    def run_frame(self):
        """Runs to line 240's timer event (including it): the state MAME's frame_done callback sees."""
        if self.mame248:
            return self.run_frame_248()
        c = self.cpu
        while True:
            line = self.line
            c.run(self.base + line * LINE - c.cycles)
            self.timer(line)
            if line + 16 >= LINES:
                self.line = 0
                self.base += FRAME
            else:
                self.line = line + 16
            if line == VBLANK_LINE:
                break
        if self.slack:
            c.run(self.base + VBLANK_LINE * LINE + self.slack - c.cycles)
        self.frame += 1

    def render_rgb(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, bool(self.ctrl[4] & 8))


class JailBreakPort(JailBreak):
    """The STE runtime's schedule (src/jailbrek.s), one call of run_frame_port an arcade frame.

    The foreground is a task loop: $8073 LDX <$3C; LDD ,X; ASLA; BCS $8073 (the queue's read pointer at $153C, the
    queue at $14C0-$14FF; an entry with bit 7 set is empty); the NMI handler ($B05D, eight a frame while ctrl 4 bit 0
    is set) steps the random generators and polls the speech chip, the IRQ handler ($8A57, at the VBLANK while ctrl 4
    bit 1 is set) plays the game and queues the tasks.  The port's idle point is $8073 with an empty queue: there each
    interrupt is delivered with $8073 as its return address, and the foreground runs the queued tasks until the queue
    is empty again.  A frame is seven NMIs, then the eighth with the IRQ behind it (the arcade's order at line 240).
    The boot: from the reset to the first idle.

    The speech chip's BSY pin is counted in NMIs (one NMI = 32 lines = 3072 CPU cycles = 16.27 speech samples): ST
    rising raises it, ST falling starts the phrase of the data latch's table entry at the speed the last RST falling
    edge latched, and it falls that many NMIs later (the handler that polls it runs before the count goes down).
    """
    IDLE = 0x8073
    NMI = 0xB05D
    IRQ = 0x8A57
    QPTR = 0x153C
    SAMPLES_PER_NMI = VLM_RATE * 32 * LINE / CPU_HZ

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.booted = False
        self.irqs = self.nmis = 0
        self.bsy = 0
        self.bsy_left = 0                  # NMIs until BSY falls (when a phrase runs)
        self.speed = self.step_bits = 0
        self.latch = 0
        self.st = self.rst = 0

    def rd(self, a):
        if a == 0x6000:
            return self.bsy
        return super().rd(a)

    def wr(self, a, v):
        if a == 0x4000:
            self.sound_log.append((self.frame, 'pins', v))
            st, rst = v >> 1 & 1, v >> 2 & 1
            if st != self.st:
                self.st = st
                if st:
                    self.bsy, self.bsy_left = 1, 0
                else:
                    self.bsy_left = vlm_nmis(self.vlm_rom, self.latch, self.speed, self.step_bits)
            if rst != self.rst:
                self.rst = rst
                if not rst:
                    self.speed, self.step_bits = self.latch >> 3 & 7, self.latch & 3
                elif self.bsy:
                    self.bsy = self.bsy_left = 0
                    self.speed = self.step_bits = 0
        elif a == 0x5000:
            self.sound_log.append((self.frame, 'vlm', v))
            self.latch = v
        else:
            super().wr(a, v)

    def waits(self):
        m = self.mem
        return m[(m[self.QPTR] << 8) | m[self.QPTR + 1]] & 0x80 != 0

    def run_to_idle(self, limit=20000000):
        """the foreground (at least one instruction) until the task queue is empty at the idle point"""
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc == self.IDLE and self.waits():
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def nmi_tick(self):
        c = self.cpu
        c.set_nmi(True)
        c.step()                                      # (the entry: the state pushed, PC = the vector)
        assert c.pc == self.NMI, hex(c.pc)
        self.nmis += 1
        self.run_to_idle()
        if self.bsy_left:
            self.bsy_left -= 1
            if not self.bsy_left:
                self.bsy = 0

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        for i in range(8):
            if self.ctrl[4] & 1:
                self.nmi_tick()
        if self.ctrl[4] & 2 and not c.cc & 0x10:
            c.set_irq(True)
            c.step()
            assert c.pc == self.IRQ, hex(c.pc)
            self.irqs += 1
            self.run_to_idle()
        self.frame += 1


def vlm_nmis(rom, latch, speed, step_bits):
    """NMIs a phrase keeps BSY high (see Vlm.st_w: the same frame walk, in speech samples, then in NMIs)"""
    f = (40, 30, 20, 20, 40, 60, 50, 50)[speed]
    step = 4 if step_bits & 2 else 2 if step_bits & 1 else 1
    table = (latch & 0xFE) + ((latch & 1) << 8)
    addr = (rom[table & 0x1FFF] << 8) | rom[(table + 1) & 0x1FFF]
    periods, interp, stop = 1, 4, False
    while not stop and periods < 100000:
        if interp == 0:
            cmd = rom[addr & 0x1FFF]
            if cmd & 1:
                addr += 1
                if cmd & 2:
                    interp, stop = 4, True
                else:
                    interp = ((cmd >> 2) + 1) * 2 * 4
            else:
                addr += 6
                interp = 4
        interp -= step
        periods += 1
    return max(1, -(-periods * f // int(JailBreakPort.SAMPLES_PER_NMI)))


if __name__ == "__main__":
    import time
    m = JailBreak()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, ctrl %s" % (time.time() - t, m.cpu.pc, m.ctrl))
