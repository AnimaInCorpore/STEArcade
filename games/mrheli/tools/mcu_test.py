"""The MCU model (tools/mcu.py, the twin of src/mcu.s) against the real i8751 program in the reference board.

    venv/bin/python games/mrheli/tools/mcu_test.py [frames] [--seed N] [--start F] [--romtest F] [--starve F]
                                                   [--trace out.pkl.z]

The board (engine/m72board.py: V30, Z80 and the i8751 on engine/i8051.py, equal to MAME) runs from power-on; at frame
--start (>= mcu.BOOT_END) the model takes the MCU's state (MCU.from_board) and a copy of the dual-port RAM.  From
then on the model sees only what the STE program will see: the V30's writes to the dual-port RAM (applied to its copy
when the board applies them), the V30's port C0 writes (MCU.command, with the time in the frame) and the frame
boundaries (MCU.frame).  Checked:
  - every byte the V30 reads from the dual-port RAM (instruction fetches included): the model's copy = the board's;
  - every sample command: taken or not, the sample's address (the MCU's writes to its data space 0 and 1);
  - the DAC bytes of every sample (port 1) against mcu.dac_value of the sample's bytes, and its length.
--seed: the inputs, ref/cover.py's (1-3 attract, 4-7 coin at 600, start and random play, 8+ the same with the
Invulnerability DIP switch).  --romtest F: the sound latch gets $11 at frame F (as if the V30 had asked: service mode's ROM
test) on the board and the model; --starve F: the V30's writes to $B0FFE are dropped on both sides from frame F for
40 frames (the watchdog).  --trace: the V30 reads/writes and the commands, for mcu68k_test.py.
"""
import argparse
import pickle
import random
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from m72board import M72, AS, FRAME_AS  # noqa: E402
import mcu as model  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ref"))
try:
    import cover  # noqa: E402  (agent A's)
except ImportError:
    cover = None

UNIT_AS = FRAME_AS // model.UNITS_FRAME


