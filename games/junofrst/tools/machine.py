"""Juno First (MAME `junofrst`, Konami GX310, 1983): the reference board, from MAME konami/junofrst.cpp and
konami/tutankhm_v.cpp.

Main CPU: KONAMI-1 (MC6809E, opcodes encrypted, engine/m6809.py with konami1_opcode) at 18.432 MHz / 12 = 1.536 MHz.
Screen: 6.144 MHz pixel clock, 384 x 264 total, 256 x 224 visible (lines 16-239), 60.606 Hz, ROT90 (MAME's snapshot
is 224 wide, 768 high: every arcade column three pixel rows): 25344 CPU cycles a frame, 96 a line.  The VBLANK
(line 240) toggles a flip-flop; on every other frame (the second, the fourth ...) the IRQ is asserted while latch Q0
(the interrupt enable) is 1; writing Q0 = 0 clears it.  No NMI, no FIRQ.

Memory map (main CPU):
    $0000-$7FFF  w  video RAM: a 256 x 256 bitmap of 4 bpp, 128 bytes a line; byte = y * 128 + x / 2, the even x in the
                    low nibble.  Read back by the CPU (RAM)
    $8000-$800F  w  palette RAM, one byte a pen: bits 0-2 red (1k, 470, 220 ohm), 3-5 green, 6-7 blue (470, 220)
    $8010 r DSW2    $801C r watchdog    $8020 r SYSTEM    $8024 r P1    $8028 r P2    $802C r DSW1
    $8030-$8037  w  LS259 latch, bit 0 of the data: Q0 IRQ enable, Q1/Q2 coin counters, Q4 flip x, Q5 flip y
    $8040  w  sound IRQ trigger (0 -> 1 of bit 0; the Z80)    $8050  w  sound latch
    $8060  w  bank select (data & 15: the 4 KB window $9000-$9FFF = ROM $10000 + 4 KB * bank; banks 12-15 read 0)
    $8070-$8073  w  blitter: dest nibble address (hi, lo), source nibble address (hi, lo); the write to $8073 blits
    $8100-$8FFF  RAM            $9000-$9FFF  bank window            $A000-$FFFF  ROM (jfa_b9, jfb_b10, jfc_a10)
Blitter (junofrst_state::blitter_w): 16 x 16 pixels of 4 bpp from the 24 KB blitter ROM (nibble address src & $FFFC,
the high nibble first) to the video RAM at the destination nibble address (a row is 256 nibbles on); source pixels
that are 0 are skipped, the others are written (bit 0 of the source address set) or clear the pixel to 0 (clear).
Sound: a Z80 (14.318 MHz / 8), an AY-3-8910, an i8039 and a DAC behind the latches: the main CPU only writes (the
latch and the trigger), so it is not emulated here: sound_log keeps (frame, latch value) at each trigger.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from m6809 import M6809, konami1_opcode
import mamegfx as G

CPU_HZ = 1536000
LINE = 96                                  # CPU cycles a line (384 pixels / 4)
LINES = 264
FRAME = LINE * LINES                       # 25344
VBLANK_LINE = 240
VISIBLE = (16, 239)                        # MAME's visible lines

# MAME's defaults: DSW1 1 coin 1 credit both slots; DSW2 3 lives ($03), upright, difficulty 1 ($70), $08 unused,
# demo sounds on
DSW1, DSW2 = 0xFF, 0x7B


def load(name):
    return (EXTRACTED / "junofrst" / name).read_bytes()


PROGRAM = (("jfa_b9.bin", 0xA000), ("jfb_b10.bin", 0xC000), ("jfc_a10.bin", 0xE000))
BANKED = ("jfc1_a4.bin", "jfc2_a5.bin", "jfc3_a6.bin", "jfc4_a7.bin", "jfc5_a8.bin", "jfc6_a9.bin")
BLIT = ("jfs3_c7.bin", "jfs4_d7.bin", "jfs5_e7.bin")


def pens(palette):
    """16 pens' RGB from the palette RAM bytes (tutankhm_state::raw_to_rgb_func, RGB_MAXIMUM 224)."""
    rw, gw, bw = G.resistor_weights(0, 224, -1.0, ([1000, 470, 220], 470, 0), ([1000, 470, 220], 470, 0),
                                    ([470, 220], 470, 0))
    out = []
    for v in palette:
        bit = [(v >> k) & 1 for k in range(8)]
        out.append((G.combine(rw, *bit[0:3]), G.combine(gw, *bit[3:6]), G.combine(bw, *bit[6:8])))
    return np.array(out, np.uint8)


