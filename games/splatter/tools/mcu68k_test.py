"""src/mcu.s (the MCU natively in 68000 code) on Musashi against tools/mcu.py's MCUNative, frame by frame.

    venv/bin/python games/splatter/tools/mcu68k_test.py [frames] [--seed N] [--synthetic]

MCUNative starts from the reference board's MCU after its boot (machine.Splatter.boot; --synthetic: zero RAM and
random time counters, no board), mcu.s from MCUNative's state (state_image).  Every frame both get the same TRIRAM
and inputs: random CONTROL0/1, COIN and DIP bytes; poked now and then: voice requests (pages 3 and 6 mostly, any page
and sample sometimes, stops), coin counter requests ($039/$03A), the lockout ($03B), $038's bits, a frame with
TRIRAM[0] not $A6; 40 % of the requests are samples that end within a tick of a window's edge.  Compared: all of TRIRAM, the MCU RAM bytes mcu.s keeps ($8E-$BA, the channels' on/header/
request bytes), the port 1 byte, the samples started and stopped.  The 68000 cycles of a frame are reported.
The voice tables (build/splatter/mcu_samples.s) are generated when missing (mcu.py --tables).
"""
import argparse
import random
import subprocess
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from paths import VASM, ROOT, build_dir
from namcos1 import load_regions
from mcu import MCUNative, write_tables, sample_info

ORG = 0x10000
RAM_CHECK = list(range(0x8E, 0xBB)) + [0xD6, 0xDC, 0xDD, 0xDE, 0xDF, 0xE5, 0xE6, 0xE7]

HARNESS = """
	org	$%X
	bra.s	go
	dc.l	mcu_state, mcu_p1, mcu_start, mcu_stop, tri, inputs, stopper, mcu_sample_offsets
go:	lea	tri,a0
	lea	inputs,a1
	jsr	mcu_frame
stopper:
	nop
	bra.s	stopper
%s
	even
tri:	ds.b	2048
inputs:	ds.b	4
"""


