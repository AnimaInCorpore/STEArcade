"""Gun.Smoke main-Z80 reference bus, from MAME capcom/gunsmoke.cpp.

No ROM patches, sound emulation. Sprite buffering is explicit,
triggered by the program's C806 write, rather than automatically at VBL.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'engine'))
from paths import build_dir
from z80 import Z80

CYCLES_PER_LINE = 192
CYCLES_PER_FRAME = CYCLES_PER_LINE * 262


class GunSmoke:
    def __init__(self):
        self.rom = (build_dir('gunsmoke') / 'maincpu.rom').read_bytes()
        self.mem = bytearray(65536)
        self.sprites = bytearray(4096)
        self.inputs = [255, 255, 255, 0xf7, 255]
        self.bank = self.control = self.layers = self.sound_latch = 0
        self.frame = self.irq_count = 0
        self.pending_irq = False
        self.io_log = []
        self.cpu = Z80(self.rd8, self.wr8)
        self.video = None

    def rd8(self, a):
        if a < 0x8000:
            return self.rom[a]
        if a < 0xc000:
            return self.rom[0x8000 + self.bank * 0x4000 + a - 0x8000]
        if 0xc000 <= a <= 0xc004:
            # SYSTEM bit 3 is MAME's "VBLANK" IPT_CUSTOM without a read callback: it always reads 1 (inactive,
            # active low).  The interrupt handler skips its whole body when it reads 0.
            return self.inputs[a - 0xc000] | (8 if a == 0xc000 else 0)
        if 0xc4c9 <= a <= 0xc4cb:
            return (255, 0, 0)[a - 0xc4c9]
        if 0xd000 <= a <= 0xd802 or a >= 0xe000:
            return self.mem[a]
        return 255

    def wr8(self, a, v):
        if a in (0xc800, 0xc804, 0xc806, 0xd806):
            self.io_log.append((self.frame, self.cpu.pc, a, v))
            if a == 0xc800:
                self.sound_latch = v
            elif a == 0xc804:
                self.control = v
                self.bank = (v >> 2) & 3
            elif a == 0xc806:
                self.sprites[:] = self.mem[0xf000:]
            else:
                self.layers = v
        elif 0xd000 <= a <= 0xd802 or a >= 0xe000:
            self.mem[a] = v

    def run_frame(self):
        start = self.frame * CYCLES_PER_FRAME
        for target, vblank in ((start + 240*CYCLES_PER_LINE, True),
                               (start + CYCLES_PER_FRAME, False)):
            while self.cpu.cycles < target:
                if self.pending_irq and not self.cpu.ei_delay and self.cpu.irq():
                    self.pending_irq = False
                    self.irq_count += 1
                self.cpu.ei_delay = False
                self.cpu.step()
            if vblank:
                self.pending_irq = True
        self.frame += 1

    # The runtime's schedule (src/gunsmoke.s, z80_hook): the program is a cooperative kernel (eight tasks at EF80, the
    # scheduler 00AD-00CE).  The interrupt is delivered when the scheduler found no task ready (IDLE: the `jr $00B0`
    # after the last of the eight): RST 38 runs to completion with RESCAN (where that jr goes) as its return address,
    # so the scheduler scans again and the tasks it woke run until it idles again.  One call = one arcade frame.
    IDLE = 0x00ce
    RESCAN = 0x00b0
    booted = False

    def run_to_idle(self, limit=3000000):
        c = self.cpu
        for _ in range(limit):
            if c.pc == self.IDLE:
                return
            c.step()
        raise RuntimeError(f'The foreground did not idle (pc {c.pc:04x}, frame {self.frame})')

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        c.iff1 = c.iff2 = 0
        c.push(self.RESCAN)
        c.pc = 0x38
        for _ in range(2000000):
            c.step()
            if c.pc == self.RESCAN:
                break
        else:
            raise RuntimeError('The interrupt did not return')
        self.irq_count += 1
        c.pc = self.RESCAN
        self.run_to_idle()
        self.frame += 1

    def render_rgb(self):
        if self.video is None:
            from video import Video
            self.video = Video()
        return self.video.render_rgb(self)
