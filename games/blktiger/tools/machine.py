"""Black Tiger reference bus, main Z80, protection firmware and video.

Hardware from MAME capcom/blktiger.cpp. No sound CPU or YM2203 emulation.
MCU transactions are synchronous; no boot/checksum patches are applied.
"""
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / 'engine')]
from paths import EXTRACTED
from z80 import Z80
from mcu import MCU

ROMDIR = EXTRACTED / 'blktiger'
CYCLES_PER_FRAME = 384 * 262


def load(name):
    return (ROMDIR / name).read_bytes()


def decode(data, w, h, planes, xo, yo, stride, count):
    bits = np.unpackbits(np.frombuffer(data, np.uint8))
    offsets = (np.arange(count)[:, None, None] * stride +
               np.array(yo)[None, :, None] + np.array(xo)[None, None, :])
    out = np.zeros((count, h, w), np.uint8)
    for i, plane in enumerate(planes):
        out |= bits[offsets + plane] << (len(planes) - 1 - i)
    return out


class Gfx:
    def __init__(self):
        self.chars = decode(load('bd-15.2n'), 8, 8, (4, 0),
                            [0, 1, 2, 3, 8, 9, 10, 11], [16*y for y in range(8)], 128, 2048)
        xo = [0, 1, 2, 3, 8, 9, 10, 11, 256, 257, 258, 259, 264, 265, 266, 267]
        for kind, names in [('tiles', ('bd-12.5b', 'bd-11.4b', 'bd-14.9b', 'bd-13.8b')),
                            ('sprites', ('bd-08.5a', 'bd-07.4a', 'bd-10.9a', 'bd-09.8a'))]:
            data = b''.join(load(n) for n in names)
            half = len(data) * 4
            setattr(self, kind, decode(data, 16, 16, (half+4, half, 4, 0), xo,
                                      [16*y for y in range(16)], 512, 2048))


