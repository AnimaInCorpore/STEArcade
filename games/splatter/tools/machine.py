"""Splatterhouse (Namco System 1, MAME set `splatter`): the reference board (engine/namcos1.py) and the port's schedule.

The board follows MAME's own scheduler (`run_frame`, the CPUs interleaved as MAME interleaves them).  The port does
not interleave: `run_frame_port` is its schedule, which the translated code (src/splatter.s) has too, so the two are
compared frame by frame (tools/logic_test.py):

  1. the vertical blank: the sprite list latched (if the program asked), the MCU and the sound CPU run one frame on the
     board's scheduler (their timers and interrupts as in MAME) with the main and sub CPU held
  2. the main CPU: its IRQ taken at the idle point, the handler and the foreground run until the idle point again
  3. the sub CPU: the same

The idle points: main $E061 (`STA $F200; LDA <$02; BNE` waits for the IRQ handler to clear $02), sub $E055 (the same on
$05).  A CPU is idle there when the flag is set.  The port starts from the board's state at frame START (both CPUs idle:
the boot, with its waits on the MCU and the resets of the sub CPU, is not translated).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from namcos1 import NamcoS1

START = 200
IDLE = {0: (0xE061, 0x02), 1: (0xE055, 0x05)}       # cpu: (idle pc, the direct page flag it waits on)


class Splatter(NamcoS1):
    def __init__(self, **kw):
        super().__init__("splatter", **kw)
        self.port_frames = 0

    def dp_byte(self, cpu, a):
        return self.mmu_rd(cpu, a)                       # (DP = 0: slot 0)

    def idle(self, cpu):
        pc, flag = IDLE[cpu]
        c = self.cpus[cpu]
        return c.pc == pc and self.dp_byte(cpu, flag) != 0

    def boot(self, frames=START):
        """MAME's schedule up to the port's start; the main and sub CPU must be idle there"""
        while self.frame < frames:
            self.run_frame()
        for i in (0, 1):
            c = self.cpus[i]
            for _ in range(8):                           # (to the loop's head: at most the loop's three instructions)
                if self.idle(i):
                    break
                c.step()
            if not self.idle(i):
                raise RuntimeError("cpu %d not idle at frame %d (pc %04X)" % (i, self.frame, self.cpus[i].pc))

    def run_others(self):
        """the vblank work and one frame of the MCU and the sound CPU (main and sub held, their IRQ lines left low)"""
        held = self.suspended[0], self.suspended[1]
        self.suspended[0] = self.suspended[1] = True
        self.run_frame()
        self.suspended[0], self.suspended[1] = held
        # the board's vblank asserted IRQ on main and sub: the port takes the interrupts itself
        for i in (0, 1):
            self.queues.pop((i, "irq"), None)
            self.cpus[i].set_irq(False)
        self.timers = [t for t in self.timers if not (getattr(t[2], "__name__", "") == "<lambda>" and False)]

    def run_cpu(self, i, limit=3000000):
        """IRQ at the idle point, then until the idle point again"""
        c = self.cpus[i]
        # (the CC byte the interrupt pushes: its H is the translation's only inexact bit - only DAA reads H)
        self.irq_cc_addr = getattr(self, "irq_cc_addr", {})
        self.irq_cc_addr[i] = self.offsets[i][(c.s - 12) >> 13 & 7] | ((c.s - 12) & 0x1FFF)
        c.set_irq(True)
        c.step()                                         # (the interrupt entry)
        c.set_irq(False)
        if c.pc == IDLE[i][0]:
            raise RuntimeError("cpu %d: the IRQ was not taken (I set?)" % i)
        for _ in range(limit):
            if c.pc == IDLE[i][0] and self.dp_byte(i, IDLE[i][1]) != 0:
                return
            c.step()
        raise RuntimeError("cpu %d did not come back to its idle point (pc %04X)" % (i, c.pc))

    def run_frame_port(self):
        self.run_others()
        self.run_cpu(0)
        self.run_cpu(1)
        self.port_frames += 1
