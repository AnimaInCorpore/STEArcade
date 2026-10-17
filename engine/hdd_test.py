"""engine/rt/hdd.s's hdd_read / hdd_poll against register models of the DMA chip with an ACSI target and of an
IDE drive (tools/hddtest.sh runs the whole module, hdd_open too, on Hatari's emulated disks).

The extents are set directly (as hdd_open leaves them); physical sector p of the model disk holds the longs
p << 8 | j.  Checked: the data of requests across extents and longer than HDD_STEP, the ACSI command bytes
(target, block address, count), IDE in LBA and CHS addressing (master and slave), a second hdd_read while busy, a
request beyond the file, and the errors: no ACSI target, an ACSI error status, IDE ERR, an IDE drive that stays busy
(the timeout, counted by hdd_vbl's ticks).

    python engine/hdd_test.py
"""
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from machine68k import CPUType, Machine, Register as R

from paths import VASM, RT_INCLUDE

ORG = 0x1000
VARS = 0x8000
BUF = 0x20000
SOURCE = """
	include	"hdd.s"
	org	$%x
	bra.w	start
done:	bra.s	done			; (ORG+4)
start:	movem.l	d0-d1/a0,-(sp)
	bsr	hdd_read
	move.l	d0,result
	movem.l	(sp)+,d0-d1/a0
	tst.l	result
	bne.s	.out
	bsr	hdd_read		; (busy: refused)
	move.l	d0,result2
.poll:	bsr	hdd_poll
	cmp.l	#HDD_BUSY,d0
	beq.s	.poll
	move.l	d0,result
.out:	bra	done
	hdd_text
	org	$%x
	hdd_vars
result:		ds.l	1
result2:	ds.l	1
""" % (ORG, VARS)

HDD_E_RANGE, HDD_E_TIMEOUT, HDD_E_STATUS, HDD_E_BUSY = -6, -8, -9, -10


def sector(p):
    return b"".join(struct.pack(">I", (p << 8 | j) & 0xFFFFFFFF) for j in range(128))


class Acsi:
    """The DMA chip ($FF8604 / $FF8606 / address $FF8609-$FF860D) and one ACSI target; GPIP bit 5 = its interrupt."""

    def __init__(self, mem, target, present=True, status=0, delay=3):
        self.mem, self.target, self.present, self.status, self.delay = mem, target, present, status, delay
        self.mode = 0x80
        self.addr = 0
        self.count = 0
        self.cmd = []
        self.commands = []
        self.irq = False
        self.pending = 0           # GPIP reads until the data phase's interrupt

    def w16(self, a, v):
        if a == 0xFF8606:
            self.mode = v
            if v == 0 and len(self.cmd) == 6:          # the DMA started
                self.start()
        elif a == 0xFF8604:
            self.irq = False
            if self.mode & 0x10:
                self.count = v & 0xFF
            elif self.mode & 0x08 and self.mode & 0x80:
                if not self.mode & 2:                   # A1 low: a command's first byte
                    self.cmd = []
                self.cmd.append(v & 0xFF)
                if self.present and (self.cmd[0] >> 5) == self.target and len(self.cmd) < 6:
                    self.irq = True

    def w32(self, a, v):
        self.w16(a, v >> 16)
        self.w16(a + 2, v & 0xFFFF)

    def w8(self, a, v):
        shift = {0xFF8609: 16, 0xFF860B: 8, 0xFF860D: 0}.get(a)
        if shift is not None:
            self.addr = (self.addr & ~(0xFF << shift)) | (v << shift)

    def start(self):
        c = self.cmd
        self.commands.append(tuple(c))
        if not self.present or (c[0] >> 5) != self.target:
            return
        lba = (c[1] & 0x1F) << 16 | c[2] << 8 | c[3]
        n = c[4] or 256
        assert c[0] & 0x1F == 0x08 and n == self.count, (c, self.count)
        for i in range(n):
            self.mem.w_block(self.addr + 512 * i, sector(lba + i))
        self.pending = self.delay

    def r16(self, a):
        if a == 0xFF8604:
            return self.status if self.mode & 0x08 else 0
        if a == 0xFF8606:
            return 1                                   # no DMA error
        return 0

    def gpip(self):
        if self.pending:
            self.pending -= 1
            if not self.pending:
                self.irq = True
        return 0xDF if self.irq else 0xFF