class Video:
    def render_nibbles(self, mem, flip=(False, False)):
        """The visible screen's pixel values [224, 256] (lines 16-239) from the main CPU's memory (64 KB image)."""
        vram = np.frombuffer(bytes(mem[0:0x8000]), np.uint8).reshape(256, 128)
        px = np.empty((256, 256), np.uint8)
        px[:, 0::2] = vram & 15
        px[:, 1::2] = vram >> 4
        lines = np.arange(VISIBLE[0], VISIBLE[1] + 1)
        if flip[1]:
            lines = lines ^ 255
        out = px[lines]
        if flip[0]:
            out = out[:, ::-1]
        return out

    def render_rgb(self, mem, flip=(False, False), rotate=True):
        """The visible picture as MAME's snapshot shows it: [768, 224, 3] rotated (ROT90, columns three rows), else
        [224, 256, 3]."""
        rgb = pens(mem[0x8000:0x8010])[self.render_nibbles(mem, flip)]
        if not rotate:
            return rgb
        return np.ascontiguousarray(np.repeat(np.rot90(rgb, 1), 3, axis=0))


class Juno:
    def __init__(self, dsw1=DSW1, dsw2=DSW2):
        self.rom = bytearray(0x10000)
        for n, a in PROGRAM:
            self.rom[a:a + 0x2000] = load(n)
        self.bank_rom = b"".join(load(n) for n in BANKED) + bytes(0x4000)      # 16 banks of 4 KB
        self.blit_rom = b"".join(load(n) for n in BLIT)
        self.mem = bytearray(0x10000)              # RAM areas (and the ROM copy, for render/compare convenience)
        self.mem[0xA000:] = self.rom[0xA000:]
        self.system = self.p1 = self.p2 = 0xFF
        self.dsw1, self.dsw2 = dsw1, dsw2
        self.latch = [0] * 8
        self.bank = 0
        self.blt = [0, 0, 0, 0]
        self.sound_latch = 0
        self.sound_trig = 0
        self.sound_log = []
        self.watchdog = 0
        self.frame = 0
        self.toggle = 1                            # (MAME's flip-flop starts at 0 and toggles once at the start-up
                                                   # VBLANK before frame 1: its first IRQ is the second VBLANK)
        self.blits = []                            # (src, dest) log when not None
        self.cpu = M6809(self.rd, self.wr, konami1_opcode(self.rd))
        self.video = None
        self.cpu.reset()
        self.next_vblank = VBLANK_LINE * LINE      # the first VBLANK: line 240 of the first frame

    def rd(self, a):
        if a < 0x9000 and (a < 0x8000 or a >= 0x8100 or a < 0x8010):
            return self.mem[a]
        if a >= 0xA000:
            return self.mem[a]
        if a >= 0x9000:
            return self.bank_rom[self.bank * 0x1000 + a - 0x9000]
        if a == 0x8010:
            return self.dsw2
        if a == 0x8020:
            return self.system
        if a == 0x8024:
            return self.p1
        if a == 0x8028:
            return self.p2
        if a == 0x802C:
            return self.dsw1
        return 0                                    # $801C the watchdog, the rest unmapped

    def wr(self, a, v):
        if a < 0x8010 or 0x8100 <= a < 0x9000:
            self.mem[a] = v
        elif 0x8030 <= a < 0x8038:
            q, b = a & 7, v & 1
            self.latch[q] = b
            if q == 0 and not b:
                self.cpu.set_irq(False)
        elif a == 0x8040:
            if self.sound_trig == 0 and v == 1:
                self.sound_log.append((self.frame, self.sound_latch))
            self.sound_trig = v
        elif a == 0x8050:
            self.sound_latch = v
        elif a == 0x8060:
            self.bank = v & 15
        elif 0x8070 <= a < 0x8074:
            self.blt[a - 0x8070] = v
            if a == 0x8073:
                self.blit()

    def blit(self):
        b = self.blt
        src = ((b[2] << 8) | b[3]) & 0xFFFC
        dest = (b[0] << 8) | b[1]
        copy = b[3] & 1
        if self.blits is not None:
            self.blits.append((src, dest, copy))
        rom, mem = self.blit_rom, self.mem
        for _ in range(16):
            for _ in range(16):
                i = src >> 1
                byte = rom[i] if i < len(rom) else 0
                data = byte & 15 if src & 1 else byte >> 4
                src += 1
                if data:
                    if not copy:
                        data = 0
                    j = dest >> 1
                    if j < 0x8000:
                        if dest & 1:
                            mem[j] = (mem[j] & 0x0F) | (data << 4)
                        else:
                            mem[j] = (mem[j] & 0xF0) | data
                dest += 1
            dest += 240

    def run_frame(self):
        """Runs to the next VBLANK and starts it (IRQ every other frame when enabled): the state MAME's frame_done
        callback sees."""
        c = self.cpu
        c.run(self.next_vblank - c.cycles)
        self.toggle ^= 1
        if self.toggle and self.latch[0]:
            c.set_irq(True)
        self.next_vblank += FRAME
        self.frame += 1

    def flip(self):
        """(flip x, flip y).  The game writes Q4 = Q5 = 1 from frame 28 on (upright) and WolfMAME 0.248 shows the
        unflipped RAM then: the picture is flipped while the bit is 0 (the 0.286 source's flip_screen_x_w sets the
        flip with the bit as is, which would show Juno First upside down: that difference is untested, 0.286 has no
        arcade binary here)."""
        return (not self.latch[4], not self.latch[5])

    def render_rgb(self, rotate=True):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem, self.flip(), rotate)