def build(regions):
    out = build_dir("splatter")
    tables = out / "mcu_samples.s"
    if not tables.exists():
        print("generating", tables)
        write_tables(tables, regions["voice"], regions["mcu"])
    src = out / "mcu68k_test.s"
    # (one flat binary: the sections of mcu.s dropped)
    body = "\n".join(l for l in (ROOT / "games" / "splatter" / "src" / "mcu.s").read_text().splitlines()
                     if not l.strip().startswith("section"))
    src.write_text(HARNESS % (ORG, body))
    binf = out / "mcu68k_test.bin"
    r = subprocess.run([VASM, "-Fbin", "-quiet", "-I", str(ROOT / "games" / "splatter" / "src"), "-I", str(out),
                        "-o", str(binf), str(src)], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("vasm failed")
    return binf.read_bytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    regions = load_regions("splatter")
    if args.synthetic:
        nat = MCUNative(regions["voice"], None, regions["mcu"])
        for a in (0x8F, 0x93, 0x97, 0x9B):
            nat.ram[a:a + 4] = bytes([0x00, 0x12, 0x59, 0x58])
        nat.ram[0xB4] = 0x07
        tri = bytearray(0x800)
        tri[0] = 0xA6
    else:
        from machine import Splatter
        m = Splatter()
        m.boot()
        nat = MCUNative.from_board(m)
        tri = bytearray(m.triram)
    binary = build(regions)
    # samples that end near a window's edge when started at ACT_TICK (the edge cases of the end tick)
    from mcu import sample_length, ACT_TICK, TICKS
    edge = [(nib, n) for nib in (0, 1, 2, 3, 4, 5, 6, 7) for n in range(1, 256)
            if (ACT_TICK + sample_length(regions["voice"], nib, n, regions["mcu"])) % TICKS in (TICKS - 1, 0, 1)
            and sample_length(regions["voice"], nib, n, regions["mcu"]) < 3000]
    from machine68k import CPUType, Machine
    mach = Machine(CPUType.M68000, 2048)
    mem, cpu = mach.mem, mach.cpu
    mem.w_block(ORG, binary + bytes(0x1000))
    st, p1a, starta, stopa, tria, inpa, stopper, offs = (mem.r32(ORG + 2 + 4 * i) for i in range(8))
    image = nat.state_image()
    mem.w_block(st, image)
    bad = 0
    cycles = []
    events = {"started": 0, "stopped": 0, "end": 0, "ignored": 0}
    for f in range(args.frames):
        # the main CPU's part: requests
        for ch in (0, 1):
            if rng.random() < 0.04:
                o = 0x2B + 2 * ch
                page = rng.choice([3, 6, 3, 6, 3, 6, rng.randrange(16)])
                n = rng.choice([0, rng.randrange(1, 40), rng.randrange(1, 40), rng.randrange(1, 256)])
                if edge and rng.random() < 0.4:
                    page, n = rng.choice(edge)
                tri[o] = n
                tri[o + 1] = (tri[o + 1] & 0x80) | 0x40 | page
        if rng.random() < 0.01:
            tri[0x39 + rng.randrange(2)] += rng.randrange(1, 3)
        if rng.random() < 0.02:
            tri[0x3B] = rng.choice([0, 1])
        if rng.random() < 0.01:
            tri[0x38] = rng.randrange(8)
        if rng.random() < 0.003:
            tri[0] = 0x00
        elif tri[0] != 0xA6 and rng.random() < 0.3:
            tri[0] = 0xA6
        inp = bytes([rng.randrange(256), rng.randrange(256), 0xF8 & ~rng.choice([0] * 20 + [0x08, 0x10, 0x40]),
                     rng.choice([0xFF] * 10 + [rng.randrange(256)])])
        # 68000
        mem.w_block(tria, bytes(tri))
        mem.w_block(inpa, inp)
        cpu.w_reg(__import__("machine68k").Register.A7, 0x1F0000)
        cpu.w_pc(ORG)
        n = 0
        while cpu.r_pc() != stopper:
            n += cpu.execute(1).cycles
            if n > 2000000:
                raise SystemExit("mcu_frame did not return")
        cycles.append(n)
        # the model
        rec = nat.frame(tri, inp[0], inp[1], inp[2], inp[3])
        got_tri = bytes(mem.r_block(tria, 0x800))
        got_ram = bytes(mem.r_block(st, 128))
        problems = []
        d = [o for o in range(0x800) if got_tri[o] != tri[o]]
        if d:
            problems.append("TRIRAM %s" % ["%03X %02X/%02X" % (o, got_tri[o], tri[o]) for o in d[:8]])
        d = [a for a in RAM_CHECK if got_ram[a - 0x80] != nat.ram[a]]
        if d:
            problems.append("RAM %s" % ["%02X %02X/%02X" % (a, got_ram[a - 0x80], nat.ram[a]) for a in d[:8]])
        if rec["p1"] is not None and mem.r8(p1a) != rec["p1"]:
            problems.append("port 1 %02X/%02X" % (mem.r8(p1a), rec["p1"]))
        started = {e[1]: e[3][0] for e in rec["events"] if e[2] == "started"}
        stopped = {e[1] for e in rec["events"] if e[2] == "stopped"}
        for e in rec["events"]:
            for k in events:
                if e[2].startswith(k):
                    events[k] += 1
        for ch in (0, 1):
            idx = mem.r32(starta + 4 * ch)
            got = None if idx == 0xFFFFFFFF else mem.r32(offs + 4 * idx)
            if got != started.get(ch):
                problems.append("channel %d started %s / %s" % (ch, got, started.get(ch)))
            if bool(mem.r8(stopa + ch)) != (ch in stopped):
                problems.append("channel %d stop %d / %s" % (ch, mem.r8(stopa + ch), ch in stopped))
        if problems:
            bad += 1
            if bad <= 20:
                print("frame %d:" % f)
                for p in problems:
                    print("   " + p)
            # resync
            mem.w_block(st, nat.state_image())
        if f % 5000 == 4999:
            print("%d frames, %d with differences" % (f + 1, bad), flush=True)
    print("%d frames compared, %d with differences; events %s" % (args.frames, bad, events))
    print("68000 cycles a frame: mean %.0f, max %d" % (sum(cycles) / len(cycles), max(cycles)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
