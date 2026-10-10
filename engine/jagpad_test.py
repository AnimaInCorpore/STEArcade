"""engine/rt/jagpad.s against Hatari's model of the STE pads (src/joy.c: Joy_StePadButtons / Joy_StePadMulti).

Assembles jagpad_poll with a map that gives every pad button its own bit, presses each button of pad A and pad B
alone (then * and # together) and checks jp_in and quit_flag.

    python engine/jagpad_test.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from machine68k import CPUType, Machine, Register as R

from paths import VASM, RT_INCLUDE

ORG = 0x1000
VARS = 0x3000
SOURCE = """
JP1_UP = 1<<0
JP1_DOWN = 1<<1
JP1_LEFT = 1<<2
JP1_RIGHT = 1<<3
JP1_B1 = 1<<4
JP1_B2 = 1<<5
JP1_B3 = 1<<6
JP2_UP = 1<<7
JP2_DOWN = 1<<8
JP2_LEFT = 1<<9
JP2_RIGHT = 1<<10
JP2_B1 = 1<<11
JP2_B2 = 1<<12
JP2_B3 = 1<<13
JP_START1 = 1<<14
JP_START2 = 1<<15
JP_COIN1 = 1<<16
JP_COIN2 = 1<<17
	include	"jagpad.s"
	org	$%x
	bra.w	start
done:	bra.s	done			; (ORG+4)
start:	bsr	jagpad_init
	bsr	jagpad_poll
	bra	done
	jagpad_text
	jagpad_maps
	org	$%x
	jagpad_vars			; jp_in at VARS
quit_flag:	ds.b	1		; (VARS+6)
	even
""" % (ORG, VARS)

# Hatari's button numbers (Joy_GetFireButtons): A, B, C, Option, Pause, #, 9, 6, 3, 0, 8, 5, 2, *, 7, 4, 1
HB = {n: i for i, n in enumerate(["A", "B", "C", "Option", "Pause", "#", "9", "6", "3", "0", "8", "5", "2", "*",
                                  "7", "4", "1"])}
STICK = {"up": 1, "down": 2, "left": 4, "right": 8}


def hatari_ff9200(sel, pads):
    data = 0xFF
    for p, (mask, fire_bit, pause_bit) in enumerate(((0x0F, 2, 1), (0xF0, 8, 4))):
        stick, buttons = pads[p]
        s = (sel & mask) >> (4 * p)
        if s == 0xF:
            continue
        for row, name in enumerate(("A", "B", "C", "Option")):
            if not s & (1 << row):
                if buttons & (1 << HB[name]):
                    data &= ~fire_bit
                if row == 0 and buttons & (1 << HB["Pause"]):
                    data &= ~pause_bit
                break
    return 0xFF00 | data


def hatari_ff9202(sel, pads):
    data = 0xFF
    for p, mask in enumerate((0x0F, 0xF0)):
        stick, buttons = pads[p]
        s = (sel & mask) >> (4 * p)
        if s == 0xF:
            continue
        for row, shift in enumerate((None, 13, 9, 5)):
            if not s & (1 << row):
                nib = stick if shift is None else (buttons >> shift)
                data = (data & ~(0xF << 4 * p)) | ((~nib & 0xF) << 4 * p)
                break
    return (data << 8) | 0xFF


def run(pads):
    """pads: [(stick bits, Hatari button bits)] for pad A and B -> (jp_in, quit_flag)"""
    m = Machine(CPUType.M68000, 1024)
    cpu, mem = m.cpu, m.mem
    state = {"sel": 0xFFFF}

    def write(addr, value):
        if addr & 0xFFFFFF == 0xFF9202:
            state["sel"] = value & 0xFFFF

    def read(addr):
        a = addr & 0xFFFFFF
        if a == 0xFF9200:
            return hatari_ff9200(state["sel"], pads)
        if a == 0xFF9202:
            return hatari_ff9202(state["sel"], pads)
        return 0

    mem.set_special_range_read_func(0xFF0000, 1, read)       # (word accesses: the pads' registers are word wide)
    mem.set_special_range_write_func(0xFF0000, 1, write)
    mem.w_block(ORG, BIN)
    cpu.pulse_reset()
    cpu.w_reg(R.A7, 0x8000)
    cpu.w_sr(0x2700)
    cpu.w_pc(ORG)
    for _ in range(50):
        cpu.execute(1000)
        if cpu.r_pc() == ORG + 4:
            break
    else:
        sys.exit("jagpad_test: did not finish (pc %x)" % cpu.r_pc())
    return mem.r32(VARS), mem.r8(VARS + 6)


def main():
    global BIN
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "t.s", Path(tmp) / "t.bin"
        src.write_text(SOURCE)
        r = subprocess.run([VASM, "-Fbin", "-quiet", "-I", str(RT_INCLUDE), "-o", str(out), str(src)],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        BIN = out.read_bytes()

    # (pad button, expected map bit for pad A, for pad B)
    cases = [("up", 0, 7), ("down", 1, 8), ("left", 2, 9), ("right", 3, 10), ("A", 4, 11), ("B", 5, 12),
             ("C", 6, 13), ("Option", 16, 17), ("Pause", 14, 15), ("1", 14, 14), ("2", 15, 15), ("5", 16, 16),
             ("6", 17, 17)]
    fails = 0
    none = run([(0, 0), (0, 0)])
    if none != (0, 0):
        print("idle:", none)
        fails += 1
    for name, bit_a, bit_b in cases:
        press = (STICK[name], 0) if name in STICK else (0, 1 << HB[name])
        for pad, bit in ((0, bit_a), (1, bit_b)):
            pads = [(0, 0), (0, 0)]
            pads[pad] = press
            got = run(pads)
            if got != (1 << bit, 0):
                print("pad %s %s: jp_in %05x quit %d, expected %05x" % ("AB"[pad], name, got[0], got[1], 1 << bit))
                fails += 1
    for name in ("3", "4", "7", "8", "9", "0", "*", "#"):     # not mapped
        got = run([(0, 1 << HB[name]), (0, 0)])
        if got != (0, 0):
            print("pad A %s: jp_in %05x quit %d, expected nothing" % (name, *got))
            fails += 1
    for pad in (0, 1):
        pads = [(0, 0), (0, 0)]
        pads[pad] = (0, (1 << HB["*"]) | (1 << HB["#"]))
        got = run(pads)
        if got[1] != 0xFF:
            print("pad %s * and #: no quit" % "AB"[pad])
            fails += 1
    got = run([(STICK["left"] | STICK["up"], 1 << HB["B"]), (STICK["right"], 1 << HB["A"])])
    if got != ((1 << 2) | (1 << 0) | (1 << 5) | (1 << 10) | (1 << 11), 0):
        print("both pads: jp_in %05x" % got[0])
        fails += 1
    print("jagpad_test:", "FAIL (%d)" % fails if fails else "ok (%d buttons on both pads)" % len(cases))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