if __name__ == "__main__":
    import time
    m = Juno()
    t = time.time()
    for _ in range(300):
        m.run_frame()
    print("300 frames in %.1f s, pc %04X, sound commands %d" % (time.time() - t, m.cpu.pc, len(m.sound_log)))


class JunoPort(Juno):
    """The STE runtime's schedule (src/junofrst.s), one call of run_frame_port an arcade frame.

    The foreground is a task loop: $A010 LDX <$72; LDD ,X; ASLA; BCS $A010 (the queue at $8900-$893F, its read
    pointer at $8872; an entry with bit 7 set is empty); the IRQ handler ($A00A: JMP $A5D0, every other frame while
    latch Q0 is 1) plays the game and queues the tasks.  The port's idle point is $A010 with an empty queue: there the
    IRQ is delivered with $A010 as its return address; after its RTI the foreground runs the queued tasks until the
    queue is empty again.  A frame without IRQ runs nothing.  The boot: from the reset to the first idle.
    """
    IDLE = 0xA010
    IRQ = 0xA00A
    QPTR = 0x8872

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.booted = False
        self.irqs = 0

    def waits(self):
        m = self.mem
        return m[(m[self.QPTR] << 8) | m[self.QPTR + 1]] & 0x80 != 0

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
            self.run_to_idle()
            self.booted = True
        self.toggle ^= 1
        if self.toggle and self.latch[0] and not c.cc & 0x10:
            c.set_irq(True)
            c.step()                                  # (the entry: the state pushed, I set, PC = the vector)
            assert c.pc == self.IRQ, hex(c.pc)
            self.irqs += 1
            self.run_to_idle()
        self.frame += 1