class BlackTiger:
    def __init__(self):
        self.rom = bytearray(0x50000)
        for off, name in [(0, 'bdu-01a.5e'), (0x10000, 'bdu-02a.6e'),
                          (0x20000, 'bdu-03a.8e'), (0x30000, 'bd-04.9e'), (0x40000, 'bd-05.10e')]:
            data = load(name)
            self.rom[off:off+len(data)] = data
        self.mem = bytearray(0x10000)
        self.bg = bytearray(0x4000)
        self.sprites = bytearray(0x200)
        self.bank = self.bg_bank = self.control = self.video_enable = self.layout = 0
        self.scroll = bytearray(4)
        self.inputs = [0xff, 0xff, 0xff, 0xff, 0x6f, 0xff]
        self.sound_latch = self.coin_lockout = 0
        self.mcu = MCU(load('bd.6k'))
        self.cpu = Z80(self.rd8, self.wr8, self.io_in, self.io_out)
        self.cpu.afmask = 0xc1
        self.booted = False
        self.frame = 0
        self.pending_irq = False
        self.irq_count = 0
        self.gfx = None
        self.io_log = []

    def rd8(self, a):
        if a < 0x8000:
            return self.rom[a]
        if a < 0xc000:
            return self.rom[0x10000 + self.bank * 0x4000 + a - 0x8000]
        if a < 0xd000:
            return self.bg[self.bg_bank * 0x1000 + a - 0xc000]
        return self.mem[a]

    def wr8(self, a, v):
        if 0xc000 <= a < 0xd000:
            self.bg[self.bg_bank * 0x1000 + a - 0xc000] = v
        elif a >= 0xd000:
            self.mem[a] = v

    def io_in(self, port):
        port &= 255
        if port < 6:
            return self.inputs[port]
        if port == 7:
            return self.mcu.response
        return 255

    def io_out(self, port, v):
        port &= 255
        self.io_log.append((self.frame, self.cpu.pc, port, v))
        if port == 0:
            self.sound_latch = v
        elif port == 1:
            self.bank = v & 15
        elif port == 3:
            self.coin_lockout = v
        elif port == 4:
            self.control = v
        elif port == 7:
            self.mcu.send(v)
        elif 8 <= port <= 11:
            self.scroll[port-8] = v
        elif port == 12:
            self.video_enable = v
        elif port == 13:
            self.bg_bank = v & 3
        elif port == 14:
            self.layout = v

    def run_frame(self):
        # Rising VBL at line 240: latch sprites and assert HOLD_LINE IRQ.
        start = self.frame * CYCLES_PER_FRAME
        for target, vblank in [(start + 240*384, True), (start + CYCLES_PER_FRAME, False)]:
            while self.cpu.cycles < target:
                if self.pending_irq and not self.cpu.ei_delay and self.cpu.irq():
                    self.pending_irq = False
                    self.irq_count += 1
                self.cpu.ei_delay = False
                self.cpu.step()
            if vblank:
                self.sprites[:] = self.mem[0xfe00:]
                self.pending_irq = True
        self.frame += 1

    IDLE_PC = 0x00d4

    def run_to_idle(self, limit=2000000):
        for _ in range(limit):
            if self.cpu.pc == self.IDLE_PC:
                return
            self.cpu.ei_delay = False
            self.cpu.step()
        raise RuntimeError(f'Black Tiger did not idle: PC={self.cpu.pc:04x}, bank={self.bank}')

    def run_frame_port(self):
        """Cooperative STE schedule: one held IRQ, then run every ready task."""
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        self.sprites[:] = self.mem[0xfe00:]
        if not self.cpu.irq():
            raise RuntimeError('Interrupts disabled at Black Tiger idle point')
        self.irq_count += 1
        # Run the handler to its return to the idle PC, then execute the old
        # idle-loop jump once before running the tasks it made ready.
        self.run_to_idle()
        self.cpu.step()
        self.run_to_idle()
        self.frame += 1

    def render_raw(self):
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        out = np.full((256, 256), 1023, np.uint16)
        yy, xx = np.indices((256, 256))
        if not self.video_enable & 2:
            sx = self.scroll[0] | self.scroll[1] << 8
            sy = self.scroll[2] | self.scroll[3] << 8
            cols, rows = (128, 64) if self.layout else (64, 128)
            wx, wy = (xx+sx) % (cols*16), (yy+sy) % (rows*16)
            col, row = wx//16, wy//16
            idx = ((col & 15) + ((row & 15) << 4) +
                   ((col & 0x70) << 4) + ((row & 0x30) << 7)) if self.layout else (
                   (col & 15) + ((row & 15) << 4) + ((col & 0x30) << 4) + ((row & 0x70) << 6))
            bg = np.frombuffer(self.bg, np.uint8)
            attr = bg[2*idx+1]
            code = bg[2*idx] + ((attr.astype(np.uint16) & 7) << 8)
            colour = (attr & 0x78) >> 3
            px = np.where(attr & 128, 15-(wx & 15), wx & 15)
            pen = g.tiles[code, wy & 15, px]
            front_limit = np.take([12, 12, 8, 8, 4, 4] + [0]*10, colour)
            front = pen < front_limit
            back = (pen != 15) & ~front
            bgpens = colour.astype(np.uint16)*16 + pen
            out[back] = bgpens[back]
        if not self.video_enable & 4:
            for o in range(0x1fc, -1, -4):
                code, attr, y, x = self.sprites[o:o+4]
                x -= (attr & 0x10) << 4
                pixels = g.sprites[code | ((attr & 0xe0) << 3)]
                if attr & 8:
                    pixels = pixels[:, ::-1]
                x0, x1, y0, y1 = max(0, x), min(256, x+16), y, min(256, y+16)
                if x0 >= x1 or y0 >= y1:
                    continue
                p = pixels[y0-y:y1-y, x0-x:x1-x]
                dest = out[y0:y1, x0:x1]
                mask = p != 15
                dest[mask] = (0x200 + (attr & 7)*16 + p.astype(np.uint16))[mask]
        if not self.video_enable & 2:
            out[front] = bgpens[front]
        if not self.control & 128:
            fg = np.frombuffer(self.mem, np.uint8)
            idx = (yy//8)*32 + xx//8
            attr = fg[0xd400+idx]
            code = fg[0xd000+idx].astype(np.uint16) + ((attr.astype(np.uint16) & 0xe0) << 3)
            pen = g.chars[code, yy & 7, xx & 7]
            mask = pen != 3
            out[mask] = (0x300 + (attr.astype(np.uint16) & 31)*4 + pen)[mask]
        if self.control & 64:
            out = out[::-1, ::-1]
        return out

    def render_rgb(self):
        values = np.frombuffer(self.mem, np.uint8)
        pal = values[0xd800:0xdc00].astype(np.uint16) | values[0xdc00:0xe000].astype(np.uint16) << 8
        rgb = np.stack([(pal >> 4 & 15)*17, (pal & 15)*17, (pal >> 8 & 15)*17], axis=1).astype(np.uint8)
        return rgb[self.render_raw()[16:240]]
