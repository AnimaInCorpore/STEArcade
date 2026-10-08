"""Bubble Bobble (Taito 1986, MAME set `bublbobl`) machine model -- host reference.

Chips: main Z80 (6 MHz), sub Z80 (6 MHz), sound Z80 (3 MHz), MC6801 MCU (a78-01.17).
This is the ground truth the STE port is checked against; it is *not* shipped.

Evidence grades for each hardware claim are kept in docs/hardware.md; anything
the code marks `# HYP` is a hypothesis still waiting for a second confirmation.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "ste", "tools"))
from z80 import Z80          # noqa: E402  (shared reference Z80 from the Donkey Kong port)
from m6801 import M6801      # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ROMDIR = os.path.join(ROOT, "assets", "roms", "extracted_bublbobl")

MAIN_HZ = 6_000_000
FPS = 59.185606
FRAME_CYCLES = int(MAIN_HZ / FPS)          # 101375 main-CPU T-states per frame
VBLANK_AT = int(FRAME_CYCLES * 240 / 264)  # vblank starts after visible line 240 of 264


# Two main-CPU ROM sets share every other ROM (sub, sound, MCU, gfx, PROM are byte-identical).
VARIANTS = {
    "bublbobl": ("extracted_bublbobl", "a78-06-1.51", "a78-05-1.52"),
    "bublboblr": ("extracted_bublboblr", "a78-25.51", "a78-24.52"),
}


def load(name, variant="bublbobl"):
    d = VARIANTS[variant][0] if name in VARIANTS[variant][1:] else "extracted_bublbobl"
    with open(os.path.join(ROOT, "assets", "roms", d, name), "rb") as f:
        return f.read()


class Bubble:
    def __init__(self, trace_unmapped=True, variant="bublbobl"):
        self.variant = variant
        self.main_rom = load(VARIANTS[variant][1], variant)   # 0000-7FFF
        self.bank_rom = load(VARIANTS[variant][2], variant)   # 4 x 16K banked at 8000-BFFF
        self.sub_rom = load("a78-08.37")
        self.snd_rom = load("a78-07.46")
        self.mcu_rom = load("a78-01.17")

        self.vram = bytearray(0x2000)       # C000-DFFF  (videoram C000-DCFF, objectram DD00-DFFF)
        self.mainram = bytearray(0x1800)    # E000-F7FF  shared main/sub
        self.palram = bytearray(0x200)      # F800-F9FF
        self.mcuram = bytearray(0x400)      # FC00-FFFF  shared main/MCU
        self.sub_ram = bytearray(0x800)     # sub 8000-87FF   # HYP
        self.snd_ram = bytearray(0x1000)    # sound 8000-8FFF # HYP

        self.bank = 0
        self.mcu_reset_n = 0
        self.sub_reset_n = 0
        self.snd_reset_n = 0
        self.fb40_log = []
        self.flip = 0
        self.sound_latch = 0
        self.sound_latch2 = 0
        self.snd_nmi_pending = False
        self.snd_nmi_enabled = False
        self.video_enable = True
        self.unmapped = {}
        self.trace_unmapped = trace_unmapped
        self.frame = 0
        self.log_sound = []
        self.in0 = 0xFF
        self.in1 = 0xFF
        self.dsw0 = 0xFF
        self.dsw1 = 0xFF
        self.coin = 0x00

        self.main = Z80(self.m_rd, self.m_wr)
        self.sub = Z80(self.s_rd, self.s_wr)
        self.snd = Z80(self.a_rd, self.a_wr)
        self.main.afmask = self.sub.afmask = self.snd.afmask = 0xFF
        self.sub.sp = self.snd.sp = 0xFFFF

        # ---- MCU glue ------------------------------------------------------
        self.mcu_ram = bytearray(0xC0)   # internal RAM $40-$FF (init loop in a78-01.17 clears it)
        self.mcu = M6801(self.mcu_bus_rd, self.mcu_bus_wr)
        # P1 pins: bit0 tilt (idle 1), bit1 (idle 1, role HYP), bit2/3 coin1/2 (active-high pulses)
        self.pins = {"tilt": 1, "p1_1": 1, "coin1": 0, "coin2": 0}
        self.mcu.port_in[1] = self._p1_pins
        self.mcu.port_in[3] = lambda: self.mcu_p3_in
        self.mcu.port_out[1] = self.mcu_p1_w
        self.mcu.port_out[2] = self.mcu_p2_w
        self.mcu.port_out[4] = self.mcu_p4_w
        self.mcu.port_out[3] = self.mcu_p3_w
        self.mcu_p3_in = 0xFF
        self.mcu_p3_out = 0
        self.mcu_p4_out = 0
        self.mcu_p2_prev = 0
        self.mcu_p1_prev = 0
        self.main_irq_pending = None   # vector byte when asserted
        self.sub_irq_pending = False
        self.mcu.reset()
        self.main.reset()
        self.sub.reset()
        self.snd.reset()
        self.main.sp = 0xFFFF

    def _p1_pins(self):
        p = self.pins
        return 0xF0 | p["tilt"] | (p["p1_1"] << 1) | (p["coin1"] << 2) | (p["coin2"] << 3)

    # ===== main CPU bus =====================================================
    def m_rd(self, a):
        if a < 0x8000:
            return self.main_rom[a]
        if a < 0xC000:
            return self.bank_rom[self.bank * 0x4000 + (a - 0x8000)]
        if a < 0xE000:
            return self.vram[a - 0xC000]
        if a < 0xF800:
            return self.mainram[a - 0xE000]
        if a < 0xFA00:
            return self.palram[a - 0xF800]
        if a >= 0xFC00:
            return self.mcuram[a - 0xFC00]
        return self._unm("m", "r", a)

    def m_wr(self, a, v):
        if a < 0x8000:
            return
        if a < 0xC000:
            return
        if a < 0xE000:
            self.vram[a - 0xC000] = v
        elif a < 0xF800:
            self.mainram[a - 0xE000] = v
        elif a < 0xFA00:
            self.palram[a - 0xF800] = v
        elif a >= 0xFC00:
            self.mcuram[a - 0xFC00] = v
        elif a == 0xFA00:
            self.sound_latch = v
            self.log_sound.append((self.frame, v))
            self.snd_nmi_pending = True      # HYP: command write raises sound NMI
        elif a == 0xFA03:
            self.snd_nmi_enabled = bool(v & 1) is False   # HYP
        elif a == 0xFA80:
            pass                            # watchdog
        elif a == 0xFB40:
            self.bank = v & 3                 # HYP: bit 2 ignored (code writes $04..$07 and $00..$03 for the same banks)
            self.flip = (v >> 6) & 3
            sub_n, snd_n = (v >> 4) & 1, (v >> 5) & 1
            # HYP: the MCU shares the sub CPU's reset line (the boot RAM test of $FC01-$FFFF would
            # otherwise be disturbed by the MCU's own handshake writes)
            if sub_n and not self.sub_reset_n:
                self.sub.reset(); self.sub.sp = 0xFFFF
                self.mcu.reset(); self.main_irq_pending = None
                self.mcu.cycles = self.main.cycles // 8
            if snd_n and not self.snd_reset_n:
                self.snd.reset(); self.snd.sp = 0xFFFF
            self.sub_reset_n, self.snd_reset_n = sub_n, snd_n
            self.mcu_reset_n = sub_n
            self.fb40_log.append((self.frame, v))
        else:
            self._unm("m", "w", a, v)

    # ===== sub CPU bus ========================================================
    def s_rd(self, a):
        if a < 0x8000:
            return self.sub_rom[a]
        if 0x8000 <= a < 0x8800:
            return self.sub_ram[a - 0x8000]
        if 0xE000 <= a < 0xF800:
            return self.mainram[a - 0xE000]
        return self._unm("s", "r", a)

    def s_wr(self, a, v):
        if 0x8000 <= a < 0x8800:
            self.sub_ram[a - 0x8000] = v
        elif 0xE000 <= a < 0xF800:
            self.mainram[a - 0xE000] = v
        else:
            self._unm("s", "w", a, v)

    # ===== sound CPU bus ==========================================================
    def a_rd(self, a):
        if a < 0x8000:
            return self.snd_rom[a]
        if 0x8000 <= a < 0x9000:
            return self.snd_ram[a - 0x8000]
        if a == 0x9000:
            return 0x00       # YM2203 status: not busy, no timer flags  # HYP
        if a == 0xA000:
            return 0x00       # YM3526 status
        if a == 0xB000:
            return self.sound_latch
        return self._unm("a", "r", a)

    def a_wr(self, a, v):
        if 0x8000 <= a < 0x9000:
            self.snd_ram[a - 0x8000] = v
        elif a in (0x9000, 0x9001, 0xA000, 0xA001):
            self.log_sound.append((self.frame, "ym%X" % a, v))
        elif a == 0xB000:
            self.sound_latch2 = v
        elif a in (0xB001, 0xE000):
            pass
        else:
            self._unm("a", "w", a, v)

    def _unm(self, cpu, rw, a, v=None):
        if self.trace_unmapped:
            k = (cpu, rw, a)
            self.unmapped[k] = self.unmapped.get(k, 0) + 1
        return 0xFF

    # ===== MCU bus =================================================================
    def mcu_bus_rd(self, a):
        if 0xF000 <= a:
            return self.mcu_rom[a - 0xF000]
        if 0x40 <= a < 0x100:
            return self.mcu_ram[a - 0x40]
        return 0

    def mcu_bus_wr(self, a, v):
        if 0x40 <= a < 0x100:
            self.mcu_ram[a - 0x40] = v

    def mcu_p1_w(self, v, ddr):
        # bit 6 falling edge: raise main-CPU IRQ with vector = shared RAM[0]  (HYP: confirmed by main code
        # writing the IM2 vector low byte to $FC00 at $0130)
        if (self.mcu_p1_prev & 0x40) and not (v & 0x40):
            self.main_irq_pending = self.mcuram[0]
        self.mcu_p1_prev = v

    def mcu_p3_w(self, v, ddr):
        self.mcu_p3_out = v

    def mcu_p4_w(self, v, ddr):
        self.mcu_p4_out = v

    def mcu_p2_w(self, v, ddr):
        # bit 4 rising edge latches a bus cycle: address = P4 | (P2&0xF)<<8; P1.7 = read(1)/write(0)
        if (v & 0x10) and not (self.mcu_p2_prev & 0x10):
            addr = self.mcu_p4_out | ((v & 0x0F) << 8)
            rd = bool(self.mcu.pout[1] & 0x80)
            if rd:
                if (addr & 0xC00) == 0xC00:
                    self.mcu_p3_in = self.mcuram[addr & 0x3FF]
                elif addr < 4:
                    self.mcu_p3_in = (self.in0, self.dsw0, self.dsw1, self.in1)[addr]
                else:
                    self.mcu_p3_in = 0xFF
                    self._unm("mcu", "r", addr)
            else:
                if (addr & 0xC00) == 0xC00:
                    self.mcuram[addr & 0x3FF] = self.mcu_p3_out
                else:
                    self._unm("mcu", "w", addr, self.mcu_p3_out)
        self.mcu_p2_prev = v

    # ===== scheduling ================================================================
    def run_frame(self):
        main, sub, snd, mcu = self.main, self.sub, self.snd, self.mcu
        base = main.cycles
        vblank_fired = False
        target = base + FRAME_CYCLES
        while main.cycles < target:
            t = main.cycles - base
            if not vblank_fired and t >= VBLANK_AT:
                vblank_fired = True
                self.sub_irq_pending = True
                mcu.irq_line = True
            # main
            if self.main_irq_pending is not None and main.iff1:
                vec = self.main_irq_pending
                if main.irq(vec):
                    self.main_irq_pending = None
            main.step()
            # sub (same clock)
            if self.sub_reset_n:
                while sub.cycles < main.cycles:
                    if self.sub_irq_pending and sub.iff1:
                        sub.irq()
                        self.sub_irq_pending = False
                    sub.step()
            else:
                sub.cycles = main.cycles
            # sound (half clock)
            if self.snd_reset_n:
                while snd.cycles * 2 < main.cycles:
                    if self.snd_nmi_pending and self.snd_nmi_enabled:
                        snd.nmi()
                        self.snd_nmi_pending = False
                    snd.step()
            else:
                snd.cycles = main.cycles // 2
            # MCU: E clock = 750 kHz = main/8
            if self.mcu_reset_n:
                while mcu.cycles * 8 < main.cycles:
                    mcu.step()
            else:
                mcu.cycles = main.cycles // 8
        self.frame += 1
