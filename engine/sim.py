"""STE system simulation on Musashi: runs a port's .PRG without Hatari.

Models what the runtime needs: GEMDOS (Super, Fopen/Fread/Fclose/Fcreate/Fwrite, Pterm),
the VBL interrupt, the video registers (for screenshots) and the Blitter.  Timer A/B (border
removal) and the keyboard are not simulated (build with -DSIM to skip their wait loops).

    python sim.py [frames] [--shot out.png]
"""
import os
import re
import sys
from pathlib import Path

import numpy as np
from machine68k import CPUType, Machine, Register as R

from paths import ROOT
RUN = ROOT / "run" / "dkong"          # default program; the other ports pass run_dir

LOAD = 0x10000
TRAP1 = 0x500
FRAME_CYCLES = 160000


class Blitter:
    """STE Blitter (see FAST_BLITTER_SPRITES.md, Atari blitter manual)."""

    def __init__(self, sim):
        self.sim = sim
        self.cycles = 0
        self.upper = 0
        self.lower = 0
        self.stats = {} if os.environ.get("BLIT_STATS") else None   # PC -> [passes, longest (bus cycles), its words]

    def reg16(self, off):
        io = self.sim.io
        return (io[off] << 8) | io[off + 1]

    def reg32(self, off):
        io = self.sim.io
        return (io[off] << 24) | (io[off + 1] << 16) | (io[off + 2] << 8) | io[off + 3]

    @staticmethod
    def s16(v):
        return v - 0x10000 if v & 0x8000 else v

    def run(self):
        io = self.sim.io
        mem = self.sim.mem
        ht = [self.reg16(0xA00 + 2 * i) for i in range(16)]
        sxi = self.s16(self.reg16(0xA20))
        syi = self.s16(self.reg16(0xA22))
        src = self.reg32(0xA24) & 0xFFFFFE
        em1, em2, em3 = self.reg16(0xA28), self.reg16(0xA2A), self.reg16(0xA2C)
        dxi = self.s16(self.reg16(0xA2E))
        dyi = self.s16(self.reg16(0xA30))
        dst = self.reg32(0xA32) & 0xFFFFFE
        xcount = self.reg16(0xA36) or 65536
        ycount = self.reg16(0xA38) or 65536
        hop = io[0xA3A] & 3
        op = io[0xA3B] & 15
        ctrl = io[0xA3C]
        ln = ctrl & 15
        smudge = bool(ctrl & 0x20)
        fxsr = bool(io[0xA3D] & 0x80)
        nfsr = bool(io[0xA3D] & 0x40)
        skew = io[0xA3D] & 15
        usesrc = hop >= 2
        if self.stats is not None and hasattr(self.sim, "cpu"):
            # a HOG pass holds the CPU (and its interrupts) for its bus cycles: a write, a destination read unless the
            # op ignores it, a source read
            per = 4 + (0 if op in (0, 3, 12, 15) else 4) + (4 if usesrc else 0)
            c = xcount * ycount * per + (4 * ycount if usesrc and fxsr else 0)
            # (a pass without HOG shares the bus: it runs on during the interrupts, under the border code's timing)
            pc = self.sim.cpu.r_pc()
            if os.environ.get("BLIT_CALLER"):        # (inside blit_go: its caller, above the saved d0-d2)
                pc = mem.r32((self.sim.cpu.r_reg(R.A7) + 12) & 0xFFFFFF)
            e = self.stats.setdefault((pc, bool(ctrl & 0x40)), [0, 0, 0])
            e[0] += 1
            if c > e[1]:
                e[1], e[2] = c, (xcount, ycount)
        r16 = mem.r16
        w16 = mem.w16
        for _ in range(ycount):
            if usesrc and fxsr:
                self.upper = self.lower
                self.lower = r16(src & 0xFFFFFF)
                src = (src + sxi) & 0xFFFFFF
                self.cycles += 4
            for x in range(xcount):
                if xcount == 1:
                    mask = em1
                elif x == 0:
                    mask = em1
                elif x == xcount - 1:
                    mask = em3
                else:
                    mask = em2
                if usesrc:
                    if not (x == xcount - 1 and nfsr):
                        # Each fetch shifts the source buffer, including the fetch after FXSR.
                        self.upper = self.lower
                        self.lower = r16(src & 0xFFFFFF)
                        src = (src + (sxi if x < xcount - 1 else syi)) & 0xFFFFFF
                        self.cycles += 4
                    s = (((self.upper << 16) | self.lower) >> skew) & 0xFFFF
                else:
                    s = 0
                h = ht[ln]
                if hop == 0:
                    w = 0xFFFF
                elif hop == 1:
                    w = h
                elif hop == 2:
                    w = s
                else:
                    w = s & h
                d = r16(dst & 0xFFFFFF)
                if op == 0: r = 0
                elif op == 1: r = w & d
                elif op == 2: r = w & ~d
                elif op == 3: r = w
                elif op == 4: r = ~w & d
                elif op == 5: r = d
                elif op == 6: r = w ^ d
                elif op == 7: r = w | d
                elif op == 8: r = ~w & ~d
                elif op == 9: r = ~(w ^ d)
                elif op == 10: r = ~d
                elif op == 11: r = w | ~d
                elif op == 12: r = ~w
                elif op == 13: r = ~w | d
                elif op == 14: r = ~w | ~d
                else: r = 0xFFFF
                w16(dst & 0xFFFFFF, ((d & ~mask) | (r & mask)) & 0xFFFF)
                self.cycles += 4
                self.upper = self.lower
                if x == xcount - 1:
                    dst = (dst + dyi) & 0xFFFFFF
                else:
                    dst = (dst + dxi) & 0xFFFFFF
            ln = (ln + (1 if dyi >= 0 else -1)) & 15
        # write back the registers the blitter updates
        for off, v in ((0xA24, src), (0xA32, dst)):
            for i in range(4):
                io[off + i] = (v >> (24 - 8 * i)) & 0xFF
        io[0xA38] = 0
        io[0xA39] = 0
        io[0xA3C] = (ctrl & ~0x80 & ~0x0F) | ln


