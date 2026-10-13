"""Galaga '88 (Namco System 1, MAME set `galaga88`): the reference board (engine/namcos1.py) and the port's schedule.

The board follows MAME's own scheduler (`run_frame`, the CPUs interleaved as MAME interleaves them).  The port does
not interleave: `run_frame_port` is its schedule, which the translated code (src/galaga88.s) has too, so the two are
compared frame by frame (tools/logic_test.py):

  1. the vertical blank: the sprite list latched (if the program asked), the MCU and the sound CPU run one frame on the
     board's scheduler (their timers and interrupts as in MAME) with the main and sub CPU held
  2. the main CPU: its IRQ taken at the idle point, the handler and the foreground run until the idle point again
  3. the sub CPU: the same

Both programs run with DP = $40 (slot 2: the work RAM page $180, shared by the two CPUs), their stacks in slot 2 too.
The idle loops (main $E16A, sub $E058):
    main:  INC <$20 / E16C: INC <$2C; LDA <$20; BNE E16C          (the IRQ handler clears $20)
    sub:   INC <$21 / E05A: INC <$2D; LDA <$21; ORA <$E6; BNE E05A (the IRQ handler clears $21; $E6 holds the sub)
$2C / $2D count the loop's passes and the game reads them as random numbers (main $7FB47E, sub $7F18BD).  The arcade's
count depends on every cycle; the port's schedule makes it one pass a frame: a CPU is idle at the loop's head (E16C /
E05A) when the loop would go on, and the pass that leaves the loop is the only one counted.  The port's idle hook does
the same (src/core.s): at the head, idle without counting when the loop goes on, else count and leave.

The port starts from the board's state at frame START (both CPUs idle: the boot, with its waits on the MCU and the
resets of the sub CPU, is not translated).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from namcos1 import NamcoS1

START = 300
DP = 0x40
# cpu: (idle pc, the direct page bytes the loop goes on while any is set)
IDLE = {0: (0xE16C, (0x20,)), 1: (0xE05A, (0x21, 0xE6))}
COUNTER = {0: 0x2C, 1: 0x2D}                        # (the loop's pass counter, direct page)
IRQ = {0: 0xE1D3, 1: 0xE0B3}                        # the IRQ handlers (slot 7)


class Galaga88(NamcoS1):
    def __init__(self, **kw):
        super().__init__("galaga88", **kw)
        self.port_frames = 0
        self.irq_cc_addr = {}

    def dp_byte(self, cpu, a):
        return self.mmu_rd(cpu, (DP << 8) | a)

    def idle(self, cpu):
        pc, flags = IDLE[cpu]
        return self.cpus[cpu].pc == pc and any(self.dp_byte(cpu, f) for f in flags)

    def boot(self, frames=START):
        """MAME's schedule up to the port's start; the main and sub CPU must be idle there"""
        while self.frame < frames:
            self.run_frame()
        for i in (0, 1):
            c = self.cpus[i]
            for _ in range(8):                           # (to the loop's head: at most the loop's instructions)
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
            c.step()
            if self.idle(i):
                return
        raise RuntimeError("cpu %d did not come back to its idle point (pc %04X)" % (i, c.pc))

    def run_frame_port(self):
        self.run_others()
        self.run_cpu(0)
        self.run_cpu(1)
        self.port_frames += 1
