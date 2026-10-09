"""1943 main Z80 bus and reference frame schedule, with real MCU firmware.

Audio CPU/YM2203 and cycle-accurate MCU execution are not implemented.
The Euro program is the MAME BAD_DUMP; no further program patches are applied.
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from paths import build_dir
from z80 import Z80
from mcu import MCU
from video import Video

CYCLES_PER_FRAME = 384*262


class Game1943:
    def __init__(self):
        build = build_dir('1943')
        self.set_name = (build / 'set.txt').read_text().strip()
        self.rom = (build / 'maincpu.rom').read_bytes()
        self.mem = bytearray(65536)
        self.sprites = bytearray(4096)
        self.inputs = [255, 255, 255, 248, 255]
        self.control = self.layers = self.bank = self.sound_latch = 0
        self.frame = self.scanline = self.irq_count = self.dma_count = 0
        self.pending_irq = False
        self.mcu = MCU((build / 'mcu.rom').read_bytes())
        self.cpu = Z80(self.rd8, self.wr8)
        self.video = None

    def rd8(self, addr):
        if addr < 0x8000: return self.rom[addr]
        if addr < 0xc000: return self.rom[0x10000+self.bank*0x4000+addr-0x8000]
        if 0xc000 <= addr <= 0xc004:
            value = self.inputs[addr-0xc000]
            if addr == 0xc000:
                return (value & ~8) | (8 if self.scanline >= 240 or self.scanline < 16 else 0)
            return value
        if addr == 0xc007: return self.mcu.response
        if 0xd000 <= addr < 0xd805 or addr >= 0xe000: return self.mem[addr]
        return 255

    def wr8(self, addr, value):
        if addr == 0xc800: self.sound_latch = value
        elif addr == 0xc804:
            self.control = value
            self.bank = (value >> 2) & 7
        elif addr == 0xc806:
            self.sprites[:] = self.mem[0xf000:]
            self.dma_count += 1
        elif addr == 0xc807: self.mcu.command = value
        elif addr == 0xd806: self.layers = value
        elif 0xd000 <= addr < 0xd805 or addr >= 0xe000: self.mem[addr] = value

    def run_frame(self):
        start = self.frame*CYCLES_PER_FRAME
        # Scanline granularity supplies the SYSTEM VBL bit consistently.
        for line in range(262):
            self.scanline = line
            if line in (144, 240): self.pending_irq = True
            if line == 240: self.mcu.vblank()
            target = start+(line+1)*384
            while self.cpu.cycles < target:
                if self.pending_irq and not self.cpu.ei_delay and self.cpu.irq():
                    self.pending_irq = False
                    self.irq_count += 1
                self.cpu.ei_delay = False
                self.cpu.step()
        self.frame += 1

    def render_rgb(self, rotated=False):
        if self.video is None: self.video = Video(self.set_name)
        return self.video.render_rgb(self.mem, self.sprites, self.control, self.layers, rotated)

    # The cooperative STE schedule (the runtime's z80_hook does the same): the scheduler at IDLE_PC found no ready task.
    IDLE_PC = 0x00d4
    booted = False

    def run_to_idle(self, limit=4000000):
        for _ in range(limit):
            if self.cpu.pc == self.IDLE_PC:
                return
            self.cpu.ei_delay = False
            self.cpu.step()
        raise RuntimeError(f'1943 did not idle: PC={self.cpu.pc:04x}, bank={self.bank}')

    def irq_port(self, scanline):
        """One held IRQ taken at the idle point, its handler run to the return to IDLE_PC (it does not switch tasks)."""
        self.scanline = scanline
        if not self.cpu.irq():
            raise RuntimeError('Interrupts disabled at the 1943 idle point')
        self.irq_count += 1
        self.run_to_idle()

    def run_frame_port(self):
        """A tick: the line 144 IRQ (VBL bit clear), the MCU's INT1, the line 240 IRQ (VBL bit set), then the tasks
        the handlers made ready, to the next idle point.  The tasks see the VBL bit clear."""
        if not self.booted:
            self.scanline = 16
            self.run_to_idle()
            self.booted = True
        self.irq_port(144)
        self.mcu.vblank()
        self.irq_port(240)
        self.scanline = 16
        self.cpu.step()                       # (the idle loop's jr, then the scheduler's next round)
        self.run_to_idle()
        self.frame += 1
