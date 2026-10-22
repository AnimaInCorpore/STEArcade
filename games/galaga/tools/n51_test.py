"""The STE build's 51XX (the translated chip, galaga.s g_ctrl06 / n51_*) in the whole program against the reference in
the same schedule (tools/machine.py run_frame_port with Galaga(mcu=True, mcu_events=True)): the same inputs, and the
06XX traffic of both compared tick by tick (the 51XX's VBLs): the transfers started (control), the bytes written, the
bytes read.

A --sim build with -D IOLOG=1 runs on Musashi; the inputs go into its keyboard cells at every VBL, where the 51XX
takes them.  The build needs a few hundred VBLs to start the game, so both sides count the 51XX's ticks instead: the
VBLs with its reset line (latch $6823) released; the script's frame is that count + 699 (MAME's full boot).  The log's kinds (4: a tick): 1 a transfer's control value,
2 a byte written, 3 a byte read.

    python n51_test.py [frames] [script]        # default 3000 coin; the scripts of ref/mame_cmp_51xx.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "ref"), os.path.join(HERE, "..", "..", "..", "engine")]
FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
SCRIPT = sys.argv[2] if len(sys.argv) > 2 else "coin"
sys.argv = [sys.argv[0], str(FRAMES), SCRIPT]
from sim import Sim
from paths import ROOT, build_dir
from machine import Galaga
import mame_cmp_51xx as scripts

RUN = ROOT / "run" / "galaga_n51"
LOGSIZE = 1 << 20


def inputs(tick):
    """the inputs for the 51XX's tick (1: its first VBL out of reset)"""
    return scripts.inputs(tick + 699) if tick > 0 else (0xff, 0xff)


def ste():
    RUN.mkdir(parents=True, exist_ok=True)
    prg = RUN / "GALAGA.PRG"
    subprocess.run([sys.executable, os.path.join(HERE, "build.py"), "--sim", "-D", "IOLOG=1", "-D",
                    "IOLOGSIZE=%d" % LOGSIZE, "--out", str(prg)], check=True, stdout=subprocess.DEVNULL)
    s = Sim(str(prg), ram_kib=16384, run_dir=RUN)
    sym = {k: v + s.base for k, v in s.symbols(build_dir("galaga") / "galaga.map").items()}

    tick = [0]
    io1 = sym["G_IO1"]

    def on_frame(sim):
        if sim.mem.r8(io1 + 0x6823):
            tick[0] += 1
        in0, in1 = inputs(tick[0])
        sim.mem.w8(sym["in0_kbd"], ~in0 & 0xff)
        sim.mem.w8(sym["in1_kbd"], ~in1 & 0xff)
    while tick[0] < FRAMES and s.frames < FRAMES + 2000:
        s.run_frames(100, on_frame)
    end = s.mem.r32(sym["iolog_ptr"])
    raw = bytes(s.mem.r_block(sym["iolog_buf"], end - sym["iolog_buf"]))
    if end >= sym["iolog_buf"] + LOGSIZE - 2:
        sys.exit("the log is full")
    return [(raw[i], raw[i + 1]) for i in range(0, len(raw), 2)]


def reference():
    m = Galaga(skip_tests=True, mcu=True, mcu_events=True)
    log = []
    cw, dw, dr = m.ctrl06_w, m.data06_w, m.data06_r

    def ctrl(v):
        if not m.in_nmi06:
            log.append((1, v))
        cw(v)

    def write(v):
        if m.in_nmi06:
            log.append((2, v))
        dw(v)

    def read():
        v = dr()
        if m.in_nmi06:
            log.append((3, v))
        return v
    m.ctrl06_w, m.data06_w, m.data06_r = ctrl, write, read
    tc = m.n51.mcu.set_tc

    def set_tc(v):
        if not v and not m.n51.held:
            log.append((4, 0))
        tc(v)
    m.n51.mcu.set_tc = set_tc
    tick = 0
    while True:
        m.run_frame_port_inputs = None
        # the inputs of this frame's VBL: the tick counts if the latch is released by then; the main thread runs
        # first, so the inputs are set from the latch before the frame and fixed up below if it releases during it
        nxt = tick + 1 if m.latch[3] else tick
        m.in0, m.in1 = inputs(nxt)
        was = m.latch[3]
        m.run_frame_port()
        if m.latch[3]:
            tick += 1
            if not was:
                pass                # (released during this frame: its VBL was tick 1, with no input set: all idle)
        if tick >= FRAMES:
            break
    return log


