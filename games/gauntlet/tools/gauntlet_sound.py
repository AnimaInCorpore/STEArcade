"""Gauntlet's sound board for the reference board (tools/machine.py): the 6502's bus (MAME's sound_map), its
74LS259 (soundctl), the YM2151's timers and status (engine/m72board.py's model; its IRQ is not connected here), the
POKEY (engine/pokey.py: an execute device of its own in MAME, the board runs it after the 6502) and the TMS5220C
(engine/tms5220.py: its io_ready timer, its stream rendered at reads, writes and the 50 Hz update).

    0000-0FFF RAM (mirrored at 2000)   1000-17FF / 3000-37FF the I/O, decoded by A4-A5 and A11 (mirror 27C0):
    w 1000 the response latch          r 1010 the command latch         r 1020 coins / w 1020 mixer
    r 1030 status: 7 command pending, 6 response pending, 5 speech not ready, 4 service (A0-A3 not decoded)
    w 1030-1037 soundctl: data bit 7 into Q(A0-A2)
    1800 POKEY (A0-A3)   1810 YM2151 (A0)   w 1820 speech data   1830 IRQ acknowledge (read $FF, or write)
    4000-FFFF ROM; everything else reads $FF (unmap_value_high)
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from m72board import YM2151

AS = 10 ** 18


class SoundBoard:
    def __init__(self, board):
        self.b = board
        self.ram = bytearray(0x1000)
        self.rom = board.snd_rom
        self.ym = YM2151(board, lambda s: None)
        self.ym_reset_state = 1
        self.squeak = 0
        self.irq = False
        from pokey import POKEY
        from tms5220 import TMS5220C
        self.pokey = POKEY(board)
        self.tms = TMS5220C(board)

    def exec_core(self):
        from m6502mame import M6502Mame
        self.cpu = M6502Mame(self.rd, self.wr)
        return M6502Exec(self.cpu)

    # ---- the bus ------------------------------------------------------------
    def rd(self, a):
        if a < 0x4000:
            if not a & 0x1000:
                return self.ram[a & 0xFFF]
            if a & 0x800:
                k = a & 0x30
                if k == 0x00:
                    return self.pokey.read(a & 0xF)
                if k == 0x10:
                    return self.ym.read_status() if a & 1 else 0xFF   # (ymfm: offset 0 reads $FF)
                if k == 0x20:
                    return 0xFF
                self.b.set_line(self.b.sound, "irq", False)            # sound_irq_ack_r
                return 0xFF
            k = a & 0x30
            if k == 0x10:
                return self.b.soundlatch.read()
            if k == 0x20:
                return self.b.coins
            if k == 0x30:
                v = 0x30
                if self.b.soundlatch.written:
                    v ^= 0x80
                if self.b.mainlatch.written:
                    v ^= 0x40
                if not self.tms.readyq_r():
                    v ^= 0x20
                if self.b.service:
                    v ^= 0x10
                return v
            return 0xFF
        return self.rom[a]

    def wr(self, a, v):
        if a < 0x4000:
            if not a & 0x1000:
                self.ram[a & 0xFFF] = v
                return
            k = a & 0x30
            if a & 0x800:
                if k == 0x00:
                    self.pokey.write(a & 0xF, v)
                elif k == 0x10:
                    self.ym.write(a & 1, v)
                elif k == 0x20:
                    self.tms.data_w(v)
                else:
                    self.b.set_line(self.b.sound, "irq", False)        # sound_irq_ack_w
                return
            if k == 0x00:
                self.b.reply_written(v)
            elif k == 0x20:
                self.mixer_w(v)
            elif k == 0x30:
                self.b.soundctl.write_bit(a & 7, v >> 7 & 1)

    # ---- soundctl (16T/U) ---------------------------------------------------------
    def soundctl(self, bit, state):
        if bit == 0:
            self.ym_reset(state)
        elif bit == 1:
            self.tms.wsq_w(state)
        elif bit == 2:
            self.tms.rsq_w(state)
        elif bit == 3:
            self.tms.set_clock(int(14318181 / 2 / (16 - (5 | (2 if state else 0))) + 1e-3))   # XTAL::value()

    def mixer_w(self, v):
        """the gains (only the TMS5220's matters to the logic: a change updates its stream)"""
        self.tms.set_output_gain(((v >> 5) & 7) / 7.0)

    def ym_reset(self, state):
        """ym2151_device::reset_w (active low): a rising edge resets the chip (registers, status, timers)"""
        if state != self.ym_reset_state:
            self.ym_reset_state = state
            if state:
                ym = self.ym
                ym.regs[:] = bytes(256)
                ym.status = 0
                for t in (0, 1):
                    self.b.cancel(ym.timer[t])
                    ym.running[t] = False

    def stream_update(self):
        self.tms.stream_update()


class M6502Exec:
    """engine/m6502mame.py in the scheduler's protocol"""

    def __init__(self, cpu):
        self.cpu = cpu

    def run(self, n):
        return self.cpu.run(n)

    def executed(self):
        return self.cpu.executed()

    def abort(self):
        self.cpu.abort()

    def set_line(self, line, state):
        self.cpu.set_input(line, state, self.cpu.total_cycles())

    def reset(self):
        """device_reset; interface_pre_reset zeroes the total cycles"""
        self.cpu.reset()
        self.cpu.total = 0
