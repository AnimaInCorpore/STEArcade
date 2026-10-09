"""Commando World main CPU and video reference, from MAME capcom/commando.cpp.

Sound CPU/YM2203 output is omitted: the main CPU only writes a sound latch.
Opcode M1 reads are decrypted; operands and indexed-CB tails use the data bus.
"""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'engine'))
from z80 import Z80
from paths import build_dir

BUILD = build_dir('commando')
CYCLES_PER_LINE, LINES = 192, 262


def region(name):
    return (BUILD / (name + '.rom')).read_bytes()


class Program(bytes):
    def __new__(cls):
        obj = super().__new__(cls, region('maincpu'))
        obj.opcodes = region('opcodes')
        return obj


class CommandoZ80(Z80):
    def fetch_opcode(self):
        addr = self.pc
        self.pc = (addr + 1) & 0xffff
        return self.opcodes[addr] if addr < 0xc000 else self.rd8(addr)


def decode_gfx(data, planes, xoffs, yoffs, size, count):
    bits = np.unpackbits(np.frombuffer(data, np.uint8))
    pos = (np.arange(count, dtype=np.int64) * size)[:, None, None]
    pos = pos + np.array(yoffs)[None, :, None] + np.array(xoffs)[None, None, :]
    out = np.zeros(pos.shape, np.uint8)
    for i, offset in enumerate(planes):
        out |= bits[pos + offset] << (len(planes) - i - 1)
    return out


class Gfx:
    def __init__(self):
        self.chars = decode_gfx(region('chars'), [4, 0], [0,1,2,3,8,9,10,11],
                                [16*y for y in range(8)], 128, 1024)
        self.tiles = decode_gfx(region('tiles'), [0, 0x8000*8, 0x10000*8],
                                list(range(8)) + list(range(128,136)), [8*y for y in range(16)], 256, 1024)
        self.sprites = decode_gfx(region('sprites'), [0xc000*8+4, 0xc000*8, 4, 0],
                                  [0,1,2,3,8,9,10,11,256,257,258,259,264,265,266,267],
                                  [16*y for y in range(16)], 512, 768)
        prom = region('proms')
        # palette_device::RGB_444_PROMS uses resistor weights 0x0e/0x1f/0x43/0x8f.
        weights = [14, 31, 67, 143]
        self.rgb = np.array([[sum(weights[b] for b in range(4) if prom[c*256+i] & (1<<b))
                              for c in range(3)] for i in range(256)], np.uint8)