def press(m, f, seed, rng, st):
    """ref/cover.py's inputs (agent A's lock-step seeds: 1-3 attract, 4-7 play, 8+ with Invulnerability)"""
    if cover:
        cover.press(m, f, seed, rng, st)
        return
    m.in0 = m.in1 = 0xFFFF                                # (the same scheme without ref/cover.py)
    if seed > 3:
        if f % 2400 in (600, 601, 602, 603):
            m.in1 &= ~0x04
        if f % 2400 in range(660, 666):
            m.in1 &= ~0x01
        if f >= 720:
            if st["hold"] <= 0:
                st["bits"] = rng.choice([0, 1, 2, 4, 8, 5, 9, 6, 10, 0x80, 0x81, 0x82, 0x84, 0x88, 0x40, 0x01, 0x80])
                st["hold"] = rng.randint(2, 60)
            st["hold"] -= 1
            m.in0 = 0xFFFF & ~st["bits"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--start", type=int, default=model.BOOT_END)
    ap.add_argument("--romtest", type=int, default=-1)
    ap.add_argument("--starve", type=int, default=-1)
    ap.add_argument("--check", type=int, action="append", default=[],
                    help="frame: the main task [3712] = 0040:1ECA (the protection check: port C0 $10, call B000:0000)")
    ap.add_argument("--trace")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    b = M72("mrheli")
    if a.seed >= 8:
        b.dsw &= ~0x4000
    rng, st = random.Random(a.seed), dict(hold=0, bits=0)
    t0 = time.time()
    for f in range(a.start):
        press(b, f, a.seed, rng, st)
        b.run_frame()
    mod = model.MCU.from_board(b)
    mod.dp = bytearray(b.dpram)
    init = (mod.state_image(), bytes(mod.dp))
    cpu = b.mcu.core.cpu
    F = [a.start]
    fstart = [b.base]
    bad = []
    reads = Counter()
    trace = []                                            # (frame, kind, offset/value, n/value)
    starve = lambda: a.starve <= F[0] < a.starve + 40    # noqa: E731

    def units():
        return (b.now() - fstart[0]) // UNIT_AS

    o_rd = b.dpram_left_r

    def rd(o):
        v = o_rd(o)
        reads[o] += 1
        if mod.dp[o] != v and len(bad) < 10000:
            bad.append((F[0], b.vpos(), o, v, mod.dp[o]))
        if a.trace:
            trace.append((F[0], "r", o, v))
        return v
    b.dpram_left_r = rd
    o_wr = b.dpram_left_w

    def wr(o, data, mask):
        if (o >> 1) == 0x7FF and starve():
            return
        o_wr(o, data, mask)
        lo, n = (o, 2) if mask == 0xFFFF else ((o, 1) if mask == 0xFF else (o + 1, 1))
        for k in range(n):
            mod.dp[lo + k] = b.dpram[lo + k]
        mod.v30_write(lo, n)
        if a.trace:
            trace.append((F[0], "w", lo, bytes(b.dpram[lo:lo + n])))
    b.dpram_left_w = wr
    o_io = b.io_write

    def io(p, data, mask):
        o_io(p, data, mask)
        if p == 0xC0 and mask & 0xFF:
            if data & 0xFF == 0x10:
                sent[0] = True
            mod.command(data & 0xFF, units())
            if a.trace:
                trace.append((F[0], "c", data & 0xFF, units()))
    b.io_write = io
    # the board's sample commands and starts (the MCU's latch reads, data space writes 1 then 0, port 1)
    cmds = []                                             # [value, frame, units, addr or None, dac bytes]
    o_mrd, o_mwr = cpu.rd_data, cpu.wr_data

    def mrd(x):
        v = o_mrd(x)
        if x == 2:
            cmds.append([v, F[0], units(), None, bytearray(), None])
        return v

    def mwr(x, v):
        o_mwr(x, v)
        if x == 0 and cmds and cpu.pc in range(0x0557, 0x05C1):
            cmds[-1][3] = b.mcu_sample_addr
    cpu.rd_data, cpu.wr_data = mrd, mwr
    o_po = cpu.port_out

    def po(n, v):
        o_po(n, v)
        if n == 1:
            for c in reversed(cmds):
                if c[3] is not None:
                    c[4].append(v)
                    if v == 0x80 and cpu.pc in range(0x05D0, 0x05D9) and c[5] is None:
                        c[5] = F[0] * model.UNITS_FRAME + units()          # (the sample's end)
                    break
    cpu.port_out = po
    fbad = []                                             # frame boundaries with the whole dual-port RAM different
    task = [None]
    next_task = [None]
    sent = [False]
    v = b.main.core.cpu
    o_w16 = v.wr16

    def w16(x, val):
        if task[0] is not None and (x & 0xFFFFF) == 0xA3712 and val == 0x1ED9:
            next_task[0], val = 0x1ED9, task[0]            # (1ED9 at the next frame boundary)
        o_w16(x, val)
    v.wr16 = w16
    for f in range(a.start, a.frames):
        F[0] = f
        if f in a.check:                                  # (an object's task: 1ECA one frame, 1ED9 the next)
            task[0] = b.ram[0x3712] | b.ram[0x3713] << 8
            sent[0] = False
            b.ram[0x3712:0x3714] = (0x1ECA).to_bytes(2, "little")
        elif task[0] is not None:
            w = b.ram[0x3712] | b.ram[0x3713] << 8
            if next_task[0] is not None:
                b.ram[0x3712:0x3714] = next_task[0].to_bytes(2, "little")
                next_task[0] = None
            elif w == 0x0470:
                b.ram[0x3712:0x3714] = task[0].to_bytes(2, "little")      # (the check's end: the game's task again)
                print("frame %d: the check ran" % f)
                task[0] = None
            elif not sent[0]:
                b.ram[0x3712:0x3714] = (0x1ECA).to_bytes(2, "little")
        if f == a.romtest:
            b.mculatch.write(0x11)
            mod.command(0x11, 0)
        press(b, f, a.seed, rng, st)
        b.run_frame()
        fstart[0] = b.base
        mod.frame()
        if mod.dp != b.dpram:
            fbad.append((f, [o for o in range(0x1000) if mod.dp[o] != b.dpram[o]]))
        if not a.quiet and f % 1000 == 999:
            print("frame %d: %d read mismatches, %.0fs" % (f + 1, len(bad), time.time() - t0), flush=True)
    # sample commands
    mev = [e for e in mod.events if e[0] in ("start", "ignore")]
    bcmd = [c for c in cmds if c[0] not in (0x10, 0x11)]
    sbad = []
    if len(mev) != len(bcmd):
        sbad.append("commands: model %d, board %d" % (len(mev), len(bcmd)))
    dac_ok = 0
    ends = Counter()                                      # board end - model end (lines)
    for e, c in zip(mev, bcmd):
        if e[1] != c[0] or (e[0] == "start") != (c[3] is not None) or (e[0] == "start" and e[2] != c[3]):
            sbad.append("frame %d: command %02X board %s, model %s" % (c[1], c[0], c[3], e))
            continue
        if e[0] == "start":
            want = bytes(model.dac_value(x, e[4]) for x in model.sample_bytes(b.samples, e[2]))
            got = bytes(c[4])
            ended = got[len(want):len(want) + 1] == b"\x80"
            if not want.startswith(got[:len(want)]) or (len(got) > len(want) and not ended):
                sbad.append("frame %d: command %02X DAC differs" % (c[1], c[0]))
            else:
                dac_ok += 1
            if c[5] is not None:
                want_end = c[1] * model.UNITS_FRAME + e[5] + 3 * e[3] * (len(model.sample_bytes(b.samples, e[2])) + 1)
                ends[(c[5] - want_end) // model.UNITS_LINE] += 1
    lag = Counter((c[2] - e[2]) // model.UNITS_LINE for e, c in
                  zip([e for e in mod.events if e[0] == "cmd"], cmds))
    print("frames %d-%d, seed %d: %d V30 reads of the dual-port RAM (%d offsets), %d differ" %
          (a.start, a.frames, a.seed, sum(reads.values()), len(reads), len(bad)))
    for x in bad[:20]:
        print("   frame %d line %d: $%03X board %02X model %02X" % x)
    print("frame boundaries with the dual-port RAM different: %d" % len(fbad))
    for f, d in fbad[:10]:
        print("   frame %d: %d bytes at %s" % (f, len(d), " ".join("%03X" % o for o in d[:12])))
    print("commands %s; samples: %d commands, %d started, %d DAC streams equal, %d problems" %
          (dict(Counter(c[0] for c in cmds)), len(bcmd), sum(1 for e in mev if e[0] == "start"), dac_ok, len(sbad)))
    for s in sbad[:20]:
        print("   " + s)
    print("sample ends, board - model (lines): %s" % dict(sorted(ends.items())))
    print("command lag (lines, port C0 -> MCU latch read): %s" % dict(sorted(lag.items())))
    print("MCU at the end: pc %04X $44=%02X $5B=%02X; model state %d wd %02X wipe %02X" %
          (cpu.pc, cpu.ram[0x44], cpu.ram[0x5B], mod.state, mod.wd, mod.wipe))
    print("offsets read: %s" % " ".join("%03X" % o for o in sorted(reads)[:64]))
    if a.trace:
        Path(a.trace).write_bytes(zlib.compress(pickle.dumps(dict(start=a.start, state=init[0], dpram=init[1], trace=trace)), 6))
    return 1 if bad or sbad else 0


if __name__ == "__main__":
    sys.exit(main())
