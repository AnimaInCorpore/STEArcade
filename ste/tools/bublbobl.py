"""Bubble Bobble (Taito, 1986, set bublbobl with the MC6801 protection MCU) arcade model
around the reference Z80 and 6801 (MAME bublbobl.cpp / bublbobl_m.cpp / bublbobl_v.cpp).

Main Z80 (6 MHz):  0000-7FFF ROM, 8000-BFFF ROM bank (16 KB x 4 of a78-05-1.52),
  C000-DCFF video RAM (tile codes: 2 bytes per tile, 64 per column strip), DD00-DFFF object
  RAM (4 bytes per strip), E000-F7FF RAM shared with the sub CPU, F800-F9FF palette RAM
  (RGBx444, big endian), FA00 sound command / answer, FA01 semaphores, FA03 sound reset,
  FA80 watchdog, FB00 NMI to the sub CPU, FB40 bank / resets / video enable / flip,
  FC00-FFFF RAM shared with the MCU.  IM 2: the MCU interrupts, the vector low byte is
  the byte at FC00.
Sub Z80 (6 MHz): 0000-7FFF ROM, E000-F7FF shared RAM; IRQ at the vertical blank.
Sound Z80 (3 MHz): YM2203 + YM3526 (not emulated; status reads 0).
MCU (1 MHz): ports 1-4 read the inputs / DIP switches and move bytes to and from FC00-FFFF.
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from z80 import Z80
from m6801 import M6801

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROMDIR = os.path.join(ROOT, "assets", "roms", "extracted", "bublbobl")

CYCLES_PER_LINE = 384
LINES = 264
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES       # 59.19 Hz
VBLANK_LINE = 240
VBLANK_END = 16


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def skip_tests(main, sub):
    """The boot self-tests patched out of the main and the sub CPU's ROMs (the port skips them completely):
    the RAM tests of $E000-$F7FF and $FC01-$FFFF (jumps past them; they leave the RAM zero, which it is
    already), the delay loop at $0138 (one pass instead of 16384), the sub CPU's checksum of its 32 KB
    ROM at $017B (a return).  The MCU handshake, the vector setup and the MCU's own checksum stay."""
    original = bytes(main)
    main = bytearray(main)
    sub = bytearray(sub)
    assert main[0xC1:0xC4] == bytes([0x21, 0x00, 0xE0]) and main[0xF1:0xF4] == bytes([0x21, 0x01, 0xFC])
    assert main[0x138:0x13B] == bytes([0x21, 0x00, 0x40]) and sub[0x17B] == 0x21
    main[0xC1:0xC4] = bytes([0xC3, 0xE8, 0x00])          # jp $00E8
    main[0xF1:0xF4] = bytes([0xC3, 0x18, 0x01])          # jp $0118
    main[0x138:0x13B] = bytes([0x21, 0x01, 0x00])        # ld hl,$0001
    sub[0x17B] = 0xC9                                    # ret
    # the game checksums main ROM bytes $0001-$0EDC one per frame (E6FD += (de), pc $484B) and compares
    # with $E6FE at the end: dead bytes of the old RAM test ($C4: the operand of its `ld de`) make the sum
    # the original's
    orig = sum(original[1:0xEDD])
    main[0xC4] = (main[0xC4] + orig - sum(main[1:0xEDD])) & 0xFF
    assert sum(main[1:0xEDD]) & 0xFF == orig & 0xFF
    return bytes(main), bytes(sub)


GFX_FILES = [["a78-09.12", "a78-10.13", "a78-11.14", "a78-12.15", "a78-13.16", "a78-14.17"],
             ["a78-15.30", "a78-16.31", "a78-17.32", "a78-18.33", "a78-19.34", "a78-20.35"]]