class Commando:
    def __init__(self):
        self.rom = Program()
        self.mem = bytearray(65536)
        self.mem[:0xc000] = self.rom
        self.inputs = [0xff, 0xff, 0xff, 0xff, 0x1f]
        self.scroll = bytearray(4)
        self.control = self.latch = 0
        self.sprites = bytearray(0x180)
        self.irqprom = region('irqprom')
        self.cpu = CommandoZ80(self.rd8, self.wr8)
        self.cpu.opcodes = self.rom.opcodes
        self.pending = None
        self.frame = 0
        self.gfx = None
        self.watch = None
        self.booted = False

    def rd8(self, addr):
        if 0xc000 <= addr <= 0xc004:
            return self.inputs[addr-0xc000]
        if addr < 0xc000 or addr >= 0xd000:
            return self.mem[addr]
        return 0xff

    def wr8(self, addr, value):
        if self.watch:
            self.watch(self.cpu.pc, addr, value)
        if addr >= 0xd000:
            self.mem[addr] = value
        elif addr == 0xc800:
            self.latch = value
        elif addr == 0xc804:
            self.control = value
        elif addr == 0xc806:
            self.sprites[:] = self.mem[0xfe00:0xff80]
        elif 0xc808 <= addr <= 0xc80b:
            self.scroll[addr-0xc808] = value

    def step(self):
        c = self.cpu
        if self.pending is not None and c.iff1 and not c.ei_delay:
            c.iff1 = c.iff2 = 0
            c.halted = False
            c.push(c.pc)
            c.pc = self.pending & 0x38
            c.cycles += 13
            self.pending = None
        # Clear EI's delay before executing the following instruction; that instruction
        # may itself be EI and restart the delay.
        c.ei_delay = False
        c.step()

    def run_frame(self):
        target = self.frame * CYCLES_PER_LINE * LINES
        for line in range(LINES):
            irq = self.irqprom[line & 255]
            if irq & 8:
                self.pending = 0xc7 | ((irq << 3) & 0x18)
            target += CYCLES_PER_LINE
            while self.cpu.cycles < target:
                self.step()
        self.frame += 1

    IDLE = 0x8001
    TOKEN = 0xc7fe

    def idle(self):
        return self.cpu.pc == self.IDLE and self.rd8(self.cpu.rd16(0xed82)) == 255

    def run_to_idle(self):
        for _ in range(2000000):
            if self.idle(): return
            self.cpu.step()
        raise RuntimeError(f'Foreground did not idle at {self.cpu.pc:04x}')

    def run_frame_port(self):
        if not self.booted:
            self.run_to_idle(); self.booted=True
        for vector in (8,16):
            c=self.cpu
            c.iff1=c.iff2=0
            c.push(self.TOKEN);c.pc=vector
            for _ in range(2000000):
                c.step()
                if c.pc==self.TOKEN:break
            else: raise RuntimeError('Interrupt did not return')
            c.pc=self.IDLE
        # Leave the idle hook once, then drain the foreground queue.
        self.cpu.step()
        self.run_to_idle()
        self.frame+=1

    def render_raw(self):
        if self.gfx is None:
            self.gfx = Gfx()
        g, mem = self.gfx, self.mem
        wide = np.empty((512,512), np.uint8)
        for idx in range(1024):
            attr = mem[0xdc00+idx]
            tile = g.tiles[mem[0xd800+idx]+((attr & 0xc0)<<2)]
            if attr & 0x10: tile = tile[:,::-1]
            if attr & 0x20: tile = tile[::-1]
            col, row = divmod(idx,32)
            wide[row*16:row*16+16,col*16:col*16+16] = tile + (attr & 15)*8
        sx = self.scroll[0] | (self.scroll[1]<<8)
        sy = self.scroll[2] | (self.scroll[3]<<8)
        bmp = wide[np.ix_((np.arange(256)+sy)&511, (np.arange(256)+sx)&511)].copy()
        flip = bool(self.control & 0x80)
        if flip:
            # Tilemap global flip also mirrors the scroll origin in its 512px map.
            bmp = wide[np.ix_((511-np.arange(256)+sy)&511, (511-np.arange(256)+sx)&511)].copy()
        for off in range(0x17c,-1,-4):
            code, attr, y, x = self.sprites[off:off+4]
            bank = attr >> 6
            if bank == 3: continue
            tile = g.sprites[code+bank*256]
            fx, fy = bool(attr & 4), bool(attr & 8)
            x -= (attr & 1)<<8
            if flip:
                x, y, fx, fy = 240-x, 240-y, not fx, not fy
            if fx: tile=tile[:,::-1]
            if fy: tile=tile[::-1]
            self.overlay(bmp, tile, x, y, 128+((attr>>4)&3)*16, 15)
        for idx in range(1024):
            attr = mem[0xd400+idx]
            tile = g.chars[mem[0xd000+idx]+((attr & 0xc0)<<2)]
            fx, fy = bool(attr & 0x10), bool(attr & 0x20)
            row, col = divmod(idx,32)
            x, y = col*8, row*8
            if flip: x,y,fx,fy = 248-x,248-y,not fx,not fy
            if fx: tile=tile[:,::-1]
            if fy: tile=tile[::-1]
            self.overlay(bmp,tile,x,y,192+(attr & 15)*4,3)
        return bmp

    @staticmethod
    def overlay(bmp,tile,x,y,base,transparent):
        h,w=tile.shape
        x0,x1,y0,y1=max(0,x),min(256,x+w),max(0,y),min(256,y+h)
        if x0>=x1 or y0>=y1: return
        src=tile[y0-y:y1-y,x0-x:x1-x]
        dst=bmp[y0:y1,x0:x1]
        mask=src!=transparent
        dst[mask]=src[mask]+base

    def render_rgb(self):
        bmp=self.render_raw()
        return self.gfx.rgb[bmp[16:240]].transpose(1,0,2)[::-1]


if __name__ == '__main__':
    import time
    from PIL import Image
    m=Commando();t=time.monotonic()
    for _ in range(int(sys.argv[1]) if len(sys.argv)>1 else 700): m.run_frame()
    Image.fromarray(m.render_rgb()).save(str(BUILD/'reference.png'))
    print(f'frame {m.frame}, PC {m.cpu.pc:04x}, {time.monotonic()-t:.1f}s; {BUILD}/reference.png')