def blit_stats(sim, mapfile=None, limit=512):
    """BLIT_STATS=<limit>: the HOG passes longer than `limit` bus cycles (a scanline: 512), every shared-bus pass; by the
    PC after their start"""
    st = sim.blitter.stats
    if not st:
        return
    names = []
    if mapfile:
        names = sorted((v + sim.base, k) for k, v in sim.symbols(mapfile).items())

    def where(pc):
        best = None
        for a, k in names:
            if a > pc:
                break
            best = (a, k)
        return "%s+%X" % (best[1], pc - best[0]) if best else "%06X" % pc
    for hog in (True, False):
        sel = {pc: e for (pc, h), e in st.items() if h == hog}
        if not sel:
            print("Blitter: no %s passes" % ("HOG" if hog else "shared-bus"))
            continue
        long_ = [(e[1], pc, e) for pc, e in sel.items() if e[1] > limit or not hog]
        print("Blitter: %d %s passes from %d places, longest %d bus cycles; over %d: %d places" % (
            sum(e[0] for e in sel.values()), "HOG" if hog else "shared-bus", len(sel),
            max(e[1] for e in sel.values()), limit, sum(1 for c, pc, e in long_ if c > limit)))
        for c, pc, e in sorted(long_, reverse=True)[:12]:
            print("  %-28s %6d passes, longest %5d cycles (%d words x %d lines)" % (where(pc), e[0], c, *e[2]))