class Ide:
    """An IDE drive pair at $F00000 (Falcon register layout); one drive present, as unit `unit`."""

    def __init__(self, unit, heads=16, spt=63, error=False, stuck=False, delay=2):
        self.unit, self.heads, self.spt, self.error, self.stuck, self.delay = unit, heads, spt, error, stuck, delay
        self.reg = {}
        self.data = b""
        self.left = 0
        self.lba = 0
        self.busy = 0
        self.commands = []

    def w8(self, a, v):
        r = a & 0xFF
        self.reg[r] = v
        if r == 0x1D:
            head = self.reg[0x19]
            assert (head >> 4) & 1 == self.unit, "drive select"
            if head & 0x40:
                lba = (head & 0x0F) << 24 | self.reg[0x15] << 16 | self.reg[0x11] << 8 | self.reg[0x0D]
            else:
                assert head & 0xA0 == 0xA0, "CHS: bits 7 and 5 set"
                cyl = self.reg[0x15] << 8 | self.reg[0x11]
                lba = (cyl * self.heads + (head & 0x0F)) * self.spt + self.reg[0x0D] - 1
                assert 1 <= self.reg[0x0D] <= self.spt and head & 0x0F < self.heads
            n = self.reg[0x09] or 256
            self.commands.append((v, lba, n, bool(head & 0x40)))
            assert v == 0x20
            self.lba, self.left, self.busy = lba, n, self.delay

    def status(self):
        if self.stuck:
            return 0x80
        if self.error and self.left:
            return 0x51
        if self.busy:
            self.busy -= 1
            return 0x80
        if self.left and not self.data:
            self.data = sector(self.lba)
        return 0x58 if self.data else 0x50

    def r8(self, a):
        return self.status() if a & 0xFF in (0x1D, 0x39) else 0

    def r32(self, a):
        assert self.data, "data read without DRQ"
        v, self.data = self.data[:4], self.data[4:]
        if not self.data:
            self.left -= 1
            self.lba += 1
            self.busy = self.delay if self.left else 0
        return struct.unpack(">I", v)[0]


def run(syms, kind, extents, first, count, make, unit, lba=0, heads=16, spt=63):
    """make(mem) -> the device model.  -> (hdd_read / hdd_poll result, the second hdd_read's, the buffer, flock,
    hdd_state, the device)"""
    m = Machine(CPUType.M68000, 1024)
    cpu, mem = m.cpu, m.mem
    device = make(mem)
    acsi = isinstance(device, Acsi)
    mem.w_block(ORG, BIN)
    mem.w_block(BUF, b"\xEE" * (count * 512 if 0 < count <= 0x200 else 512))

    def r8(a):
        a &= 0xFFFFFF
        if a == 0xFFFA01:
            return device.gpip() if acsi else 0xFF
        return device.r8(a) if not acsi and a >> 16 == 0xF0 else 0

    def r16(a):
        return device.r16(a & 0xFFFFFF) if acsi else 0

    def r32(a):
        return device.r32(a & 0xFFFFFF) if not acsi else 0

    def w8(a, v):
        device.w8(a & 0xFFFFFF, v)

    def w16(a, v):
        if acsi:
            device.w16(a & 0xFFFFFF, v)

    def w32(a, v):
        if acsi:
            device.w32(a & 0xFFFFFF, v)

    for page in (0xF00000, 0xFF0000):
        mem.set_special_range_read_funcs(page, 1, r8, r16, r32)
        mem.set_special_range_write_funcs(page, 1, w8, w16, w32)

    mem.w8(syms["hdd_kind"], kind)
    mem.w8(syms["hdd_unit"], unit)
    mem.w8(syms["hdd_lba"], lba)
    mem.w16(syms["hdd_heads"], heads)
    mem.w16(syms["hdd_spt"], spt)
    mem.w32(syms["hdd_sectors"], sum(e[2] for e in extents))
    mem.w16(syms["hdd_extent_count"], len(extents))
    for i, e in enumerate(extents):
        for k, v in enumerate(e):
            mem.w32(syms["hdd_extents"] + 12 * i + 4 * k, v)
    cpu.pulse_reset()
    cpu.w_reg(R.A7, 0x10000)
    cpu.w_reg(R.D0, first)
    cpu.w_reg(R.D1, count)
    cpu.w_reg(R.A0, BUF)
    cpu.w_sr(0x2700)
    cpu.w_pc(ORG)
    for _ in range(2000):
        cpu.execute(160000)                             # a VBL: hdd_vbl
        if cpu.r_pc() == ORG + 4:
            break
        t = mem.r16(syms["hdd_ticks"])
        if t:
            mem.w16(syms["hdd_ticks"], t - 1)
    else:
        sys.exit("hdd_test: did not finish (pc %x)" % cpu.r_pc())
    data = mem.r_block(BUF, count * 512) if 0 < count <= 0x200 else b""
    return (mem.r32s(syms["result"]), mem.r32s(syms["result2"]), data, mem.r16(0x43E), mem.r8(syms["hdd_state"]),
            device)


