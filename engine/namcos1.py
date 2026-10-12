"""Namco System 1 reference board (MAME namco/namcos1.cpp, namcos1_m.cpp, namcos1_v.cpp, c117.cpp,
namco_c116.cpp, namco_c123tmap.cpp, namcos1_sprite.cpp): Pac-Mania, Galaga '88, Splatterhouse, Dragon Spirit.

CPUs: main and sub MC6809E (engine/m6809.py) behind the CUS117 MMU, the sound MC6809E, the HD63701 MCU
(engine/hd63701.py), all at 1.536 MHz; a frame is 384 x 264 pixel clocks at 6.144 MHz = 25344 CPU cycles
(60.606 Hz), 96 a line.  The CPUs interleave as MAME's scheduler runs them (`timeslice`: 1/38400 s quanta in device
order, cut at every timer; an input line change is a synchronize() timer that ends the running CPU's slice), so a
run follows MAME's own instruction for instruction.

CUS117: each 6809 sees eight 8 KB banks, each pointing anywhere in a 23 bit virtual space (`offsets`).
Writes to $E000-$FFFF are the MMU's registers: $E000 + 2n even/odd = bank n bits 22-21 / 20-13, $F000 sub
reset (SUBRES: the sub CPU, the sound CPU and the MCU run only while bit 0 is 1), $F200 watchdog, $F600 IRQ
ack, $F800 FIRQ ack, $FA00 FIRQ to the sub CPU, $FC00 the sub CPU's bank 7 (main CPU only).

Virtual space: 2C0000 3D glasses, 2E0000-2E7FFF CUS116 palette (R, G, B planes of 2048 pens, registers at
x800 + 16), 2F0000-2F7FFF CUS123 tile RAM (big endian words), 2F8000-2F9FFF key custom, 2FC000-2FC7FF
scratch RAM, 2FC800-2FCFFF sprite RAM, 2FD000 (mirror FE0) CUS123 control, 2FE000-2FE3FF (mirror C00) CUS30
sound RAM, 2FF000-2FF7FF (mirror 800) TRIRAM shared by all four CPUs, 300000-307FFF RAM, 400000-7FFFFF ROM.

Interrupts: the vertical blank's start (line 240) asserts IRQ on main and sub (acknowledged at $F600), its
end (line 16, the first visible line) IRQ on the sound CPU ($E000) and IRQ1 on the MCU ($F000 of its map);
the YM2151's timers drive the sound CPU's FIRQ.  The sprite list is latched at the vblank's start when the
program wrote $7F2 of the sprite RAM.

The key custom of each game: type 1 (Dragon Spirit CUS136: 16/8 division), type 2 (Pac-Mania CUS151, Galaga '88 CUS153: 16/16 and 32/16 division), type 3
(Splatterhouse CUS181: key number and MAME's machine().rand(), whose seed is fixed).

MCU (MAME's mcu_map): $1000-$1003 DIP switches (one nibble, bit-reversed), $1400/$1401 the controls, $4000-$BFFF
the voice ROM bank ($D800), $C000-$C7FF TRIRAM, $C800-$CFFF EEPROM (non-volatile RAM, zero at power-on),
$D000/$D400 the DACs.  MAME's kludge: once the MCU wrote $A6 to TRIRAM[0] further writes there are ignored.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import EXTRACTED

CPU_HZ = 1536000
LINE = 96                       # CPU cycles a line (384 pixel clocks / 4)
LINES = 264
FRAME = LINE * LINES            # 25344
VBLANK_START = 240
VBLANK_END = 16
YM_HZ = 3579545
# MAME's scheduler in attoseconds (emu/schedule.cpp, attotime.h): integer periods, truncated as MAME truncates
AS = 10 ** 18
CPU_AS = AS // CPU_HZ                     # a CPU cycle (all four CPUs run at 1.536 MHz)
_SHIFT = 0
while (CPU_AS >> _SHIFT) >= 1 << 32:
    _SHIFT += 1
_DIV = CPU_AS >> _SHIFT                   # divu_64x32(delta >> divshift, divisor)
PIXEL_AS = AS // 6144000
SCAN_AS = 384 * PIXEL_AS
FRAME_AS = LINES * SCAN_AS
QUANTUM_AS = AS // 38400                  # set_maximum_quantum(attotime::from_hz(38400))
YM_AS = AS // YM_HZ
YM_RATE = YM_HZ // 64                     # the YM2151's sample rate (its total_clocks)
SOUND_UPDATE_AS = AS // 50                # sound_manager's periodic stream update (a timer: it splits slices)
VIS_X0, VIS_X1, VIS_Y0, VIS_Y1 = 73, 360, 16, 239   # MAME's visible area (bitmap coordinates)
WIDTH, HEIGHT = VIS_X1 - VIS_X0 + 1, VIS_Y1 - VIS_Y0 + 1    # 288 x 224

# The ROM sets (file names as in the archives, regions and loads as MAME's ROM_START):
#   ("main", name, start, "512"|"1024")  ROM_LOAD_512 / ROM_LOAD_1024 (mirrored over 512 KB)
#   ("voice", name, start, "hs")          ROM_LOAD_HS (a 64 KB ROM loaded twice)
GAMES = {
    "pacmania": dict(key=(2, 0x12), rot=270, files=[
        ("audio", "pn2_s0.bin", 0x00000), ("audio", "pn2_s1.bin", 0x10000),
        ("main", "pn_prg-6.bin", 0x300000, "1024"), ("main", "pn2_p7.bin", 0x380000, "512"),
        ("voice", "pn2_v0.bin", 0x00000, "hs"),
        ("mask", "pn2_c8.bin", 0x00000),
        ("chr", "pn_chr-0.bin", 0x00000), ("chr", "pn_chr-1.bin", 0x20000),
        ("chr", "pn_chr-2.bin", 0x40000), ("chr", "pn_chr-3.bin", 0x60000),
        ("sprite", "pn_obj-0.bin", 0x00000), ("sprite", "pnx_obj1.bin", 0x20000)]),
    "galaga88": dict(key=(2, 0x31), rot=270, files=[
        ("audio", "g81_s0.bin", 0x00000), ("audio", "g81_s1.bin", 0x10000),
        ("main", "g81_p0.bin", 0x000000, "512"), ("main", "g81_p1.bin", 0x080000, "512"),
        ("main", "g81_p5.bin", 0x280000, "512"), ("main", "g8x_p6.bin", 0x300000, "512"),
        ("main", "g8x_p7.bin", 0x380000, "512")]
        + [("voice", "g81_v%d.bin" % i, 0x20000 * i, "hs") for i in range(6)]
        + [("mask", "g8_chr-8.bin", 0)]
        + [("chr", "g8_chr-%d.bin" % i, 0x20000 * i) for i in range(4)]
        + [("sprite", "g8_obj-%d.bin" % i, 0x20000 * i) for i in range(6)]),
    "dspirit": dict(key=(1, 0x36), rot=90, files=[
        ("audio", "ds1_s0.bin", 0x00000), ("audio", "ds1_s1.bin", 0x10000)]
        + [("main", "ds1_p%d.bin" % i, 0x80000 * i, "512") for i in range(6)]
        + [("main", "ds3_p%d.bin" % i, 0x80000 * i, "512") for i in (6, 7)]
        + [("voice", "ds1_v0.bin", 0x00000, "hs")]
        + [("voice", "ds_voi-%d.bin" % i, 0x20000 * i) for i in range(1, 5)]
        + [("mask", "ds_chr-8.bin", 0)]
        + [("chr", "ds_chr-%d.bin" % i, 0x20000 * i) for i in range(8)]
        + [("sprite", "ds_obj-%d.bin" % i, 0x20000 * i) for i in range(4)]
        + [("sprite", "ds1_o4.bin", 0x80000, "hs")]),
    "splatter": dict(key=(3, 181, 3, 4), rot=180, files=[
        ("audio", "sh1_snd0b.bin", 0x00000), ("audio", "sh1_snd1.bin", 0x10000)]
        + [("main", "sh1_prg%d.bin" % i, 0x80000 * i, "512") for i in range(5)]
        + [("main", "sh3_prg%d.bin" % i, 0x80000 * i, "512") for i in range(5, 8)]
        + [("voice", "sh_voi-%d.bin" % i, 0x20000 * i) for i in range(4)]
        + [("mask", "sh_chr-8.bin", 0)]
        + [("chr", "sh_chr-%d.bin" % i, 0x20000 * i) for i in range(6)]
        + [("sprite", "sh_obj-%d.bin" % i, 0x20000 * i) for i in range(8)]),
}
REGION_SIZE = {"audio": 0x20000, "main": 0x400000, "voice": 0xC0000, "mask": 0x20000, "chr": 0x100000,
               "sprite": 0x100000}


def load_regions(game, romdir=None):
    """The MAME regions of a set, PRG7's address bit 16 inverted as driver_init does."""
    romdir = romdir or str(EXTRACTED / game)
    regions = {k: bytearray(n) for k, n in REGION_SIZE.items()}
    for entry in GAMES[game]["files"]:
        region, name, start = entry[:3]
        with open(os.path.join(romdir, name), "rb") as f:
            data = f.read()
        mode = entry[3] if len(entry) > 3 else None
        if mode in ("512", "1024"):
            for k in range(0x80000 // len(data)):
                regions[region][start + k * len(data):start + (k + 1) * len(data)] = data
        elif mode == "hs":
            regions[region][start:start + len(data)] = data
            regions[region][start + len(data):start + 2 * len(data)] = data
        else:
            regions[region][start:start + len(data)] = data
    main = regions["main"]
    for i in range(0x380000, 0x400000, 0x20000):
        lo, hi = bytes(main[i:i + 0x10000]), bytes(main[i + 0x10000:i + 0x20000])
        main[i:i + 0x10000], main[i + 0x10000:i + 0x20000] = hi, lo
    with open(os.path.join(romdir, "cus64-64a1.mcu"), "rb") as f:
        regions["mcu"] = f.read()
    return regions


class YM2151:
    """What the sound CPU sees of the YM2151, as ymfm (3rdparty/ymfm, ymfm_opm.cpp / ymfm_fm.ipp) and MAME's
    ymfm_mame.h do it: timers A (64 x (1024 - A) clocks) and B (1024 x (256 - B)) as scheduler timers, the
    status flags (set only while the timer's IRQ enable bit is on), the IRQ line (synchronized into the sound
    CPU's FIRQ), the mode register written through a synchronize() timer, busy for 64 clocks after a data write.
    Other register writes are kept in `writes` (the music, for the sound tools)."""

    def __init__(self, board):
        self.b = board
        self.addr = 0
        self.regs = bytearray(256)
        self.status = 0
        self.irq_state = False
        self.running = [False, False]
        self.timer = [None, None]
        self.busy_end = 0
        self.writes = []                   # (attotime, register, value)

    def read_status(self):
        st = self.status & 3
        if self.b.now() < self.busy_end:
            st |= 0x80
        return st

    def write(self, port, v):
        if port == 0:
            self.addr = v
            return
        r = self.addr
        if r == 0x14:
            self.b.at_end(lambda: self.b.synchronize(lambda: self.mode_write(v)))
        else:
            self.regs[r] = v
            if r not in (0x10, 0x11, 0x12):
                self.writes.append((self.b.now(), r, v))
        self.b.at_end(self.set_busy)

    def set_busy(self):
        self.busy_end = self.b.now() + 64 * YM_AS

    def mode_write(self, v):
        self.regs[0x14] = v
        self.set_reset_status(0, ((v >> 4) & 1) | (((v >> 5) & 1) << 1))
        total = (self.b.now() * YM_RATE) // AS
        self.update_timer(1, v & 2, -(total & 15))
        self.update_timer(0, v & 1, 0)

    def update_timer(self, t, enable, delta):
        if enable and not self.running[t]:
            period = (1024 - ((self.regs[0x10] << 2) | (self.regs[0x11] & 3))) if t == 0 else 16 * (256 - self.regs[0x12])
            period += delta
            self.timer[t] = self.b.timer(self.b.now() + period * 64 * YM_AS, lambda: self.expired(t))
            self.running[t] = True
        elif not enable:
            if self.timer[t] is not None:
                self.b.cancel(self.timer[t])
                self.timer[t] = None
            self.running[t] = False

    def expired(self, t):
        self.timer[t] = None
        if self.regs[0x14] & (4 << t):
            self.set_reset_status(1 << t, 0)
        self.running[t] = False
        self.update_timer(t, 1, 0)

    def set_reset_status(self, set_, reset):
        self.status = (self.status | set_) & ~reset
        if self.b.executing is not None:
            self.b.synchronize(self.check_interrupts)
        else:
            self.check_interrupts()

    def check_interrupts(self):
        old = self.irq_state
        self.irq_state = bool(self.status & 3)
        if old != self.irq_state:
            self.b.set_line(2, "firq", self.irq_state)


class NamcoS1:
    def __init__(self, game, regions=None, cpus=True):
        """cpus=False: the video state only (the renderer checks)"""
        self.game = game
        info = GAMES[game]
        r = regions or load_regions(game)
        self.rom = bytes(r["main"])
        self.audio_rom = bytes(r["audio"])
        self.voice = bytes(r["voice"])
        self.mask_rom = bytes(r["mask"])
        self.chr_rom = bytes(r["chr"])
        self.sprite_rom = bytes(r["sprite"])
        self.mcu_rom = r["mcu"]
        self.pal = [bytearray(0x2000) for _ in range(3)]     # R, G, B of the 8192 pens
        self.c116_regs = [0] * 8
        self.vram = bytearray(0x8000)                         # CUS123 tile RAM as the CPU sees it
        self.control = bytearray(0x20)                        # CUS123 control
        self.scratch = bytearray(0x800)                       # 2FC000
        self.spriteram = bytearray(0x800)                     # 2FC800
        self.sound_ram = bytearray(0x400)                     # CUS30
        self.triram = bytearray(0x800)
        self.ram = bytearray(0x8000)                          # 300000
        self.snd_ram = bytearray(0x2000)                      # sound CPU 8000-9FFF
        self.nvram = bytearray(0x800)                         # MCU C800 (EEPROM)
        self.copy_sprites = False
        self.flip = False
        self.key = bytearray(8)
        kt = info["key"]
        self.key_type, self.key_id = kt[0], kt[1]
        self.key_reg, self.key_rng = (kt[2], kt[3]) if kt[0] == 3 else (-1, -1)
        self.key_quotient = self.key_reminder = self.key_numerator_high = 0
        self.rand_seed = 0x9D14ABD7          # running_machine::rand() (machine.cpp), MAME's own seed
        self.mcu_patch = 0
        self.sound_bank = 0
        self.voice_bank = 0
        self.dac = [0, 0]
        self.dac_writes = []
        self.dipsw = 0xFF
        self.control_in = [0xFF, 0xFF]
        self.coin_in = 0xF8                                  # COIN: bits 3-6 active low, 0-2 custom outputs
        self.frame = 0
        self.subres = 0
        self.wdog = 0
        self.offsets = [[0] * 8, [0] * 8]
        self.offsets[0][0] = self.offsets[0][1] = 0x180 * 0x2000
        self.offsets[0][7] = 0x3FF * 0x2000
        self.offsets[1][0] = 0x180 * 0x2000
        self.offsets[1][7] = 0x3FF * 0x2000
        self._chr = self._mask = self._spr = None
        # the scheduler (see run_frame)
        self.base = 0
        self.local = [0, 0, 0, 0]
        self.suspended = [False, True, True, True]   # CUS117's reset holds the sub CPU, the sound CPU and the MCU
        self.executing = None
        self.timers = []                              # [expire, seq, fn], sorted (MAME's timer list)
        self.seq = 0
        self.queues = {}                              # (cpu, line) -> pending states (device_input's event queue)
        self.stop = False
        self.vblank_due = False
        self.deferred = []
        self.aborted = False
        if cpus:
            self.make_cpus()

    def make_cpus(self):
        from m6809 import M6809
        from hd63701 import HD63701
        self.main = M6809(lambda a: self.mmu_rd(0, a), lambda a, v: self.mmu_wr(0, a, v))
        self.sub = M6809(lambda a: self.mmu_rd(1, a), lambda a, v: self.mmu_wr(1, a, v))
        self.snd = M6809(self.snd_rd, self.snd_wr)
        self.ym = YM2151(self)
        self.mcu = HD63701(self.mcu_rom, self.mcu_rd, self.mcu_wr, in_p1=lambda: self.coin_in,
                           out_p1=lambda v, ddr: None, out_p2=lambda v, ddr: None)
        self.mcu.on_rmcr = self.mcu_rmcr
        self.sci_timer = None
        self.cpus = [self.main, self.sub, self.snd, self.mcu]
        self.main.reset()
        self.local[0] = self.main.cycles * CPU_AS          # (the reset's 4 cycles are time too)
        # MAME's screen starts in the vertical blank (beam at line 240): the blank ends 40 lines in, the first
        # frame ends at the next blank's start; the scanline 0 timer comes 24 lines in
        self.timer(40 * SCAN_AS, self.vblank_end)
        self.timer(FRAME_AS, self.vblank_begin)
        self.timer(24 * SCAN_AS, self.scanline0)
        self.timer(SOUND_UPDATE_AS, self.sound_update)

    # ---- the virtual space -------------------------------------------------
    def vrd(self, a):
        if a >= 0x400000:
            return self.rom[a - 0x400000]
        if a >= 0x300000:
            return self.ram[a & 0x7FFF] if a < 0x308000 else 0
        if (a >> 15) == 0x2F0000 >> 15:
            return self.vram[a & 0x7FFF]
        if a >= 0x2FF000:
            return self.triram[a & 0x7FF]
        if a >= 0x2FE000:
            return self.sound_ram[a & 0x3FF]
        if a >= 0x2FD000:
            return self.control[a & 0x1F]
        if a >= 0x2FC800:
            return self.spriteram[a & 0x7FF]
        if a >= 0x2FC000:
            return self.scratch[a & 0x7FF]
        if 0x2F8000 <= a < 0x2FA000:
            return self.key_rd(a - 0x2F8000)
        if 0x2E0000 <= a < 0x2E8000:
            return self.c116_rd(a & 0x7FFF)
        return 0

    def vwr(self, a, v):
        if a >= 0x400000:
            return
        if a >= 0x300000:
            if a < 0x308000:
                self.ram[a & 0x7FFF] = v
        elif (a >> 15) == 0x2F0000 >> 15:
            self.vram[a & 0x7FFF] = v
        elif a >= 0x2FF000:
            self.triram[a & 0x7FF] = v
        elif a >= 0x2FE000:
            self.sound_ram[a & 0x3FF] = v
        elif a >= 0x2FD000:
            self.control[a & 0x1F] = v
        elif a >= 0x2FC800:
            o = a & 0x7FF
            self.spriteram[o] = v
            if o == 0x7F2:
                self.copy_sprites = True
            elif o == 0x7F6:
                self.flip = bool(v & 1)
        elif a >= 0x2FC000:
            self.scratch[a & 0x7FF] = v
        elif 0x2F8000 <= a < 0x2FA000:
            self.key_wr(a - 0x2F8000, v)
        elif 0x2E0000 <= a < 0x2E8000:
            self.c116_wr(a & 0x7FFF, v)

    def c116_rd(self, o):
        plane = (o >> 11) & 3
        if plane == 3:
            reg = (o & 0xF) >> 1
            return self.c116_regs[reg] & 0xFF if o & 1 else self.c116_regs[reg] >> 8
        return self.pal[plane][((o & 0x6000) >> 2) | (o & 0x7FF)]

    def c116_wr(self, o, v):
        plane = (o >> 11) & 3
        if plane == 3:
            reg = (o & 0xF) >> 1
            r = self.c116_regs[reg]
            self.c116_regs[reg] = (r & 0xFF00) | v if o & 1 else (r & 0xFF) | (v << 8)
        else:
            self.pal[plane][((o & 0x6000) >> 2) | (o & 0x7FF)] = v

    def key_rd(self, o):
        if self.key_type == 1:
            if o < 3:
                d, n = self.key[0], (self.key[1] << 8) | self.key[2]
                q, r = (n // d, n % d) if d else (0xFFFF, 0)
                return (r, q >> 8, q & 0xFF)[o]
            return self.key_id if o == 3 else 0
        if self.key_type == 2:
            self.key_numerator_high = 0
            if o < 4:
                return (self.key_reminder >> 8, self.key_reminder & 0xFF,
                        self.key_quotient >> 8, self.key_quotient & 0xFF)[o]
            return self.key_id if o == 4 else 0
        op = (o & 0x70) >> 4
        if op == self.key_reg:
            return self.key_id
        if op == self.key_rng:
            self.rand_seed = (1664525 * self.rand_seed + 1013904223) & 0xFFFFFFFF
            return (self.rand_seed >> 16) & 0xFF        # (seed >> 16) | (seed << 16), the low byte
        return 0

    def key_wr(self, o, v):
        if self.key_type == 1:
            if o < 4:
                self.key[o] = v
        elif self.key_type == 2:
            if o < 5:
                self.key[o] = v
                if o == 3:
                    d = (self.key[0] << 8) | self.key[1]
                    n = (self.key_numerator_high << 16) | (self.key[2] << 8) | self.key[3]
                    if d:
                        self.key_quotient, self.key_reminder = (n // d) & 0xFFFF, (n % d) & 0xFFFF
                    else:
                        self.key_quotient, self.key_reminder = 0xFFFF, 0
                    self.key_numerator_high = (self.key[2] << 8) | self.key[3]
        else:
            self.key[(o & 0x70) >> 4] = v

    # ---- CUS117 --------------------------------------------------------------
    def mmu_rd(self, cpu, a):
        return self.vrd(self.offsets[cpu][a >> 13] | (a & 0x1FFF))

    def mmu_wr(self, cpu, a, v):
        if a < 0xE000:
            self.vwr(self.offsets[cpu][a >> 13] | (a & 0x1FFF), v)
            return
        reg = (a >> 9) & 0xF
        if reg < 8:
            bank = self.offsets[cpu][reg]
            if a & 1:
                self.offsets[cpu][reg] = (bank & 0x600000) | (v * 0x2000)
            else:
                self.offsets[cpu][reg] = (bank & 0x1FE000) | ((v & 3) * 0x200000)
        elif reg == 8 and cpu == 0:
            new = v & 1
            if new != self.subres:
                self.mcu_patch = 0
                for c in (1, 2, 3):
                    self.set_line(c, "reset", not new)
            self.subres = new
        elif reg == 11:
            self.set_line(cpu, "irq", False)
        elif reg == 12:
            self.set_line(cpu, "firq", False)
        elif reg == 13 and cpu == 0:
            self.set_line(1, "firq", True)
        elif reg == 14 and cpu == 0:
            self.offsets[1][7] = 0x600000 | (v * 0x2000)

    # ---- sound CPU ---------------------------------------------------------
    def snd_rd(self, a):
        if a < 0x4000:
            return self.audio_rom[self.sound_bank * 0x4000 + a]
        if a >= 0xC000:
            return self.audio_rom[a - 0xC000]
        if a < 0x5000:
            return self.ym.read_status() if a < 0x4002 else 0
        if a < 0x6000:
            return self.sound_ram[a & 0x3FF]
        if 0x7000 <= a < 0x8000:
            return self.triram[a & 0x7FF]
        if 0x8000 <= a < 0xA000:
            return self.snd_ram[a - 0x8000]
        return 0

    def snd_wr(self, a, v):
        if 0x4000 <= a < 0x4002:
            self.ym.write(a & 1, v)
        elif 0x5000 <= a < 0x6000:
            self.sound_ram[a & 0x3FF] = v
        elif 0x7000 <= a < 0x8000:
            self.triram[a & 0x7FF] = v
        elif 0x8000 <= a < 0xA000:
            self.snd_ram[a - 0x8000] = v
        elif 0xC000 <= a < 0xC002:
            self.sound_bank = (v & 0x70) >> 4
        elif a == 0xE000:
            self.set_line(2, "irq", False)

    # ---- MCU -----------------------------------------------------------------
    def mcu_rd(self, a):
        if 0x1000 <= a < 0x1004:
            nib = (self.dipsw >> 4) if a & 2 else self.dipsw & 0xF
            return 0xF0 | ((nib & 1) << 3) | ((nib & 2) << 1) | ((nib & 4) >> 1) | ((nib & 8) >> 3)
        if a == 0x1400 or a == 0x1401:
            return self.control_in[a & 1]
        if 0x4000 <= a < 0xC000:
            return self.voice[self.voice_bank * 0x8000 + a - 0x4000]
        if 0xC000 <= a < 0xC800:
            return self.triram[a & 0x7FF]
        if 0xC800 <= a < 0xD000:
            return self.nvram[a & 0x7FF]
        return 0

    def mcu_wr(self, a, v):
        if 0xC000 <= a < 0xC800:
            if a == 0xC000:
                if self.mcu_patch == 0xA6:
                    return
                self.mcu_patch = v
            self.triram[a & 0x7FF] = v
        elif 0xC800 <= a < 0xD000:
            self.nvram[a & 0x7FF] = v
        elif a == 0xD000 or a == 0xD400:
            self.dac[(a >> 10) & 1] = v
        elif a == 0xD800:
            sel = v & 0xFC
            bank = {0xF8: 0, 0xF4: 4, 0xEC: 8, 0xDC: 12, 0xBC: 16, 0x7C: 20}.get(sel, 0)
            if sel == 0xF8:
                v ^= 2
            self.voice_bank = bank + (v & 3)
        elif a == 0xF000:
            self.set_line(3, "irq", False)

    # ---- the scheduler (MAME's device_scheduler) ----------------------------
    def now(self):
        """machine().time(): the executing CPU's local time (at the start of its current instruction)"""
        i = self.executing
        if i is None:
            return self.base
        return self.local[i] + (self.cpus[i].cycles - self.slice_start) * CPU_AS

    def timer(self, expire, fn):
        """a one-shot timer; inserted after timers with the same expiry; at the head it ends the running slice"""
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
        """abort_timeslice: the executing CPU stops after its current instruction"""
        i = self.executing
        c = self.cpus[i]
        self.aborted = True
        if i < 3:
            c.end = c.cycles
        else:
            c.icount = 0

    def at_end(self, fn):
        """fn() when the executing 6809's instruction is done (MAME's m6809 counts a bus cycle before it does the
        access, and a store is the instruction's last cycle); at once for the MCU (MAME's 6800 cores count an
        instruction's cycles after it) and outside a CPU"""
        i = self.executing
        if i is not None and i < 3:
            self.deferred.append(fn)
            c = self.cpus[i]
            c.end = c.cycles                              # (run() returns after this instruction)
        else:
            fn()

    def set_line(self, cpu, line, state):
        """set_input_line: queued, applied by a synchronize() timer (device_input::set_state_synced)"""
        q = self.queues.setdefault((cpu, line), [])
        q.append(state)
        if len(q) == 1:
            self.at_end(lambda: self.synchronize(lambda: self.apply_line(cpu, line)))

    def apply_line(self, cpu, line):
        for state in self.queues.pop((cpu, line)):
            c = self.cpus[cpu]
            if line == "reset":
                if state:
                    self.suspended[cpu] = True
                elif self.suspended[cpu]:
                    before = c.cycles
                    c.reset()
                    self.local[cpu] += (c.cycles - before) * CPU_AS    # (MAME spends the reset in the next slice)
                    self.suspended[cpu] = False
            elif cpu == 3:
                c.set_irq1(state)
            elif line == "irq":
                c.set_irq(state)
            else:
                c.set_firq(state)

    def timeslice(self):
        timers = self.timers
        cpus, local, suspended = self.cpus, self.local, self.suspended
        while self.base < timers[0][0]:
            target = self.base + QUANTUM_AS
            if timers[0][0] < target:
                target = timers[0][0]
            for i in range(4):
                delta = target - local[i]
                if delta >= CPU_AS:
                    n = (delta >> _SHIFT) // _DIV
                    if suspended[i]:
                        ran = n                       # held in reset: eats its cycles
                    else:
                        c = cpus[i]
                        self.executing = i
                        self.slice_start = start = c.cycles
                        if i == 3:
                            c.icount = 0
                            c.run(n)
                        else:
                            end = start + n
                            while True:
                                c.run(end - c.cycles)
                                if not self.deferred:
                                    break
                                # the instruction that just ended wrote something that synchronizes: MAME's core
                                # did it on its last bus cycle, so the timer goes in at the instruction's end
                                d, self.deferred = self.deferred, []
                                self.aborted = False
                                for fn in d:
                                    fn()
                                if self.aborted or c.cycles >= end:
                                    break
                        self.executing = None
                        ran = c.cycles - start
                    local[i] += ran * CPU_AS
                    if local[i] < target:
                        target = max(local[i], self.base)
            self.base = target
        while timers and timers[0][0] <= self.base and not self.stop:
            t = timers.pop(0)
            t[2]()

    def mcu_rmcr(self, v):
        """m6801_cpu_device::set_rmcr: with the internal clock (RMCR bits 2-3 = 1 or 2) the SCI ticks on a periodic
        timer of 16 / 128 / 1024 / 4096 clocks of the chip (6.144 MHz; 0.289's binary, the vendored source divides
        cycles).  The program sets $04 (every 4 CPU cycles): nothing is sent, but the timer cuts MAME's timeslices,
        so the CPUs interleave on it (with 16 cycles the main CPU parts from MAME's trace at frame 49.6)."""
        if self.sci_timer is not None:
            self.cancel(self.sci_timer)
            self.sci_timer = None
        if (v & 0x0C) >> 2 in (1, 2):
            period = (16, 128, 1024, 4096)[v & 3] * (AS // 6144000)    # MAME 0.289: the chip clock / divisor

            def tick():
                self.sci_timer = self.timer(self.sci_timer[0] + period, tick)
            self.sci_timer = self.timer(self.now() + period, tick)

    def vblank_begin(self):
        """screen_device::vblank_begin: frame_update (where MAME's Lua frame_done runs: run_frame returns here),
        then the board's callback (the sprite latch, IRQ to main and sub)"""
        self.timer(self.base + FRAME_AS, self.vblank_begin)
        self.timer(self.base + 40 * SCAN_AS, self.vblank_end)
        self.vblank_due = True
        self.stop = True

    def vblank_callback(self):
        self.vblank_due = False
        if self.copy_sprites:
            for i in range(0, 0x800, 16):
                self.spriteram[i + 10:i + 16] = self.spriteram[i + 4:i + 10]
            self.copy_sprites = False
        self.set_line(0, "irq", True)
        self.set_line(1, "irq", True)

    def vblank_end(self):
        self.set_line(2, "irq", True)
        self.set_line(3, "irq", True)

    def scanline0(self):
        self.timer(self.base + FRAME_AS, self.scanline0)

    def sound_update(self):
        self.timer(self.base + SOUND_UPDATE_AS, self.sound_update)

    def run_frame(self):
        """One arcade frame, ending where MAME's frame_done comes (the start of the vertical blank, before the
        board's vblank callback), so the state compares with MAME's dumps."""
        if self.vblank_due:
            self.vblank_callback()
        self.stop = False
        while not self.stop:
            self.timeslice()
        self.frame += 1

    # ---- video ---------------------------------------------------------------
    def gfx(self):
        if self._chr is None:
            self._chr = np.frombuffer(self.chr_rom, np.uint8).reshape(-1, 8, 8)
            bits = np.unpackbits(np.frombuffer(self.mask_rom, np.uint8)).reshape(-1, 8, 8)
            self._mask = bits.astype(bool)
            # 512 bytes a 32 x 32 sprite: y half (256), x half (128), row (8), 16 pixels of 4 bits, high nibble first
            s = np.frombuffer(self.sprite_rom, np.uint8).reshape(-1, 2, 2, 16, 8)
            px = np.stack([s >> 4, s & 15], axis=-1).reshape(-1, 2, 2, 16, 16)
            self._spr = px.transpose(0, 1, 3, 2, 4).reshape(-1, 32, 32)
        return self._chr, self._mask, self._spr

    def tilemap(self, i):
        """(pens, opaque) of layer i in logical (unflipped) orientation"""
        chr_, mask, _ = self.gfx()
        words = np.frombuffer(bytes(self.vram), ">u2")
        if i < 4:
            rows = 32 if i == 3 else 64
            codes = words[i * 0x1000:i * 0x1000 + rows * 64].reshape(rows, 64) & 0x3FFF
            cols = 64
        else:
            base = 0x3808 if i == 4 else 0x3C08
            codes = words[base:base + 36 * 28].reshape(28, 36) & 0x3FFF
            rows, cols = 28, 36
        pens = chr_[codes].transpose(0, 2, 1, 3).reshape(rows * 8, cols * 8)
        opaque = mask[codes].transpose(0, 2, 1, 3).reshape(rows * 8, cols * 8)
        return pens, opaque

    def render_raw(self):
        """The picture as 13 bit pens (288 x 224, MAME's visible area, the screen unrotated); -1 = black"""
        bw, bh = 384, 264
        xextent, yextent = VIS_X1 + VIS_X0 + 1, VIS_Y1 + VIS_Y0 + 1
        out = np.full((bh, bw), -1, np.int32)
        pri = np.zeros((bh, bw), np.int32)
        x0 = max(VIS_X0, self.c116_regs[0] - 1)
        x1 = min(VIS_X1, self.c116_regs[1] - 2)
        y0 = max(VIS_Y0, self.c116_regs[2] - 0x11)
        y1 = min(VIS_Y1, self.c116_regs[3] - 0x12)
        clip = np.zeros((bh, bw), bool)
        if x0 <= x1 and y0 <= y1:
            clip[y0:y1 + 1, x0:x1 + 1] = True
        ys, xs = np.mgrid[0:bh, 0:bw]
        flip = self.flip
        c = self.control
        for p in range(8):
            for i in range(6):
                if (c[0x10 + i] & 7) != p or c[0x10 + i] & 8:
                    continue
                pens, opaque = self.tilemap(i)
                h, w = pens.shape
                if flip:
                    pens, opaque = pens[::-1, ::-1], opaque[::-1, ::-1]
                if i < 4:
                    sx = (c[i * 4] << 8) | c[i * 4 + 1]
                    sy = (c[i * 4 + 2] << 8) | c[i * 4 + 3]
                    if flip:
                        sx, sy = -sx, -sy
                    adj = (4, 2, 1, 0)[i]
                    dx, dxf = VIS_X0 - 44 - adj, VIS_X0 + 288 + 44 + adj
                    dy, dyf = VIS_Y0 - 24, VIS_Y0 + 224 + 24
                else:
                    sx = sy = 0
                    dx = dxf = VIS_X0
                    dy = dyf = VIS_Y0
                vx = (dx - sx) if not flip else (xextent - w - (dxf - sx))
                vy = (dy - sy) if not flip else (yextent - h - (dyf - sy))
                px = (xs - vx) % w
                py = (ys - vy) % h
                o = opaque[py, px] & clip
                colour = 0x800 + ((c[0x18 + i] & 7) << 8)
                out[o] = colour + pens[py, px][o].astype(np.int32)
                pri[o] = p
        self.draw_sprites(out, pri, clip)
        return out[VIS_Y0:VIS_Y1 + 1, VIS_X0:VIS_X1 + 1]

    def draw_sprites(self, out, pri, clip):
        _, _, spr = self.gfx()
        sr = self.spriteram
        size = (16, 8, 32, 4)
        xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
        yoffs = sr[0x7F7]
        pri = pri.copy()
        for off in range(0x7E0, -1, -0x10):
            attr1, attr2, color = sr[off + 10], sr[off + 14], sr[off + 12]
            flipx, flipy = bool(attr1 & 0x20), bool(attr2 & 1)
            sizex, sizey = size[attr1 >> 6], size[(attr2 & 6) >> 1]
            tx = (attr1 & 0x18) & ~(sizex - 1)
            ty = (attr2 & 0x18) & ~(sizey - 1)
            sx = sr[off + 13] + ((color & 1) << 8)
            sy = -sr[off + 15] - sizey
            code = sr[off + 11] + ((attr1 & 7) << 8)
            pmask = ((0xFF << (((attr2 & 0xE0) >> 5) + 1)) & 0xFF) | (1 << 31)   # drawgfx: bit 31 always set
            color >>= 1
            sx += xoffs
            sy -= yoffs
            if self.flip:
                sx, sy = -sx - sizex, -sy - sizey
                flipx, flipy = not flipx, not flipy
            sy += 1
            x, y = sx & 0x1FF, ((sy + 16) & 0xFF) - 16
            img = spr[code, ty:ty + sizey, tx:tx + sizex]
            if flipx:
                img = img[:, ::-1]
            if flipy:
                img = img[::-1, :]
            bh, bw = out.shape
            yy0, xx0 = max(y, 0), max(x, 0)
            yy1, xx1 = min(y + sizey, bh), min(x + sizex, bw)
            if yy0 >= yy1 or xx0 >= xx1:
                continue
            sub = img[yy0 - y:yy1 - y, xx0 - x:xx1 - x]
            region = (slice(yy0, yy1), slice(xx0, xx1))
            opq = (sub != 15) & clip[region]
            p = pri[region]
            vis = opq & (((np.int64(1) << (p & 0x1F)) & pmask) == 0)   # a pixel a sprite drew (31) is taken
            o = out[region]
            if color == 0x7F:
                # shadow: tile pens 800-FFF become their shadow page 1000-17FF
                sh = vis & (o >= 0x800) & (o < 0x1000)
                o[sh] += 0x800
            else:
                o[vis] = (color << 4) + sub[vis].astype(np.int32)
            p[opq] = 31

    def palette_rgb(self):
        return np.stack([np.frombuffer(bytes(p), np.uint8) for p in self.pal], axis=1)

    def render_rgb(self):
        """RGB picture as MAME shows it (rotated by the game's orientation)"""
        raw = self.render_raw()
        pal = np.vstack([self.palette_rgb(), np.zeros((1, 3), np.uint8)])
        rgb = pal[np.where(raw < 0, 0x2000, raw)]
        rot = GAMES[self.game]["rot"]
        return np.ascontiguousarray(np.rot90(rgb, k={0: 0, 90: -1, 180: 2, 270: 1}[rot]))