class Sim:
    def __init__(self, prg, ram_kib=4096, run_dir=RUN):
        self.run_dir = Path(run_dir)
        self.m = Machine(CPUType.M68000, ram_kib)
        self.io_ram = ram_kib >= 16384        # RAM up to $ffffff: the hardware registers are readable memory
        self.cpu, self.mem = self.m.cpu, self.m.mem
        self.io = bytearray(0x8000)           # $ff8000..$ffffff
        self.files = {}
        self.next_handle = 6
        self.blitter = Blitter(self)
        self.mapfile = None
        if self.blitter.stats is not None:
            import atexit
            atexit.register(lambda: blit_stats(self, self.mapfile, int(os.environ["BLIT_STATS"])))
        self.extra_cycles = 0
        self.terminated = False
        self.mem.set_invalid_func(lambda mode, width, addr: 0)
        self.mem.set_trace_func(self.on_access)
        self.mem.set_trace_mode(True)
        self.frames = 0
        self.log = []
        self.load_prg(prg)

    # ---- hardware ------------------------------------------------------
    def on_access(self, mode, width, addr, value):
        if mode != "W":
            return
        a = addr & 0xFFFFFF
        if a < 0xFF8000:
            return
        off = a - 0xFF8000
        nbytes = (1, 2, 4)[width]
        for i in range(nbytes):
            self.io[off + i] = (value >> (8 * (nbytes - 1 - i))) & 0xFF
        # blitter start: bit 7 of $ff8a3c
        if off <= 0xA3C < off + nbytes and self.io[0xA3C] & 0x80:
            self.blitter.run()
            if self.io_ram:
                # (code that adds to the destination address needs to read back what the Blitter advanced)
                self.mem.w_block(0xFF8A00, bytes(self.io[0xA00:0xA40]))

    # ---- loading -------------------------------------------------------
    def load_prg(self, path):
        data = Path(path).read_bytes()
        assert data[:2] == b"\x60\x1a", "not a TOS program"
        tsize = int.from_bytes(data[2:6], "big")
        dsize = int.from_bytes(data[6:10], "big")
        bsize = int.from_bytes(data[10:14], "big")
        ssize = int.from_bytes(data[14:18], "big")
        img = bytearray(data[28:28 + tsize + dsize])
        base = LOAD + 0x100
        rel_pos = 28 + tsize + dsize + ssize
        first = int.from_bytes(data[rel_pos:rel_pos + 4], "big")
        if first:
            pos = first
            p = rel_pos + 4
            done = False
            while not done:
                v = int.from_bytes(img[pos:pos + 4], "big") + base
                img[pos:pos + 4] = v.to_bytes(4, "big")
                while True:
                    b = data[p]
                    p += 1
                    if b == 0:
                        done = True
                        break
                    if b == 1:
                        pos += 254
                        continue
                    pos += b
                    break
        self.base = base
        self.text_size = tsize
        self.mem.w_block(base, bytes(img))
        self.mem.w_block(base + len(img), bytes(bsize))
        self.entry = base
        # vectors: trap #1 -> TRAP1 (a `bra.s *`), others to a halting stub
        self.mem.w16(TRAP1, 0x60FE)
        self.mem.w16(0x600, 0x60FE)
        for v in range(2, 256):
            self.mem.w32(v * 4, 0x600)
        self.mem.w32(0x84, TRAP1)
        self.mem.w32(0x70, 0x600)
        self.cpu.pulse_reset()
        self.cpu.w_reg(R.A7, 0x8000)
        self.cpu.w_sr(0x2700)
        self.cpu.w_pc(self.entry)

    def symbols(self, mapfile):
        self.mapfile = self.mapfile or mapfile
        syms = {}
        for line in Path(mapfile).read_text().splitlines():
            m = re.match(r"\s+0x([0-9a-f]{8})\s+(\S+?):", line)
            if m:
                syms[m.group(2)] = int(m.group(1), 16)
        return syms

    # ---- GEMDOS --------------------------------------------------------
    def cstr(self, addr):
        s = bytearray()
        while True:
            b = self.mem.r8(addr)
            if b == 0:
                return s.decode("latin1")
            s.append(b)
            addr += 1

    def gemdos(self):
        sp = self.cpu.r_reg(R.A7)
        args = sp + 6
        fn = self.mem.r16(args)
        d0 = 0
        if fn == 0x20:
            d0 = 0x2000
        elif fn in (0x09, 0x01):
            d0 = 0
        elif fn == 0x3D:
            name = self.cstr(self.mem.r32(args + 2))
            p = self.run_dir / name
            if p.exists():
                h = self.next_handle
                self.next_handle += 1
                self.files[h] = [p.read_bytes(), 0, None]
                d0 = h
            else:
                d0 = -33
        elif fn == 0x3F:
            h, count, buf = self.mem.r16(args + 2), self.mem.r32(args + 4), self.mem.r32(args + 8)
            data, pos, _ = self.files[h]
            chunk = data[pos:pos + count]
            self.files[h][1] += len(chunk)
            self.mem.w_block(buf, chunk)
            d0 = len(chunk)
        elif fn == 0x3C:
            name = self.cstr(self.mem.r32(args + 2))
            h = self.next_handle
            self.next_handle += 1
            self.files[h] = [b"", 0, name]
            d0 = h
        elif fn == 0x40:
            h, count, buf = self.mem.r16(args + 2), self.mem.r32(args + 4), self.mem.r32(args + 8)
            self.files[h][0] += bytes(self.mem.r_block(buf, count))
            d0 = count
        elif fn == 0x3E:
            h = self.mem.r16(args + 2)
            f = self.files.pop(h, None)
            if f and f[2]:
                (self.run_dir / f[2]).write_bytes(f[0])
            d0 = 0
        elif fn in (0x00, 0x4C):
            self.terminated = True
        else:
            self.log.append("unhandled GEMDOS %X" % fn)
        self.cpu.w_reg(R.D0, d0 & 0xFFFFFFFF)
        # rte
        sr = self.mem.r16(sp)
        pc = self.mem.r32(sp + 2)
        self.cpu.w_reg(R.A7, sp + 6)
        self.cpu.w_sr(sr)
        self.cpu.w_pc(pc)

    # ---- running -------------------------------------------------------
    def irq(self, level, vector):
        sr = self.cpu.r_sr()
        if ((sr >> 8) & 7) >= level:
            return False
        sp = self.cpu.r_reg(R.A7)
        if not sr & 0x2000:
            self.cpu.w_reg(R.USP, sp)
            sp = self.cpu.r_reg(R.ISP)
        sp -= 6
        self.mem.w32(sp + 2, self.cpu.r_pc())
        self.mem.w16(sp, sr)
        self.cpu.w_sr(0x2000 | (level << 8))
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.mem.r32(vector * 4))
        return True

    def run_frames(self, n, on_frame=None, chunk=2000):
        end = self.frames + n
        next_vbl = getattr(self, "_next_vbl", FRAME_CYCLES)
        total = getattr(self, "_total", 0)
        while self.frames < end and not self.terminated:
            r = self.cpu.execute(chunk)
            total += r.cycles
            if self.blitter.cycles:
                total += self.blitter.cycles
                self.blitter.cycles = 0
            pc = self.cpu.r_pc()
            if pc == TRAP1:
                self.gemdos()
            elif pc == 0x600:
                self.log.append("exception/halt at %X" % pc)
                break
            if total >= next_vbl:
                if self.irq(4, 28):
                    next_vbl += FRAME_CYCLES
                    self.frames += 1
                    self.lag = total - (next_vbl - FRAME_CYCLES)
                    if on_frame:
                        on_frame(self)
        self._next_vbl = next_vbl
        self._total = total

    # ---- screen ----------------------------------------------------------
    def palette(self):
        out = []
        for i in range(16):
            w = (self.io[0x240 + 2 * i] << 8) | self.io[0x241 + 2 * i]
            f = lambda n: (((n & 7) << 1) | (n >> 3)) * 17
            out.append((f((w >> 8) & 15), f((w >> 4) & 15), f(w & 15)))
        return out

    def screen_rgb(self, lines=256, width=320):
        io = self.io
        base = (io[0x201] << 16) | (io[0x203] << 8) | io[0x20D]
        stride = 160 + 2 * io[0x20F]
        pal = self.palette()
        data = np.frombuffer(bytes(self.mem.r_block(base, stride * lines)), np.uint8).reshape(lines, stride)
        words = data[:, :width // 16 * 8].reshape(lines, width // 16, 4, 2)
        bits = np.zeros((lines, width), np.uint8)
        for p in range(4):
            w = (words[:, :, p, 0].astype(np.uint16) << 8) | words[:, :, p, 1]
            for b in range(16):
                bits[:, b::16] |= (((w >> (15 - b)) & 1).astype(np.uint8) << p)
        pal_arr = np.array(pal, np.uint8)
        return pal_arr[bits]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=30)
    ap.add_argument("--prg", default=str(RUN / "DKONG.PRG"))
    ap.add_argument("--shot", default=None)
    a = ap.parse_args()
    s = Sim(a.prg)
    s.run_frames(a.frames)
    print("frames", s.frames, "pc", hex(s.cpu.r_pc()), "terminated", s.terminated, s.log[-3:])
    if a.shot:
        from PIL import Image
        Image.fromarray(s.screen_rgb()).save(a.shot)


if __name__ == "__main__":
    main()
