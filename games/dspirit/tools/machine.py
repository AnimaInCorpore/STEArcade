"""Dragon Spirit (Namco System 1, MAME set `dspirit`): the reference board (engine/namcos1.py) and the port's schedule.

The board follows MAME's own scheduler (`run_frame`, the CPUs interleaved as MAME interleaves them).  The port does
not interleave: `run_frame_port` is its schedule, which the translated code (src/dspirit.s) has too, so the two are
compared frame by frame (tools/logic_test.py):

  1. the vertical blank: the sprite list latched (if the program asked), the MCU and the sound CPU run one frame on the
     board's scheduler (their timers and interrupts as in MAME) with the main and sub CPU held
  2. the main CPU: its IRQ taken at the idle point, the handler and the foreground run until the idle point again
  3. the sub CPU: the same

The main CPU (DP $40: slot 2, the work RAM $4000 = virtual $300000; its stack there too) waits in
    8048: JSR $8770 (the random numbers: an LFSR step of <$D3/$D4); 804B: STA $F200; LDA <$FF; BNE 8048
then INC <$FF, JSR $8140 (the frame), BRA 8048.  The IRQ handler ($81B4) clears <$FF.  The arcade steps the LFSR on
every pass (~3600 a frame); the port once a frame: the main CPU is idle at 804B while <$FF is set, so the pass after
the IRQ is the only one (its JSR $8770 ran before the idle point).

The sub CPU (DP $20: slot 1, the scratch RAM $2000 = virtual $2FC000, the sprite RAM at $2800; its stack in slot 2)
never waits: its IRQ handler ($D6CD) only clears byte 9 of every sprite entry; the foreground loop
    D6C5: STA $F200; JSR $D8B0; BRA D6C5
builds the sprite list from the objects of the work RAM ($41A0 + $28 n) on every pass (~12 a frame in the arcade), each
pass from scratch.  The port runs one pass a frame: after the IRQ's RTI (back at D6C5) one pass, then idle at D6C5.
`sub_pass` says a pass runs (core.s sub_pass the same).

The port starts from the board's state at frame START (the boot, with its waits on the MCU and the resets of the sub
CPU, is not translated).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from namcos1 import NamcoS1

START = 300
DP = {0: 0x40, 1: 0x20}
IDLE = {0: 0x804B, 1: 0xD6C5}                       # the idle points (main slot 4, sub slot 6)
MAIN_FLAG = 0xFF                                    # (direct page: main idle while set)
IRQ = {0: 0x81B4, 1: 0xD6CD}                        # the IRQ handlers
IDLE_LEN = 3                                        # (STA $F200 at both idle points: the hooks go on after it)


class DSpirit(NamcoS1):
    def __init__(self, **kw):
        super().__init__("dspirit", **kw)
        self.port_frames = 0
        self.irq_cc_addr = {}
        self.sub_pass = False

    def dp_byte(self, cpu, a):
        return self.mmu_rd(cpu, (DP[cpu] << 8) | a)

    def idle(self, cpu):
        """at the idle point and the loop would wait (the sub: its pass done)"""
        c = self.cpus[cpu]
        if c.pc != IDLE[cpu]:
            return False
        if cpu == 0:
            return bool(self.dp_byte(0, MAIN_FLAG))
        return not self.sub_pass

    def arrive(self, cpu):
        """the hook at the idle point: True = idle there, else the code goes on (the sub: its pass starts)"""
        if cpu == 0:
            return self.idle(0)
        self.sub_pass = not self.sub_pass            # (back from the IRQ: the pass starts; at its end: idle)
        return not self.sub_pass

    def boot(self, frames=START):
        """MAME's schedule up to the port's start; then main and sub to their idle points"""
        while self.frame < frames:
            self.run_frame()
        c = self.cpus[0]
        for _ in range(64):                              # (main: the loop's few instructions)
            if self.idle(0):
                break
            c.step()
        c = self.cpus[1]
        for _ in range(40000):                           # (sub: to the end of the pass it is in)
            if c.pc == IDLE[1]:
                break
            c.step()
        self.sub_pass = False
        for i in (0, 1):
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

    def run_cpu(self, i, limit=3000000):
        """IRQ at the idle point, then until the idle point again (the sub: after one pass of its loop)"""
        c = self.cpus[i]
        # (the CC byte the interrupt pushes: its H is the translation's only inexact bit - only DAA reads H)
        self.irq_cc_addr[i] = self.offsets[i][(c.s - 12) >> 13 & 7] | ((c.s - 12) & 0x1FFF)
        c.set_irq(True)
        c.step()                                         # (the interrupt entry)
        c.set_irq(False)
        if c.pc == IDLE[i]:
            raise RuntimeError("cpu %d: the IRQ was not taken (I set?)" % i)
        for _ in range(limit):
            c.step()
            if c.pc == IDLE[i] and self.arrive(i):
                return
        raise RuntimeError("cpu %d did not come back to its idle point (pc %04X)" % (i, c.pc))

    def run_frame_port(self):
        self.run_others()
        self.run_cpu(0)
        self.run_cpu(1)
        self.port_frames += 1
