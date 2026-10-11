"""engine/rt/ikbd.s against byte streams of the IKBD, with overruns as Hatari's acia.c models them.

Assembles a handler loop around ikbd_byte that logs every key byte and joystick packet, feeds it a stream (the ACIA:
$FFFC00 bit 0 while bytes are left; a lost byte sets OVRN after the byte before it is read, as on the MC6850) and
checks the log and quit_flag.

    python engine/ikbd_test.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from machine68k import CPUType, Machine, Register as R

from paths import VASM, RT_INCLUDE

ORG = 0x1000
VARS = 0x3000
LOG = 0x4000
SOURCE = """
KEY_ESC = $01
	include	"ikbd.s"
	org	$%x
	bra.w	start
done:	bra.s	done			; (ORG+4)
start:	lea	$%x,a1			; the log
.again:
	ikbd_byte
.not_esc:
	move.b	d2,(a1)+		; a key: its byte
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	move.b	#$ee,(a1)+		; a joystick packet: $EE, 1 / 2, data
	move.b	d0,(a1)+
	move.b	d1,(a1)+
	bra	.again
.done:
	move.l	a1,$%x
	bra	done
	org	$%x
quit_flag:	ds.b	1		; (VARS)
	ikbd_vars
	even
""" % (ORG, LOG, VARS + 8, VARS)

LOST = object()


def run(stream):
    """stream: bytes, a LOST before a byte loses it -> (log bytes, quit_flag)"""
    queue = []                  # [byte, overrun after it]
    lose = False
    for b in stream:
        if b is LOST:
            lose = True
        elif lose:
            lose = False
            assert queue, "a lost byte needs one before it"
            queue[-1][1] = True
        else:
            queue.append([b, False])
    m = Machine(CPUType.M68000, 1024)
    cpu, mem = m.cpu, m.mem
    state = {"sr_ovrn": False}

    def read(addr):
        a = addr & 0xFFFFFF
        if a == 0xFFFC00:
            return (1 if queue else 0) | (0x20 if state["sr_ovrn"] else 0)
        if a == 0xFFFC02:
            b, ovrn = queue.pop(0)
            state["sr_ovrn"] = ovrn
            return b
        return 0

    mem.set_special_range_read_func(0xFF0000, 0, read)       # (byte accesses: the ACIA registers)
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
        sys.exit("ikbd_test: did not finish (pc %x)" % cpu.r_pc())
    end = mem.r32(VARS + 8)
    return bytes(mem.r8(a) for a in range(LOG, end)), mem.r8(VARS)


def J(port, data):
    return [0xEE, port, data]


CASES = [
    # (name, stream, expected log, quit)
    ("keys", [0x4B, 0xCB, 0x1D, 0x9D], [0x4B, 0xCB, 0x1D, 0x9D], False),
    ("Esc tap", [0x01, 0x81], [], True),
    ("Esc, a key between", [0x01, 0x4B, 0x81], [0x4B], False),
    ("Esc, a joystick packet between", [0x01, 0xFF, 0x08, 0x81], J(2, 0x08), False),
    ("joystick up", [0xFF, 0x01, 0xFF, 0x81, 0xFF, 0x00], J(2, 0x01) + J(2, 0x81) + J(2, 0x00), False),
    ("joystick 0", [0xFE, 0x04], J(1, 0x04), False),
    ("mouse packet skipped", [0xF8, 0x01, 0x02, 0x4B], [0x4B], False),
    ("status packet skipped", [0xF6, 1, 1, 1, 1, 1, 1, 0x81, 0x4B], [0x4B], False),
    ("absolute mouse skipped", [0xF7, 1, 0x81, 2, 3, 4, 0x02], [0x02], False),
    ("time of day skipped", [0xFC, 1, 0x81, 2, 3, 4, 5, 0x4B], [0x4B], False),
    ("both joysticks report", [0xFD, 0x01, 0x81, 0x4B], [0x4B], False),
    # a lost joystick header: its "up" / "up + fire" data bytes are not Esc
    ("lost header, up", [0x4B, LOST, 0xFF, 0x01, 0xFF, 0x81], [0x4B] + J(2, 0x81), False),
    ("lost header twice", [0x4B, LOST, 0xFF, 0x01, 0xCB, LOST, 0xFF, 0x81], [0x4B, 0xCB], False),
    # a lost data byte: the packet is dropped, the next header is read as one
    ("lost data", [0xFF, LOST, 0x01, 0xFF, 0x81, 0x4B], J(2, 0x81) + [0x4B], False),
    ("lost key byte", [0x4B, LOST, 0xCB, 0x1D], [0x4B, 0x1D], False),
    ("lost Esc press", [0x4B, LOST, 0x01, 0x81], [0x4B], False),
    ("lost in a mouse packet", [0xF8, 0x01, LOST, 0x02, 0x4B], [0x4B], False),
]


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

    fails = 0
    for name, stream, want, quit in CASES:
        log, q = run(stream)
        if list(log) != want or bool(q) != quit:
            print("%s: log %s quit %d, expected %s quit %d" % (name, log.hex(" "), bool(q), bytes(want).hex(" "),
                                                               quit))
            fails += 1
    print("ikbd_test:", "FAIL (%d)" % fails if fails else "ok (%d streams)" % len(CASES))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
