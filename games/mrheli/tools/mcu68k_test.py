"""src/mcu.s on Musashi against the board's dual-port RAM traffic (a trace of tools/mcu_test.py --trace).

    venv/bin/python games/mrheli/tools/mcu68k_test.py TRACE [--poll] [--noswap]
    venv/bin/python games/mrheli/tools/mcu68k_test.py --synthetic FRAMES [--seed N] [--poll] [--noswap]

The trace holds the model's state and the dual-port RAM at its start frame, then in order the V30's writes to the
dual-port RAM ("w"), its port C0 writes ("c": value, units into the frame) and its reads ("r": the byte the board
gave).  mcu.s gets the same: the writes into its copy (a call of mcu_hb at the heartbeat word unless --poll builds
with MCU_HB_POLL = 1), mcu_cmd, and mcu_frame at every frame boundary.  At every read the 68000's byte must be the
board's.  Also run: tools/mcu.py's model (MCU) on the same trace; the samples mcu.s starts must be the model's (and
so the real MCU's, mcu_test.py checks the model against it).  --noswap: MCU_SWAP = 0 (the dual-port RAM in V30 order).
The 68000 cycles of mcu_frame and mcu_cmd are reported.
--synthetic: a trace made by the model itself (the expected bytes are the model's): heartbeats with gaps (long ones
reach the watchdog), random sample commands (any value, 2 a frame at most, at any time in the frame), $10 often,
$11 rarely, reads of the bytes the MCU writes.  It restarts the model when it dies or answers the ROM test.
"""
import argparse
import pickle
import subprocess
import sys
import zlib
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from paths import VASM, ROOT, build_dir  # noqa: E402
from m72board import load_regions  # noqa: E402
import mcu as model  # noqa: E402

ORG = 0x10000
HARNESS = """
	org	$%X
	dc.l	mcu_init, mcu_frame, mcu_cmd, mcu_hb, stopper, mcu_state, mcu_snd_start, mcu_snd_count, dpram
stopper:
	nop
	bra.s	stopper
%s
	even
dpram:	ds.b	4096
"""