def drop_retries(log):
    """the coinage's rounds that the main CPU repeats ($3737: write $E1 + 8 bytes, read $B1 + 3 bytes, again while the
    first byte read is no BCD credit count): on the arcade a vertical blank falls into the slow transfer and the 51XX's
    frame turns its answers to credit mode before the read; the reference's schedule does it all at once and repeats
    until its next VBL, the STE build as the VBL happens to fall.  The failed rounds are dropped on both sides."""
    out, i = [], 0
    while i < len(log):
        blk = log[i:i + 13]
        if (len(blk) == 13 and blk[0] == (1, 0xE1) and all(k == 2 for k, _ in blk[1:9]) and blk[9] == (1, 0xB1)
                and all(k == 3 for k, _ in blk[10:13]) and (blk[10][1] >= 0xA1 or blk[10][1] & 15 >= 10)):
            i += 13
            continue
        out.append(log[i])
        i += 1
    return out


def by_tick(log, chip=1):
    """the log cut at the ticks: [entries before tick 1, after tick 1, ...] (the tick markers' values dropped), only
    the traffic of the chip (control bit 0: the 51XX, 8: the 54XX: its explosions follow the game play, which differs
    between the two sides from the boot on, see main)"""
    out = [[]]
    ctrl = 0
    for k, v in log:
        if k == 4:
            out.append([])
        elif k == 1:
            ctrl = v
            if v & chip:
                out[-1].append((k, v))
        elif ctrl & chip and k == (3 if ctrl & 0x10 else 2):
            out[-1].append((k, v))      # (a transfer the NMI handler starts inside another is not logged: its bytes
    return out                          # go the other way, the 54XX's writes inside a 51XX read)


def settled(ticks):
    """the first tick after the coinage was read back right (the boot's transfers differ in where the VBLs fall)"""
    for t, seg in enumerate(ticks):
        for i, e in enumerate(seg):
            if e == (1, 0xB1) and len(seg) > i + 1 and seg[i + 1][0] == 3 and seg[i + 1][1] < 0xA1 and seg[i + 1][1] & 15 < 10:
                return t + 1
    return None


def main():
    la, lb = ste(), reference()
    a, b = by_tick(la), by_tick(lb)
    c = by_tick(la, 8)
    d = by_tick(lb, 8)
    print("54XX commands (information): %d ticks of %d differ" % (sum(1 for t in range(min(len(c), len(d))) if c[t] != d[t]),
                                                                 min(len(c), len(d))))
    ta, tb = settled(a), settled(b)
    if ta is None or tb is None:
        sys.exit("the coinage was not read back (STE tick %s, reference %s)" % (ta, tb))
    t0 = max(ta, tb)
    print("coinage read back in tick %d (STE) / %d (reference); compared from tick %d" % (ta - 1, tb - 1, t0))
    n = min(len(a), len(b))
    bad = [t for t in range(t0, n) if a[t] != b[t]]
    print("%s: 51XX traffic, ticks %d (STE) / %d (reference), %d compared, %d differ" % (SCRIPT, len(a) - 1, len(b) - 1,
                                                                                       n - t0, len(bad)))
    for t in bad[:5]:
        print("  tick %d: STE %s\n           reference %s" % (t, " ".join("%d%02X" % e for e in a[t]), " ".join("%d%02X" % e for e in b[t])))
    print("PASS" if not bad and n - t0 > 0 else "FAIL")
    return 1 if bad else 0


def main_flat():
    a = drop_retries(ste())
    b = drop_retries(reference())
    n = min(len(a), len(b))
    d = next((i for i in range(n) if a[i] != b[i]), None)
    print("%s %d frames: 06XX log STE %d, reference %d entries" % (SCRIPT, FRAMES, len(a), len(b)))
    if d is None and len(a) == len(b):
        print("identical\nPASS")
        return 0
    i = d if d is not None else n
    print("first difference at %d:" % i)
    for j in range(max(0, i - 8), min(n, i + 8)):
        print("  %6d  STE %d %02X   reference %d %02X%s" % (j, a[j][0], a[j][1], b[j][0], b[j][1], "   <--" if a[j] != b[j] else ""))
    print("FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