def expected(extents, first, count):
    out = []
    for f in range(first, first + count):
        for start, phys, n in extents:
            if start <= f < start + n:
                out.append(sector(phys + f - start))
    return b"".join(out)


def pieces(extents, first, count):
    """(physical sector, sectors) of the commands hdd.s should send (HDD_STEP 128)"""
    out = []
    while count:
        for s, p, n in extents:
            if s <= first < s + n:
                step = min(count, s + n - first, 128)
                out.append((p + first - s, step))
                first, count = first + step, count - step
                break
    return out


def main():
    global BIN
    with tempfile.TemporaryDirectory() as tmp:
        src, out, lst = Path(tmp) / "t.s", Path(tmp) / "t.bin", Path(tmp) / "t.lst"
        src.write_text(SOURCE)
        r = subprocess.run([VASM, "-Fbin", "-quiet", "-nowarn=2047", "-I", str(RT_INCLUDE), "-L", str(lst),
                            "-o", str(out), str(src)], capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        BIN = out.read_bytes()
        syms = {m.group(1): int(m.group(2), 16)
                for m in re.finditer(r"^(\w+)\s+[AE]:([0-9A-F]+)$", lst.read_text(), re.M)}

    fails = []

    def check(name, got, result=0, data=None, commands=None):
        res, res2, buf, flock, state, dev = got
        bad = []
        if res != result:
            bad.append("result %d, expected %d" % (res, result))
        if result == 0 and res2 != HDD_E_BUSY:
            bad.append("second hdd_read %d, expected %d (busy)" % (res2, HDD_E_BUSY))
        if data is not None and buf != data:
            bad.append("data differs from sector %d" % next(i // 512 for i in range(len(buf)) if buf[i] != data[i]))
        if commands is not None and dev.commands != commands:
            bad.append("commands %s, expected %s" % (dev.commands, commands))
        if flock:
            bad.append("flock left set")
        if state:
            bad.append("hdd_state %d left" % state)
        if isinstance(dev, Acsi) and dev.mode != 0x80:
            bad.append("DMA mode $%x left (not the FDC's $80)" % dev.mode)
        print("  %-42s %s" % (name, "; ".join(bad) or "ok"))
        if bad:
            fails.append(name)

    ext = [(0, 1000, 100), (100, 5000, 300), (400, 20, 50)]   # three pieces, the second longer than HDD_STEP
    for first, count in ((0, 1), (90, 50), (99, 2), (0, 450), (300, 150)):
        cmds = [(3 << 5 | 8, p >> 16 & 0x1F, p >> 8 & 0xFF, p & 0xFF, n, 0) for p, n in pieces(ext, first, count)]
        check("ACSI target 3, sectors %d+%d" % (first, count),
              run(syms, 1, ext, first, count, lambda mem: Acsi(mem, 3), unit=3),
              data=expected(ext, first, count), commands=cmds)

    for unit, lba in ((0, 0xFF), (1, 0xFF), (0, 0), (1, 0)):
        cmds = [(0x20, p, n, bool(lba)) for p, n in pieces(ext, 95, 320)]
        check("IDE unit %d %s, sectors 95+320" % (unit, "LBA" if lba else "CHS 16/63"),
              run(syms, 2, ext, 95, 320, lambda mem: Ide(unit), unit=unit, lba=lba),
              data=expected(ext, 95, 320), commands=cmds)

    check("beyond the file", run(syms, 1, ext, 440, 11, lambda mem: Acsi(mem, 0), unit=0), result=HDD_E_RANGE)
    check("ACSI: no target", run(syms, 1, ext, 0, 4, lambda mem: Acsi(mem, 2, present=False), unit=2),
          result=HDD_E_TIMEOUT)
    check("ACSI: error status", run(syms, 1, ext, 0, 4, lambda mem: Acsi(mem, 0, status=2), unit=0),
          result=HDD_E_STATUS)
    check("IDE: ERR", run(syms, 2, ext, 0, 4, lambda mem: Ide(0, error=True), unit=0, lba=0xFF),
          result=HDD_E_STATUS)
    check("IDE: busy for good (the VBL timeout)",
          run(syms, 2, ext, 0, 4, lambda mem: Ide(0, stuck=True), unit=0, lba=0xFF), result=HDD_E_TIMEOUT)

    print("hdd_test:", "FAIL (%s)" % ", ".join(fails) if fails else "ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
