"""The translated MCU (build/bb_mcu.s on Musashi) against the 6801 reference, frame by frame.

The game runs in the port's schedule with the reference MCU; before every MCU interrupt the state
the MCU sees (its registers and RAM, the shared RAM, the inputs, the glue's port latches) is
saved, the reference handler runs, then the translated handler runs from the saved state and
both results are compared (RAM, registers, shared RAM, the main CPU's interrupt request).  The
boot (the init) is compared the same way.  The I/O hooks are Python (the reference glue).

    python mcu_test.py [frames]
"""
import os, re, subprocess, sys
from pathlib import Path
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import m6801x
from machine import Bublbobl
from machine68k import CPUType, Machine, Register as R

from paths import VASM, VLINK, build_dir
BUILD = build_dir("bublbobl")
CODE = 0x10000
MM = 0x40000            # the MCU's memory block (64 KB)
STACK = 0x0F000
HOOKS = ("mcu_rd_p1", "mcu_rd_p3", "mcu_wr_p1", "mcu_wr_p2", "mcu_restart", "mcu_done")


def build():
    text, em, code = m6801x.generate()
    (BUILD / "bb_mcu.s").write_text(text)
    (BUILD / "bb_mcu_test.s").write_text("""
mcu_mem = $%X
	section text
%s
mcu_done:	bra.s	mcu_done
	include "bb_mcu.s"
""" % (MM, "\n".join("%s:\tbra.s\t%s" % (h, h) for h in HOOKS if h != "mcu_done")))
    r = subprocess.run([str(VASM), "-Fvobj", "-quiet", "-nowarn=2047", "-o", "bb_mcu_test.o", "bb_mcu_test.s"],
                       cwd=BUILD, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    r = subprocess.run([str(VLINK), "-brawbin1", "-Ttext", hex(CODE), "-Mbb_mcu_test.map", "-o", "bb_mcu_test.bin",
                        "bb_mcu_test.o"], cwd=BUILD, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    syms = {}
    for line in (BUILD / "bb_mcu_test.map").read_text().splitlines():
        m = re.match(r"\s+0x([0-9a-f]{8})\s+(\S+?):", line)
        if m:
            syms[m.group(2)] = int(m.group(1), 16)
    return (BUILD / "bb_mcu_test.bin").read_bytes(), syms


class Test:
    def __init__(self):
        self.binary, self.sym = build()
        self.m = Machine(CPUType.M68000, 2048)
        self.cpu, self.mem = self.m.cpu, self.m.mem
        self.mem.w_block(CODE, self.binary)
        self.stops = {self.sym[h]: h for h in HOOKS}
        self.g = Bublbobl()
        self.g.port_mode = True
        self.events = []
        self.mismatch = 0
        self.checked = 0

    # ---- the reference side: state save / restore -----------------------
    def save(self):
        g, mcu = self.g, self.g.mcu
        return {"ram": bytes(mcu.ram), "reg": bytes(mcu.reg), "ddr": list(mcu.ddr), "data": list(mcu.data),
                "mcram": bytes(g.mcram), "in": (g.in0, g.in1, g.in2, g.dsw0, g.dsw1),
                "glue": (g.p1_out, g.p2_out, g.p3_out, g.p4_out, g.p3_in, g.irq_main),
                "regs": (mcu.a, mcu.b, mcu.x, mcu.sp, mcu.cc)}

    def restore(self, s):
        g, mcu = self.g, self.g.mcu
        mcu.ram[:] = s["ram"]
        mcu.reg[:] = s["reg"]
        mcu.ddr[:] = s["ddr"]
        mcu.data[:] = s["data"]
        g.mcram[:] = s["mcram"]
        g.p1_out, g.p2_out, g.p3_out, g.p4_out, g.p3_in, g.irq_main = s["glue"]

    # ---- the translated side ---------------------------------------------
    def load_mm(self, s):
        mem = self.mem
        mem.w_block(MM, bytes(0x10000))
        mem.w_block(MM + 0xF000, bytes(self.g.mcu_rom))
        mem.w_block(MM, s["reg"])
        mem.w_block(MM + 0x40, s["ram"][0x40:0x100])
        for i, v in enumerate(s["reg"]):
            pass
        # the data / ddr latches live in the register bytes ($00,$01,$04,$05 DDR, $02,$03,$06,$07 data)
        for a, v in ((0, s["ddr"][0]), (1, s["ddr"][1]), (4, s["ddr"][2]), (5, s["ddr"][3]),
                     (2, s["data"][0]), (3, s["data"][1]), (6, s["data"][2]), (7, s["data"][3])):
            mem.w8(MM + a, v)

    def hook(self, name, g):
        mem, cpu = self.mem, self.cpu
        w = cpu.w_reg
        mm = lambda a: mem.r8(MM + a)
        if name == "mcu_rd_p1":
            ddr = mm(0)
            w(R.D7, (cpu.r_reg(R.D7) & ~0xFF) | ((mm(2) & ddr) | (g.in0 & ~ddr & 0xFF)))
        elif name == "mcu_rd_p3":
            ddr = mm(4)
            w(R.D7, (cpu.r_reg(R.D7) & ~0xFF) | ((mm(6) & ddr) | (g.p3_in & ~ddr & 0xFF)))
        elif name in ("mcu_wr_p1", "mcu_wr_p2"):
            p = 0 if name == "mcu_wr_p1" else 1
            ddr = mm(0 if p == 0 else 1)
            d = mm(2 if p == 0 else 3)
            v = d if ddr == 0xFF else ((d & ddr) | (ddr ^ 0xFF))
            if p == 1:                       # the glue sees P3 (data) and P4 (low address) as they are now
                for port, reg, dreg in ((2, 6, 4), (3, 7, 5)):
                    d, dd = mm(reg), mm(dreg)
                    ov = d if dd == 0xFF else ((d & dd) | (dd ^ 0xFF))
                    if port == 2: g.p3_out = ov
                    else: g.p4_out = ov
            (g.mcu_p1_w if p == 0 else g.mcu_p2_w)(v)
            self.events.append((name, v))
        else:
            raise RuntimeError("hook " + name)
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))                      # rts
        w(R.A7, sp + 4)

    def run68(self, entry, g):
        cpu, mem = self.cpu, self.mem
        w = cpu.w_reg
        for r in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6, R.D7, R.A0, R.A1, R.A2, R.A3, R.A4):
            w(r, 0)
        w(R.A5, MM + 0x100)
        w(R.A6, MM)
        w(R.A7, STACK - 4)
        w(R.ISP, STACK - 4)
        mem.w32(STACK - 4, self.sym["mcu_done"])
        cpu.w_sr(0x2700)
        cpu.w_pc(entry)
        n = 0
        while True:
            cpu.execute(2000)
            pc = cpu.r_pc()
            if pc in self.stops:
                name = self.stops[pc]
                if name == "mcu_done":
                    return
                self.hook(name, g)
            n += 1
            if n > 5000:
                raise RuntimeError("translated MCU does not return (pc %06X)" % pc)

    def compare(self, what, ref_after, frame):
        g, mem = self.g, self.mem
        errs = []
        ram68 = bytes(mem.r8(MM + a) for a in range(0x40, 0x100))
        # the stack area (below the pointer) is not compared, nor is anything but the RAM the program owns
        refram = ref_after["ram"][0x40:0x100]
        diff = [a + 0x40 for a in range(0xB0) if ram68[a] != refram[a]]     # (the stack below $F0 is not compared)
        if diff:
            errs.append("RAM differs at %s" % ["%02X" % d for d in diff[:12]])
        if bytes(g.mcram) != ref_after["mcram"]:
            d = [i for i in range(0x400) if g.mcram[i] != ref_after["mcram"][i]]
            errs.append("shared RAM differs at %s" % ["%03X" % i for i in d[:12]])
        if self.events != ref_after["events"]:
            errs.append("events %s vs %s" % (self.events[:6], ref_after["events"][:6]))
        if errs:
            self.mismatch += 1
            if self.mismatch <= 6:
                print("frame %d %s: %s" % (frame, what, "; ".join(errs)))
        self.checked += 1

    # ---- driving -------------------------------------------------------
    def frame(self, f):
        g = self.g
        mcu = g.mcu
        before = self.save()
        ref_events = []
        o1, o2 = g.mcu_p1_w, g.mcu_p2_w
        mcu.out[0] = lambda v: (ref_events.append(("mcu_wr_p1", v)), o1(v))[1]
        mcu.out[1] = lambda v: (ref_events.append(("mcu_wr_p2", v)), o2(v))[1]
        return before, ref_events, (o1, o2)

    def check(self, f, what, entry, before, ref_events):
        """called after the reference ran: run the translation from `before`, compare, restore"""
        g = self.g
        after = self.save()
        after["events"] = ref_events
        # run the translation
        self.restore(before)
        self.load_mm(before)
        self.events = []
        self.run68(self.sym[entry], g)
        self.compare(what, after, f)
        self.restore(after)


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    t = Test()
    g = t.g
    mcu = g.mcu
    orig_boot = g.run_to_idle_mcu
    orig_irq = g.run_mcu_irq
    state = {"f": 0}

    def boot():
        # the init: the reference runs from the reset vector, the translation from $F003
        before = t.save()
        ev = []
        o1, o2 = g.mcu_p1_w, g.mcu_p2_w
        mcu.out[0] = lambda v: (ev.append(("mcu_wr_p1", v)), o1(v))[1]
        mcu.out[1] = lambda v: (ev.append(("mcu_wr_p2", v)), o2(v))[1]
        orig_boot()
        mcu.out[0], mcu.out[1] = o1, o2
        after = t.save()
        after["events"] = ev
        t.restore(before)
        t.load_mm(before)
        t.events = []
        t.run68(t.sym["MF003"], g)
        t.compare("boot", after, state["f"])
        t.restore(after)

    def irq():
        before = t.save()
        ev = []
        o1, o2 = g.mcu_p1_w, g.mcu_p2_w
        mcu.out[0] = lambda v: (ev.append(("mcu_wr_p1", v)), o1(v))[1]
        mcu.out[1] = lambda v: (ev.append(("mcu_wr_p2", v)), o2(v))[1]
        r = orig_irq()
        mcu.out[0], mcu.out[1] = o1, o2
        after = t.save()
        after["events"] = ev
        t.restore(before)
        t.load_mm(before)
        t.events = []
        t.run68(t.sym["MF046"], g)
        t.compare("irq", after, state["f"])
        t.restore(after)
        return r
    g.run_to_idle_mcu = boot
    g.run_mcu_irq = irq
    for f in range(frames):
        state["f"] = f
        g.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
        g.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
        if f > 900:
            g.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
            if f % 30 < 3:
                g.in1 &= ~0x20
        g.run_frame_port()
    print("%d MCU runs compared, %d mismatches" % (t.checked, t.mismatch))


if __name__ == "__main__":
    main()