def decode_tiles():
    """16384 tiles of 8 x 8, 4 bits per pixel (the ROMs are inverted)."""
    data = bytearray(0x80000)
    for half, files in enumerate(GFX_FILES):
        pos = half * 0x40000
        for f in files:
            d = load(f)
            data[pos:pos + len(d)] = d
            pos += 0x8000
    # 0x30000-0x3ffff and 0x70000-0x7ffff are empty (inverted: 0xff)
    data = bytearray(b ^ 0xFF for b in data)
    arr = np.frombuffer(bytes(data), np.uint8)
    n = 0x40000 // 16                      # 16384 tiles of 16 bytes (the planes are in the two halves)
    planes_bits = (0, 4, 0x40000 * 8, 0x40000 * 8 + 4)
    xoffs = (3, 2, 1, 0, 8 + 3, 8 + 2, 8 + 1, 8 + 0)
    out = np.zeros((n, 8, 8), np.uint8)
    base = np.arange(n) * 128
    for y in range(8):
        for x in range(8):
            v = np.zeros(n, np.uint8)
            for po in planes_bits:                    # first plane is the most significant
                off = base + po + xoffs[x] + y * 16
                bit = (arr[off >> 3] >> (7 - (off & 7))) & 1
                v = (v << 1) | bit
            out[:, y, x] = v
    return out


