"""Commando's sound board (MAME capcom/commando.cpp): a Z80 at 3 MHz (PHI_B), ROM 0000-3FFF, RAM 4000-47FF, the
sound latch at 6000 (written by the main CPU at C800), two YM2203 at 8000/8001 and 8002/8003 (1.5 MHz).  The
scanline PROM gives it four IRQs a frame (bit 2 of irqprom, HOLD_LINE: taken when interrupts are enabled; IM 1).
The main CPU's control write C804 bit 4 holds it in reset.

The chips are not emulated: every register write is logged as (frame, line, chip, register, value), which is what an
STE player of the music needs (and what tells which parts of the chips the music uses).

    python sound.py [frames]     the attract mode, coin, start and play of ref/cover.py: a summary of the writes
"""
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80
from paths import build_dir
from machine import Commando, CYCLES_PER_LINE, LINES


class SoundBoard:
    def __init__(self):
        rom = (build_dir("commando") / "audiocpu.rom").read_bytes()
        self.mem = bytearray(65536)
        self.mem[:0x4000] = rom[:0x4000]
        self.latch = 0
        self.writes = []            # (frame, line, chip, register, value)
        self.addr = [0, 0]          # the register address latch of each chip
        self.frame = self.line = 0
        self.cpu = Z80(self.rd8, self.wr8)
        self.irq = False
        self.taken = 0              # IRQs taken
        self.reset_held = False
        self.regs = [[0] * 16, [0] * 16]    # the SSG registers as last written
        self.in_irq = False
        self.on_irq_done = None     # called when a handler has returned to the main loop (its writes are done)
        self.irq_latch = 0          # the latch when the IRQ was taken

    def rd8(self, a):
        if a == 0x6000:
            return self.latch
        if a < 0x4000 or 0x4000 <= a < 0x4800:
            return self.mem[a]
        return 0xFF

    def wr8(self, a, v):
        if 0x4000 <= a < 0x4800:
            self.mem[a] = v
        elif 0x8000 <= a <= 0x8003:
            chip = (a >> 1) & 1
            if a & 1:
                self.writes.append((self.frame, self.line, chip, self.addr[chip], v))
                if self.addr[chip] < 16:
                    self.regs[chip][self.addr[chip]] = v
            else:
                self.addr[chip] = v

    IDLE = (0x0073, 0x0074)     # the main loop: ei; jr $0073

    def idle(self):
        return self.cpu.pc in self.IDLE

    def run_line(self, target, irq_now):
        """run to the cycle count target; irq_now: the PROM raises the IRQ on this line (held until taken)"""
        c = self.cpu
        if self.reset_held:
            c.cycles = target
            return
        if irq_now:
            self.irq = True
        while c.cycles < target:
            if self.irq and c.iff1 and not getattr(c, "ei_delay", False):
                self.irq = False
                self.taken += 1
                self.in_irq = True
                self.irq_latch = self.latch
                c.iff1 = c.iff2 = 0
                c.halted = False
                c.push(c.pc)
                c.pc = 0x38
                c.cycles += 13
            if hasattr(c, "ei_delay"):
                c.ei_delay = False
            c.step()
            if self.in_irq and c.pc in self.IDLE:
                self.in_irq = False
                if self.on_irq_done:
                    self.on_irq_done(self)


def run(frames, on_frame=None):
    """the main reference (cycle exact frames, ref/cover.py's inputs) with the sound board beside it, line by line"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref"))
    import random
    from cover import inputs
    m, s = Commando(), SoundBoard()
    rnd = random.Random(1)
    for f in range(frames):
        system, p1, p2 = inputs(f, rnd)
        m.inputs[0], m.inputs[1], m.inputs[2] = system, p1, p2
        target = m.frame * CYCLES_PER_LINE * LINES
        for line in range(LINES):
            irq = m.irqprom[line & 255]
            if irq & 8:
                m.pending = 0xc7 | ((irq << 3) & 0x18)
            target += CYCLES_PER_LINE
            while m.cpu.cycles < target:
                m.step()
            s.latch = m.latch
            held = bool(m.control & 0x10)
            if held and not s.reset_held:
                s.cpu.reset() if hasattr(s.cpu, "reset") else None
            s.reset_held = held
            s.frame, s.line = f, line
            s.run_line(target, bool(irq & 4))
        m.frame += 1
        if on_frame:
            on_frame(f, m, s)
    return m, s


if __name__ == "__main__":
    import collections
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    m, s = run(frames)
    kinds = collections.Counter()
    for f, line, chip, reg, v in s.writes:
        k = ("SSG %02X" % reg if reg < 0x10 else "key on/off" if reg == 0x28 else "timer/mode %02X" % reg if reg < 0x30
             else "FM %02X" % (reg & 0xF0))
        kinds[(chip, k)] += 1
    print("%d frames, %d register writes" % (frames, len(s.writes)))
    for (chip, k), n in sorted(kinds.items()):
        print("  YM%d %-14s %7d" % (chip + 1, k, n))