def build(poll, swap):
    out = build_dir("mrheli")
    tables = out / "mcu_tables.s"
    if not tables.exists():
        r = load_regions("mrheli")
        model.write_tables(tables, r["mcu"], r["samples"])
    body = "\n".join(l for l in (ROOT / "games" / "mrheli" / "src" / "mcu.s").read_text().splitlines()
                     if not l.strip().startswith("section"))
    src = out / "mcu68k_test.s"
    src.write_text("MCU_HB_POLL equ %d\nMCU_SWAP equ %d\n" % (poll, swap) + HARNESS % (ORG, body))
    binf = out / "mcu68k_test.bin"
    r = subprocess.run([VASM, "-Fbin", "-quiet", "-I", str(out), "-o", str(binf), str(src)],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("vasm failed")
    return binf.read_bytes()


def synthetic(frames, seed, poll):
    import random
    rng = random.Random(seed)
    r = load_regions("mrheli")
    dp = bytearray(rng.randrange(256) for _ in range(4096))
    m = model.MCU(r["mcu"], r["samples"], dp)
    init = (m.state_image(), bytes(dp))
    tr, starve = [], 0
    look = list(range(0x20)) + [0xFFC] + list(range(0xFE0, 0xFEE))
    pokes = [o for o in look if o != 0xFFC]          # (the V30 does not write $FFC: mcu_test.py)
    for f in range(frames):
        if starve:
            starve -= 1
        elif rng.random() < 0.003:
            starve = rng.choice([1, 2, 5, 29, 30, 31, 40])
        if m.state != model.ST_IDLE and rng.random() < 0.02:
            tr.append((f, "reset", 0, 0))                    # (a fresh model, as after a new snapshot)
            m.state, m.wd, m.wipe = model.ST_IDLE, 0, 0xFF
        if not starve:
            for _ in range(rng.choice([1] * 30 + [1 if poll else 2])):
                v = (dp[0xFFE] + 1) & 0xFF
                dp[0xFFE] = v
                tr.append((f, "w", 0xFFE, bytes([v])))
                m.v30_write(0xFFE, 1)
        if rng.random() < 0.05:
            o = rng.choice(pokes)
            v = rng.randrange(256)
            dp[o] = v
            tr.append((f, "w", o, bytes([v])))
            m.v30_write(o, 1)
        for _ in range(rng.choice([0] * 6 + [1, 1, 2])):
            v = rng.choice([rng.randrange(6)] * 8 + [rng.randrange(256), 0x10, 0x10, 0x11 if rng.random() < 0.1 else 3])
            t = rng.choice([128, 128, 128, rng.randrange(model.UNITS_FRAME)])
            tr.append((f, "c", v, t))
            m.command(v, t)
        for o in look:
            tr.append((f, "r", o, dp[o]))
        m.frame()
    return dict(start=0, state=init[0], dpram=init[1], trace=tr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", nargs="?")
    ap.add_argument("--synthetic", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--noswap", action="store_true")
    a = ap.parse_args()
    if a.synthetic:
        d = synthetic(a.synthetic, a.seed, a.poll)
        a.trace = "synthetic seed %d" % a.seed
    else:
        d = pickle.loads(zlib.decompress(Path(a.trace).read_bytes()))
    swap = 0 if a.noswap else 1
    binary = build(int(a.poll), swap)
    from machine68k import CPUType, Machine, Register
    mach = Machine(CPUType.M68000, 2048)
    mem, cpu = mach.mem, mach.cpu
    mem.w_block(ORG, binary + bytes(0x100))
    e_init, e_frame, e_cmd, e_hb, stopper, st_a, snd_a, cnt_a, dp_a = (mem.r32(ORG + 4 * i) for i in range(9))
    cyc = {"frame": [], "cmd": [], "hb": []}

    def call(entry, name, d0=0, d1=0, a1=0):
        sp = 0x1F0000
        mem.w32(sp - 4, stopper)
        cpu.w_reg(Register.A7, sp - 4)
        cpu.w_reg(Register.A0, dp_a)
        cpu.w_reg(Register.A1, a1)
        cpu.w_reg(Register.D0, d0)
        cpu.w_reg(Register.D1, d1)
        cpu.w_pc(entry)
        n = 0
        while cpu.r_pc() != stopper:
            n += cpu.execute(1).cycles
            if n > 200000:
                raise SystemExit("%s did not return" % name)
        if name in cyc:
            cyc[name].append(n)

    def dp_set(o, v):
        mem.w8(dp_a + (o ^ swap), v)

    for o, v in enumerate(d["dpram"]):
        dp_set(o, v)
    mem.w_block(0x1E0000, d["state"])
    call(e_init, "init", a1=0x1E0000)
    r = load_regions("mrheli")
    twin = model.MCU(r["mcu"], r["samples"], bytearray(d["dpram"]))
    (twin.state, twin.wipe, twin.wd, twin.hb, twin.prio) = d["state"][:5]
    twin.end = int.from_bytes(d["state"][6:10], "big")
    twin.romsum = int.from_bytes(d["state"][10:14], "big")
    frame = d["start"]
    bad, nread, starts, mstarts = 0, 0, [], []
    for f, kind, x, y in d["trace"]:
        while frame < f:
            call(e_frame, "frame")
            twin.frame()
            frame += 1
        if kind == "reset":
            st = bytearray(mem.r_block(st_a, 14))
            st[0], st[1], st[2] = 0, 0xFF, 0
            mem.w_block(0x1E0000, bytes(st))
            call(e_init, "init", a1=0x1E0000)
            twin.state, twin.wd, twin.wipe = model.ST_IDLE, 0, 0xFF
        elif kind == "w":
            for k, v in enumerate(y):
                dp_set(x + k, v)
                twin.dp[x + k] = v
            twin.v30_write(x, len(y))
            if x + len(y) > 0xFFE and not a.poll:
                call(e_hb, "hb")
        elif kind == "c":
            before = mem.r16(cnt_a)
            call(e_cmd, "cmd", d0=x, d1=y)
            if mem.r16(cnt_a) != before:
                starts.append((f, mem.r8(snd_a)))
            n0 = len(twin.events)
            twin.command(x, y)
            mstarts += [(f, e[1] & 63) for e in twin.events[n0:] if e[0] == "start"]
        else:
            nread += 1
            got = mem.r8(dp_a + (x ^ swap))
            if got != y:
                bad += 1
                if bad <= 20:
                    print("frame %d: read $%03X: 68000 %02X, board %02X" % (f, x, got, y))
    for p, q in zip(starts, mstarts):
        if p != q:
            print('first sample difference: 68000 %s, model %s' % (p, q))
            break
    sbad = sum(1 for p, q in zip(starts, mstarts) if p != q) + abs(len(starts) - len(mstarts))
    print("%s (poll %d, swap %d): frames %d-%d, %d reads, %d differ; %d samples started, %d differ from the model" %
          (Path(a.trace).name, a.poll, swap, d["start"], frame, nread, bad, len(starts), sbad))
    for k, v in cyc.items():
        if v:
            print("   %s: %d calls, 68000 cycles mean %.0f, max %d" % (k, len(v), sum(v) / len(v), max(v)))
    return 1 if bad or sbad else 0


if __name__ == "__main__":
    sys.exit(main())