class Bublbobl:
    def __init__(self, tests=False):
        """tests=True keeps the boot self-tests (the arcade's own behaviour)"""
        main = load("a78-06-1.51") + bytes(0x8000)
        self.main_rom = bytearray(main[:0x8000])
        big = load("a78-05-1.52")
        self.banks = [big[i * 0x4000:(i + 1) * 0x4000] for i in range(4)] + [bytes(0x4000)] * 4
        self.sub_rom = load("a78-08.37")
        if not tests:
            self.main_rom, self.sub_rom = [bytearray(x) if i == 0 else x for i, x in enumerate(skip_tests(bytes(self.main_rom), self.sub_rom))]
        self.snd_rom = load("a78-07.46")
        self.mcu_rom = load("a78-01.17")
        self.vram = bytearray(0xDD00 - 0xC000)       # C000-DCFF
        self.oram = bytearray(0x300)                 # DD00-DFFF
        self.shared = bytearray(0x1800)              # E000-F7FF
        self.pal = bytearray(0x200)                  # F800-F9FF
        self.mcram = bytearray(0x400)                # FC00-FFFF
        self.snd_ram = bytearray(0x1000)             # 8000-8FFF
        self.bank = 0
        self.video_enable = False
        self.flip = False
        self.dsw0, self.dsw1 = 0xFE, 0xFF
        self.in0, self.in1, self.in2 = 0x03, 0xFF, 0xFF      # IN0: tilt / service (low), coins (high)
        self.m2s = self.s2m = 0
        self.m2s_pending = self.s2m_pending = False
        self.snd_nmi_en = False
        self.sreset = False
        self.snd_log = []
        self.io_log = []
        self.frame = 0
        # MCU glue
        self.p1_out = self.p2_out = self.p3_out = self.p4_out = 0
        self.p3_in = 0
        self.irq_main = False
        self.main = Z80(self.rd_main, self.wr_main)
        self.sub = Z80(self.rd_sub, self.wr_sub)
        self.snd = Z80(self.rd_snd, self.wr_snd)
        self.mcu = M6801(self.mcu_rom, in_p1=lambda: self.in0, in_p3=lambda: self.p3_in,
                         out_p1=self.mcu_p1_w, out_p2=self.mcu_p2_w, out_p3=self.mcu_p3_w, out_p4=self.mcu_p4_w)
        self.sub_held = True
        self.mcu_held = True
        self.sub_irq = False
        self.tiles = None
        self.port_mode = False
        self.booted = [False, False, False]
        self.in_sub_nmi = False
        self.rnd_state = 0x1234

    # ---- main CPU bus --------------------------------------------------
    def rd_main(self, a):
        if a < 0x8000:
            return self.main_rom[a]
        if a < 0xC000:
            return self.banks[(self.bank ^ 4) & 7][a - 0x8000]
        if a < 0xDD00:
            return self.vram[a - 0xC000]
        if a < 0xE000:
            return self.oram[a - 0xDD00]
        if a < 0xF800:
            return self.shared[a - 0xE000]
        if a < 0xFA00:
            return self.pal[a - 0xF800]
        if a < 0xFC00:
            if a < 0xFA80:
                if (a & 3) == 0:
                    self.s2m_pending = False
                    return self.s2m
                if (a & 3) == 1:
                    return 0xFC | (2 if self.m2s_pending else 0) | (1 if self.s2m_pending else 0)
            return 0xFF
        return self.mcram[a - 0xFC00]

    def wr_main(self, a, v):
        if a < 0xC000:
            return
        if a < 0xDD00:
            self.vram[a - 0xC000] = v
        elif a < 0xE000:
            self.oram[a - 0xDD00] = v
        elif a < 0xF800:
            self.shared[a - 0xE000] = v
        elif a < 0xFA00:
            self.pal[a - 0xF800] = v
        elif a < 0xFC00:
            if a < 0xFA80:
                if (a & 3) == 0:
                    self.m2s = v
                    self.snd_log.append((self.frame, v))
                    if not self.port_mode:           # (the port has no sound CPU: nothing pending)
                        self.m2s_pending = True
                        if self.snd_nmi_en and not self.sreset:
                            self.snd.nmi()
                elif (a & 3) == 3:
                    self.sreset_w(v)
            elif a < 0xFB00:
                pass
            elif a < 0xFB40:
                if not self.sub_held:
                    if self.port_mode:
                        if self.booted[1] and not self.in_sub_nmi:
                            self.in_sub_nmi = True
                            self.run_handler(self.sub, nmi=True)
                            self.in_sub_nmi = False
                    else:
                        self.sub.nmi()
            elif a < 0xFB80:
                self.bankswitch_w(v)
        else:
            self.mcram[a - 0xFC00] = v

    def sreset_w(self, v):
        if v and not self.sreset:
            self.s2m_pending = False
            self.snd_nmi_en = False
        if not v and self.sreset:
            self.snd.reset()
        self.sreset = bool(v)

    def bankswitch_w(self, v):
        self.bank = v & 7
        sub_run = bool(v & 0x10)
        if sub_run and self.sub_held:
            self.sub.reset()
            self.booted[1] = False
        self.sub_held = not sub_run
        mcu_run = bool(v & 0x20)
        if mcu_run and self.mcu_held:
            self.mcu.reset()
            self.booted[2] = False
        self.mcu_held = not mcu_run
        self.video_enable = bool(v & 0x40)
        self.flip = bool(v & 0x80)

    # ---- sub CPU -------------------------------------------------------
    def rd_sub(self, a):
        if a < 0x8000:
            return self.sub_rom[a]
        if 0xE000 <= a < 0xF800:
            return self.shared[a - 0xE000]
        return 0xFF

    def wr_sub(self, a, v):
        if 0xE000 <= a < 0xF800:
            self.shared[a - 0xE000] = v

    # ---- sound CPU -----------------------------------------------------
    def rd_snd(self, a):
        if a < 0x8000 or a >= 0xE000:
            return self.snd_rom[a] if a < len(self.snd_rom) else 0xFF
        if a < 0x9000:
            return self.snd_ram[a - 0x8000]
        if 0xB000 <= a < 0xC000:
            k = a & 3
            if k == 0:
                self.m2s_pending = False
                return self.m2s
            if k == 1:
                return 0xFC | (2 if self.m2s_pending else 0) | (1 if self.s2m_pending else 0)
        return 0

    def wr_snd(self, a, v):
        if 0x8000 <= a < 0x9000:
            self.snd_ram[a - 0x8000] = v
        elif 0xB000 <= a < 0xC000:
            k = a & 3
            if k == 0:
                self.s2m = v
                self.s2m_pending = True
            elif k == 1:
                self.snd_nmi_en = True
                if self.m2s_pending:
                    self.snd.nmi()
            elif k == 2:
                self.snd_nmi_en = False

    # ---- MCU glue ------------------------------------------------------
    def mcu_p1_w(self, v):
        if (self.p1_out & 0x40) and not (v & 0x40):
            self.irq_main = True
        self.p1_out = v

    def mcu_p2_w(self, v):
        if not (self.p2_out & 0x10) and (v & 0x10):
            addr = self.p4_out | ((v & 0x0F) << 8)
            if self.p1_out & 0x80:                 # read
                if (addr & 0x0800) == 0:
                    self.p3_in = (self.dsw0, self.dsw1, self.in1, self.in2)[addr & 3]
                elif (addr & 0x0C00) == 0x0C00:
                    self.p3_in = self.mcram[addr & 0x3FF]
                self.mcu.pulse_is3()
            else:                                  # write
                if (addr & 0x0C00) == 0x0C00:
                    self.mcram[addr & 0x3FF] = self.p3_out
        self.p2_out = v

    def mcu_p3_w(self, v):
        self.p3_out = v

    def mcu_p4_w(self, v):
        self.p4_out = v

    # ---- running -------------------------------------------------------
    def run_frame(self):
        main, sub, snd, mcu = self.main, self.sub, self.snd, self.mcu
        t0 = main.cycles
        s0 = snd.cycles
        for line in range(LINES):
            t = t0 + (line + 1) * CYCLES_PER_LINE
            if line == VBLANK_LINE:
                self.sub_irq = True
            if line == VBLANK_LINE:
                mcu.irq1 = True
            if line == VBLANK_END:
                mcu.irq1 = False
            while main.cycles < t:
                if self.irq_main and main.iff1:
                    self.irq_main = False
                    main.irq(self.mcram[0])
                main.step()
            if self.sub_held:
                sub.cycles = max(sub.cycles, t)
            else:
                while sub.cycles < t:
                    if self.sub_irq and sub.iff1:
                        self.sub_irq = False
                        sub.irq()
                    sub.step()
            end = s0 + (line + 1) * (CYCLES_PER_LINE // 2)             # 3 MHz
            if self.sreset:
                snd.cycles = max(snd.cycles, end)
            else:
                while snd.cycles < end:
                    snd.step()
            if not self.mcu_held:
                mcu.run(64)
        self.frame += 1

    def rnd(self):
        """What the port's z80_rnd gives for `ld a,r`: a 16-bit shift register byte."""
        s = self.rnd_state
        s = (s >> 1) ^ (0xB400 if s & 1 else 0)
        self.rnd_state = s
        return s & 0xFF

    # ---- the STE runtime's schedule -------------------------------------
    IDLE_MAIN, IDLE_SUB = 0x01ED, 0x000A

    def run_handler(self, cpu, nmi=False, vec=0xFF):
        """Run an interrupt handler of a Z80 to its return (the interrupted pc and sp)."""
        sp0, pc0 = cpu.sp, cpu.pc
        if nmi:
            cpu.nmi()
        elif not cpu.irq(vec):
            return False
        n = 0
        while not (cpu.sp == sp0 and cpu.pc == pc0):
            cpu.step()
            n += 1
            if n > 3_000_000:
                raise RuntimeError("handler of %04X did not return" % pc0)
        return True

    def run_mcu_irq(self):
        mcu = self.mcu
        if mcu.cc & 0x10:
            return False
        sp0, pc0 = mcu.sp, mcu.pc
        mcu.take(0xFFF8)
        n = 0
        while not (mcu.sp == sp0 and mcu.pc == pc0):
            mcu.step()
            n += 1
            if n > 1_000_000:
                raise RuntimeError("MCU handler did not return")
        return True

    def run_to_idle(self, cpu, idle):
        k = 0
        while cpu.pc != idle:
            cpu.step()
            k += 1
            if k > 50_000_000:
                raise RuntimeError("CPU does not reach its idle loop at %04X (pc %04X)" % (idle, cpu.pc))

    def run_frame_port(self):
        """One frame as the STE runtime schedules it: at the vertical blank the MCU's IRQ1
        handler (it raises the main CPU's interrupt), then the main CPU's interrupt handler
        and the sub CPU's, each to completion; the sub CPU's NMI (a write to FB00) runs at the
        write.  The foreground threads only boot to their idle loops."""
        self.port_mode = True
        main, sub = self.main, self.sub
        main.r_hook = sub.r_hook = self.rnd
        if not self.booted[0]:
            k = 0
            while main.pc != self.IDLE_MAIN:
                main.step()
                k += 1
                if main.pc in self.YIELD_MAIN:
                    self.boot_turns()
                if k > 50_000_000:
                    raise RuntimeError("main CPU does not reach its idle loop (pc %04X)" % main.pc)
            self.booted[0] = True
        self.boot_turns()
        if not self.mcu_held:
            self.mcu.irq1 = False
            self.run_mcu_irq()
        if self.irq_main and main.iff1 and self.booted[0]:
            self.irq_main = False
            self.run_handler(main, vec=self.mcram[0])
        if not self.sub_held and self.booted[1] and sub.iff1:
            self.run_handler(sub)
        self.frame += 1

    # the main CPU's boot waits for the MCU's handshake ($FC85 = $37) at these pcs
    YIELD_MAIN = {0x0158, 0x015B, 0x015D}

    def boot_turns(self):
        """The booting chips run their boot code to their idle loops (the MCU's init, the sub CPU)."""
        if not self.mcu_held and not self.booted[2]:
            self.run_to_idle_mcu()
            self.booted[2] = True
        if not self.sub_held and not self.booted[1]:
            self.run_to_idle(self.sub, self.IDLE_SUB)
            self.booted[1] = True

    def run_to_idle_mcu(self):
        mcu = self.mcu
        k = 0
        while mcu.pc != 0xF043 or mcu.cc & 0x10:
            mcu.step()
            k += 1
            if k > 5_000_000:
                raise RuntimeError("MCU does not reach its idle loop (pc %04X)" % mcu.pc)

    # ---- rendering -----------------------------------------------------
    def palette_rgb(self):
        p = np.frombuffer(bytes(self.pal), np.uint8).reshape(256, 2)
        r = (p[:, 0] >> 4) * 17
        g = (p[:, 0] & 15) * 17
        b = (p[:, 1] >> 4) * 17
        return np.stack([r, g, b], 1).astype(np.uint8)

    def render_raw(self):
        """256 x 224 bitmap of palette indices (255 = background)."""
        if self.tiles is None:
            self.tiles = decode_tiles()
        bmp = np.full((256, 256), 255, np.uint8)
        if not self.video_enable:
            return bmp[16:240]
        prom = load("a71-25.41")
        vram, oram = self.vram, self.oram
        sx = 0
        for offs in range(0, 0x300, 4):
            if oram[offs:offs + 4] == b"\0\0\0\0":
                continue
            gfx_num = oram[offs + 1]
            gfx_attr = oram[offs + 3]
            prom_line = 0x80 + ((gfx_num & 0xE0) >> 1)
            gfx_offs = (gfx_num & 0x1F) * 0x80
            if (gfx_num & 0xA0) == 0xA0:
                gfx_offs |= 0x1000
            sy = -oram[offs]
            for yc in range(32):
                pl = prom[prom_line + yc // 2]
                if pl & 0x08:
                    continue
                if not pl & 0x04:
                    sx = oram[offs + 2]
                    if gfx_attr & 0x40:
                        sx -= 256
                for xc in range(2):
                    goffs = gfx_offs + xc * 0x40 + (yc & 7) * 2 + (pl & 3) * 0x10
                    b1 = vram[goffs + 1]
                    code = vram[goffs] + 256 * (b1 & 3) + 1024 * (gfx_attr & 15)
                    color = (b1 & 0x3C) >> 2
                    x = sx + xc * 8
                    y = (sy + yc * 8) & 0xFF
                    t = self.tiles[code]
                    if b1 & 0x40:
                        t = t[:, ::-1]
                    if b1 & 0x80:
                        t = t[::-1, :]
                    if self.flip:
                        x, y = 248 - x, 248 - y
                        t = t[::-1, ::-1]
                    for yy in range(8):
                        ry = y + yy
                        if not 0 <= ry < 256:
                            continue
                        for xx in range(8):
                            rx = x + xx
                            if 0 <= rx < 256 and t[yy, xx] != 15:
                                bmp[ry, rx] = color * 16 + t[yy, xx]
            sx += 16
        return bmp[16:240]

    def render_rgb(self):
        bmp = self.render_raw()
        pal = np.concatenate([self.palette_rgb(), np.zeros((1, 3), np.uint8)])
        return pal[bmp]


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)


if __name__ == "__main__":
    import time
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    out = sys.argv[2] if len(sys.argv) > 2 else "bublbobl.png"
    m = Bublbobl()
    t0 = time.time()
    for f in range(frames):
        m.run_frame()
        if f % 60 == 0:
            print("frame", f, "pc %04X %04X %04X mcu %04X" % (m.main.pc, m.sub.pc, m.snd.pc, m.mcu.pc),
                  "bank", m.bank, "held", m.sub_held, m.mcu_held)
    print("%.1f s, %.1f frames/s" % (time.time() - t0, frames / (time.time() - t0)))
    save_png(m.render_rgb(), out)
    print("wrote", out)
