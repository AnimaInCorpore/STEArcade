"""Yie Ar Kung-Fu (MAME `yiear`, Konami GX407, 1985): the reference board, from MAME konami/yiear.cpp.

Main CPU: a plain MC6809E (no encryption) at 18.432 MHz / 12 = 1.536 MHz.  Screen: 6.144 MHz pixel clock, 384 x 264
total, 256 x 224 visible (lines 16-239), 60.606 Hz: 25344 CPU cycles a frame, 96 a line.  The VBLANK (line 240)
asserts IRQ while control bit 2 is 1; writing that bit 0 clears it.  A timer every 32 lines from line 16 (eight a
frame, the music tempo) asserts NMI while control bit 1 is 1; writing that bit 0 clears the line.  The 6809's NMI is
edge triggered, so the game toggles bit 1 to take the next one.

Memory map (main CPU):
    $0000 r  VLM5030 busy                  $4000 w  control: 0 flip screen, 1 NMI enable, 2 IRQ enable, 3/4 coin counters
    $4800 w  sound latch                   $4900 w  copy the latch to the SN76489A
    $4A00 w  VLM5030 control (bit 1 ST, bit 2 RST)   $4B00 w  VLM5030 data
    $4C00 r  DSW2   $4D00 r DSW3   $4E00 r SYSTEM  $4E01 r P1  $4E02 r P2  $4E03 r DSW1    $4F00 w  watchdog
    $5000-$502F sprite RAM 1 (attr, y), $5400-$542F sprite RAM 2 (x, code), $5000-$57FF all RAM
    $5800-$5FFF video RAM (attr, code) of a 32 x 32 tilemap, $8000-$FFFF ROM; anything else reads 0.
Sound: an SN76489A (the main CPU writes it through the latch) and a VLM5030 speech chip; the writes are logged.

Video: 32 x 32 tiles of 8x8 4bpp (512), 24 sprites 16x16 4bpp (512) drawn from the last entry to the first, a 32-entry
palette PROM (3-3-2 weights).  Sprite pens 0-15, tile pens 16-31; sprite pen 0 is transparent.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import EXTRACTED
from m6809 import M6809
from vlm5030 import VLM5030
import vlm_frames
import mamegfx as G

CPU_HZ = 1536000
LINE = 96
LINES = 264
FRAME = LINE * LINES                       # 25344
VBLANK_LINE = 240
NMI_FIRST, NMI_EVERY = 16, 32              # the 16v timer's lines
VISIBLE = (0, 255, 16, 239)
SKEW = 2906                                # CPU cycles that MAME runs before the screen's time zero (found by the boot RAM test)

# MAME's defaults: DSW1 1 coin 1 credit, DSW2 1 life ($03), upright, bonus 30000 80000, normal ($10), $40 unused,
# demo sounds on; DSW3 flip off, single controls, service off
DSW1, DSW2, DSW3 = 0xFF, 0x5B, 0xFF


def load(name):
    return (EXTRACTED / "yiear" / name).read_bytes()


def palette_rgb(prom, blue=(0x52, 0xAD)):
    """the 32 palette entries: red / green bits 0-2 / 3-5 weights 0x21, 0x47, 0x97, blue bits 6-7 weights 0x52, 0xAD
    (the driver's own sums, not a resistor model)"""
    pal = []
    for i in range(32):
        v = prom[i]
        r = 0x21 * (v & 1) + 0x47 * (v >> 1 & 1) + 0x97 * (v >> 2 & 1)
        g = 0x21 * (v >> 3 & 1) + 0x47 * (v >> 4 & 1) + 0x97 * (v >> 5 & 1)
        b = blue[0] * (v >> 6 & 1) + blue[1] * (v >> 7 & 1)
        pal.append((r, g, b))
    return np.array(pal, np.uint8)


class Video:
    def __init__(self, blue=(0x52, 0xAD)):
        prom = load("407c10.1g")
        gfx1 = load("407_c01.6h") + load("407_c02.7h")
        gfx2 = b"".join(load(n) for n in ("407_d05.16h", "407_d06.17h", "407_d03.14h", "407_d04.15h"))
        half = G.rgn_frac(len(gfx1), 1, 2)
        self.tiles = G.decode_gfx(gfx1, 8, 8, half // 128, [4, 0, half + 4, half],
                                  [0, 1, 2, 3, 64, 65, 66, 67], list(range(0, 64, 8)), 128)
        half = G.rgn_frac(len(gfx2), 1, 2)
        sx = [0, 1, 2, 3, 64, 65, 66, 67, 128, 129, 130, 131, 192, 193, 194, 195]
        sy = [0, 8, 16, 24, 32, 40, 48, 56, 256, 264, 272, 280, 288, 296, 304, 312]
        self.sprites = G.decode_gfx(gfx2, 16, 16, half // 512, [4, 0, half + 4, half], sx, sy, 512)
        self.pens = palette_rgb(prom, blue)

    def render_raw(self, mem, flip=False):
        """The screen's pens [256 rows, 256] (rows 16-239 visible) from the main CPU's memory (64 KB image)."""
        v = np.frombuffer(bytes(mem[0x5800:0x6000]), np.uint8).reshape(32, 32, 2)
        attr, low = v[:, :, 0].astype(np.int32), v[:, :, 1].astype(np.int32)
        codes = low | ((attr & 0x10) << 4)
        pix, _ = G.tile_pixmap(self.tiles, codes, np.zeros((32, 32), np.int32), attr & 0x80, attr & 0x40, 32, 32, 16, 16)
        bm = pix.astype(np.int16)
        if flip:
            bm = bm[::-1, ::-1].copy()                  # (the tilemap flipped: x and y)
        s1, s2 = mem[0x5000:0x5030], mem[0x5400:0x5430]
        for offs in range(0x2E, -1, -2):
            attr = s1[offs]
            code = s2[offs + 1] + 256 * (attr & 1)
            sy = 240 - s1[offs + 1] + (1 if offs < 0x26 else 0)
            fy = attr & 0x80
            if flip:                                     # MAME: sy = 240 - sy and flip y, x and flip x as they are
                sy = s1[offs + 1] + (1 if offs < 0x26 else 0)
                fy = not fy
            G.draw_gfx(bm, VISIBLE, self.sprites, code, 0, not attr & 0x40, fy, s2[offs], sy,
                       lambda s: s == 0)
        return bm

    def render_rgb(self, mem, flip=False):
        """The visible picture [224, 256, 3] as MAME's snapshot shows it."""
        raw = self.render_raw(mem, flip)[VISIBLE[2]:VISIBLE[3] + 1]
        return self.pens[raw]


class YieAr:
    def __init__(self, dsw1=DSW1, dsw2=DSW2, dsw3=DSW3):
        rom = bytearray(0x10000)
        rom[0x8000:0xC000] = load("407_i08.10d")
        rom[0xC000:0x10000] = load("407_i07.8d")
        self.rom = bytes(rom)
        self.mem = bytearray(0x10000)              # RAM and the ROM copy
        self.mem[0x8000:] = self.rom[0x8000:]
        self.system = self.in1 = self.in2 = 0xFF
        self.dsw1, self.dsw2, self.dsw3 = dsw1, dsw2, dsw3
        self.control = 0
        self.sn_latch = 0
        self.sound_log = []                        # (frame, kind, value): SN76489A data, VLM control, VLM data
        self.watchdog = 0
        self.frame = 0
        self.vlm = VLM5030(load('407_c09.8b'))      # (only BSY matters here; tools/sound.py renders the speech)
        self.vlm_data = 0
        self.vlm_done = 0                         # samples rendered
        self.cpu = M6809(self.rd, self.wr)
        self.video = None
        self.cpu.reset()
        self.cpu.cycles -= SKEW
        self.next_nmi = NMI_FIRST * LINE
        self.next_vblank = VBLANK_LINE * LINE

    def rd(self, a):
        if a >= 0x8000 or 0x5000 <= a < 0x6000:
            return self.mem[a]
        if a == 0x4E00:
            return self.system
        if a == 0x4E01:
            return self.in1
        if a == 0x4E02:
            return self.in2
        if a == 0x4E03:
            return self.dsw1
        if a == 0x4C00:
            return self.dsw2
        if a == 0x4D00:
            return self.dsw3
        if a == 0:
            self.vlm_update()
            return self.vlm.bsy_r()
        return 0

    def wr(self, a, v):
        if 0x5000 <= a < 0x6000:
            self.mem[a] = v
        elif a == 0x4000:
            old, self.control = self.control, v
            if old & 2 and not v & 2:
                self.cpu.set_nmi(False)
            if old & 4 and not v & 4:
                self.cpu.set_irq(False)
        elif a == 0x4800:
            self.sn_latch = v
        elif a == 0x4900:
            self.sound_log.append((self.frame, 'sn', self.sn_latch))
        elif a == 0x4A00:
            self.sound_log.append((self.frame, 'vc', v))
            self.vlm_update()
            self.vlm.data_w(self.vlm_data)
            self.vlm.st_w(v >> 1 & 1)
            self.vlm.rst_w(v >> 2 & 1)
        elif a == 0x4B00:
            self.sound_log.append((self.frame, 'vd', v))
            self.vlm_data = v
        elif a == 0x4F00:
            self.watchdog += 1

    def vlm_time(self):
        """the time of a VLM access in CPU cycles"""
        return self.cpu.cycles

    def vlm_update(self):
        """the VLM5030 rendered up to now (one sample per 440 chip clocks of 3.579545 MHz); an idle chip is skipped"""
        n = self.vlm_time() * 3579545 // (CPU_HZ * 440)
        if n > self.vlm_done:
            if self.vlm.phase != 1:                  # (PH_IDLE)
                self.vlm.render(n - self.vlm_done)
            self.vlm_done = n

    def run_frame(self):
        """Runs to the next VBLANK and starts it (IRQ when enabled): the state MAME's frame_done callback sees."""
        c = self.cpu
        while True:
            t = min(self.next_nmi, self.next_vblank)
            c.run(t - c.cycles)
            if t == self.next_nmi:
                if self.control & 2:
                    c.set_nmi(True)
                self.next_nmi += NMI_EVERY * LINE
            if t == self.next_vblank:
                if self.control & 4:
                    c.set_irq(True)
                self.next_vblank += FRAME
                break
        self.frame += 1

    def video_raw(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_raw(self.mem, bool(self.control & 1))

    def render_rgb(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, bool(self.control & 1))


if __name__ == "__main__":
    import time
    m = YieAr()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, sound writes %d" % (time.time() - t, m.cpu.pc, len(m.sound_log)))


class YieArPort(YieAr):
    """The STE runtime's schedule (src/yiear.s), one call of run_frame_port an arcade frame.

    The boot self-tests (RAM, ROM checksum: about 50 frames, interrupts off) are run once without the interrupts, up to
    the jump to $8000 (ENTRY); the port starts there.  The foreground is a task loop: $807C LDX <$DA; LDD ,X; ASLA;
    BCS $807C (the queue at $52C0-$52FF, its read pointer at $51DA; an entry with bit 7 set is empty); the IRQ
    handler ($897D) plays the game and queues the tasks, the NMI handler ($C78E, eight a frame in the arcade: the
    music tempo) plays the sound channels.  The port's idle point is $807C with an empty queue: there the eight NMIs
    BSY of the VLM5030 is frame based (vlm_frames).  A frame: the IRQ (control bit 2, I clear) with $807C as the return
    address, the queued tasks to the idle point, then the eight NMIs (bit 1), each followed by the tasks it queued.
    """
    ENTRY = 0x8000
    IDLE = 0x807C
    IRQ = 0x897D
    NMI = 0xC78E
    QPTR = 0x51DA
    NMIS = 8

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.booted = False
        self.irqs = self.nmis = 0
        self.vbusy, self.vend, self.vst, self.vrst = False, None, 0, 0
        self.nmi_cycles = self.irq_cycles = 0

    def rd(self, a):
        if a == 0:
            if self.vbusy and self.vend is not None and self.frame >= self.vend:
                self.vbusy = False
            return int(self.vbusy)
        return super().rd(a)

    def wr(self, a, v):
        if a == 0x4A00:
            # the port has no time between its frames: BSY is high from ST's rise until the phrase's length in frames
            # (tools/vlm_frames.py) after ST's fall, counted from the frame the phrase starts in; RST rising ends it
            self.sound_log.append((self.frame, 'vc', v))
            st = v >> 1 & 1
            rst = v >> 2 & 1
            if rst and not self.vrst and self.vbusy:      # RST rising while BSY: the chip resets, the speech stops
                self.vbusy, self.vend = False, None
            self.vrst = rst
            if st and not self.vst:
                self.vbusy, self.vend = True, None
            elif self.vst and not st:
                self.vend = self.frame + vlm_frames.frames()[self.vlm_data]
            self.vst = st
        elif a == 0x4B00:
            self.sound_log.append((self.frame, 'vd', v))
            self.vlm_data = v
        else:
            super().wr(a, v)

    def waits(self):
        m = self.mem
        return m[(m[self.QPTR] << 8) | m[self.QPTR + 1]] & 0x80 != 0

    def boot(self):
        c = self.cpu
        n = 0
        while c.pc != self.ENTRY:
            c.step()
            n += 1
            if n > 40000000:
                raise RuntimeError('the self-test did not end (pc %04X)' % c.pc)
        del self.sound_log[:]                       # (the self-test's SN76489A silencing is not the port's)

    def run_to_idle(self, limit=20000000):
        """the foreground (at least one instruction) until the task queue is empty at the idle point"""
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc == self.IDLE and self.waits():
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        if not self.booted:
            self.boot()
            self.run_to_idle()
            self.booted = True
        if self.control & 4 and not c.cc & 0x10:
            t = c.cycles
            c.set_irq(True)
            c.step()                                  # (the entry: the state pushed, I set, PC = the vector)
            assert c.pc == self.IRQ, hex(c.pc)
            self.irqs += 1
            self.run_to_idle()
            self.irq_cycles += c.cycles - t
        for _ in range(self.NMIS):
            if not self.control & 2:
                break
            t = c.cycles
            c.set_nmi(True)
            c.step()
            assert c.pc == self.NMI, hex(c.pc)
            self.nmis += 1
            self.run_to_idle()
            self.nmi_cycles += c.cycles - t
        self.frame += 1
