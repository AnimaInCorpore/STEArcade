"""The translated main CPU program (run/rtype_sim/RTYPE.PRG on Musashi) against the reference's port schedule
(machine.py RType.run_frame_port), frame by frame.

    venv/bin/python games/rtype/tools/logic_test.py [frames] [--seed N] [--start F] [--trace F] [--steplock F]

The reference boots on MAME's schedule to machine.START; its state goes into the simulator (the work RAM, the sprite
RAM, the palettes, the video RAMs and the sound CPU's RAM into the image, the registers and segments into the context).
Every frame: the inputs (seeds as ref/cover.py: 1-3 attract, 4-7 play, 8+ play with the Invulnerability DIP switch),
port_frame in the simulator, run_frame_port in the reference.  Compared: the work RAM (the PSW the port's interrupt
pushes: only its live flags, IE and DF), the sprite RAM and the buffer the picture shows, the palettes, the video RAMs
(and that every 256-byte block of the palettes and video RAMs that changed has its mark: tools/gen.py store_marks),
the registers and segments at the idle point, the scroll, raster and control ports, the sound latch's writes.
--steplock F runs frame F instruction by instruction against the interpreter (registers at every translated label).
"""
import argparse
import bisect
import json
import os
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import RType
from paths import ROOT, build_dir
import cover
from v30 import PAR
from gen import MARKS

PROFILE = None                  # (tools/profile.py: dict(start, frames, stepper))
REGIONS = (("ram", 0x40000, 0x4000), ("sprites", 0xC0000, 0x400), ("pal0", 0xC8000, 0xC00), ("pal1", 0xCC000, 0xC00),
           ("fg", 0xD0000, 0x4000), ("bg", 0xD8000, 0x4000))
DREG = ((R.D0, 0), (R.D1, 1), (R.D2, 2), (R.D3, 3), (R.D4, 6), (R.D5, 7), (R.D6, 5))     # (68000, V30 index)


def swap(b):
    out = bytearray(len(b))
    out[0::2] = b[1::2]
    out[1::2] = b[0::2]
    return bytes(out)


def ref_region(m, base, n):
    if base == 0x40000:
        return bytes(m.ram)
    if base == 0xC0000:
        return bytes(m.spriteram)
    if base in (0xC8000, 0xCC000):
        return bytes(m.palette[(base >> 14) & 1])
    return bytes(m.videoram[0 if base == 0xD0000 else 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=600)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--trace", type=int, default=-1, help="frame whose translated labels are logged")
    ap.add_argument("--start", type=int, default=0, help="frames the reference runs alone before the comparison")
    ap.add_argument("--steplock", type=int, default=-1, help="frame run instruction by instruction against the "
                    "interpreter (registers compared at every translated label)")
    args = ap.parse_args()
    run = ROOT / "run" / "rtype_sim"
    s = Sim(str(run / "RTYPE.PRG"), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(build_dir("rtype") / "rtype_sim.map").items()}
    mem, cpu = s.mem, s.cpu
    img, ctx = sym["v30_image"], sym["ctx_main"]
    labels = sorted((v, k) for k, v in sym.items() if k[:1] == "R" and len(k) == 6 and all(
        ch in "0123456789ABCDEF" for ch in k[1:]))
    lv = [v for v, k in labels]
    trail = []

    def run_to(stop, limit=400_000_000, trace=False):
        total = 0
        bad = sym["sim_badpc"]
        while total < limit:
            if trace:
                pc = cpu.r_pc()
                i = bisect.bisect_right(lv, pc) - 1
                if i >= 0 and lv[i] == pc:
                    trail.append(labels[i][1])
                total += cpu.execute(1).cycles
            else:
                total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc == stop:
                return total
            if pc == bad:
                if trail:
                    print("last labels:", " ".join(trail[-60:]))
                regs = {r: cpu.r_reg(getattr(R, r)) & 0xFFFFFFFF for r in ("D0", "D1", "D2", "D3", "D4", "D5", "D6",
                                                                          "D7", "A2", "A3", "A4", "A5", "A7")}
                print("registers", {k: "%X" % v for k, v in regs.items()})
                raise RuntimeError("badpc %05X" % mem.r32(sym["badpc"]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError("timeout at %06X" % (cpu.r_pc() - s.base))

    run_to(sym["sim_wait"])
    m = RType()
    m.boot()
    c = m.main.core.cpu

    def load_state():
        """the reference's state into the simulator"""
        for name, base, n in REGIONS:
            mem.w_block(img + base, swap(ref_region(m, base, n)))
        mem.w_block(sym["m72_spritebuf"], swap(bytes(m.spritebuf)))
        for k, v in enumerate((m.scrolly[0], m.scrollx[0], m.scrolly[1], m.scrollx[1])):
            mem.w16(sym["m72_scroll"] + 2 * k, v)
        mem.w16(sym["m72_raster"], (m.raster_line + 128) & 0xFFFF)
        mem.w16(sym["sound_head"], 0)
        put_cpu()

    def put_cpu():
        for k in range(4):
            mem.w16(ctx + 2 * k, c.sr[k])
        mem.w8(ctx + 8, 0xFF if c.ie else 0)
        mem.w8(ctx + 9, 0xFF if c.df else 0)
        mem.w8(ctx + 10, 0 if PAR[c.pv & 0xFF] else 1)
        mem.w8(ctx + 11, 0x10 if c.av else 0)
        for k, (r68, i) in enumerate(DREG):
            mem.w32(ctx + 16 + 4 * k, c.r[i])
        bases = [img + (c.sr[k] << 4) for k in (0, 3, 2)]          # a2 DS1, a3 DS0, a4 SS
        for k, b in enumerate(bases + [bases[2] + c.r[4]]):
            mem.w32(ctx + 44 + 4 * k, b)
        f = c.flags
        mem.w16(ctx + 60, (f & 1) | (2 if f & 0x800 else 0) | (4 if f & 0x40 else 0) | (8 if f & 0x80 else 0))
    load_state()
    info = json.loads((build_dir("rtype") / "gen_info.json").read_text())
    live = info["idle_flags"]
    # the PSW bits the translation keeps at the idle point: IE DF, the reserved ones, the live flags
    keep = 0xF702 | (1 if live & 1 else 0) | (0x800 if live & 2 else 0) | (0x40 if live & 4 else 0) | \
        (0x80 if live & 8 else 0) | (4 if live & 0x100 else 0) | (0x10 if live & 0x200 else 0)
    print("idle flags live %X: PSW bits compared %04X" % (live, keep))

    def compare(f):
        bad = []
        for name, base, n in REGIONS:
            got = swap(bytes(mem.r_block(img + base, n)))
            ref = ref_region(m, base, n)
            diff = [o for o in range(n) if got[o] != ref[o]]
            if name == "ram" and m.irq_psws:
                for a in m.irq_psws:
                    o = a - 0x40000
                    g, w = got[o] | (got[o + 1] << 8), ref[o] | (ref[o + 1] << 8)
                    if not (g ^ w) & keep:
                        diff = [x for x in diff if x not in (o, o + 1)]
            if diff:
                bad.append("%s: %d bytes, first %s" % (name, len(diff), ["%05X %02X/%02X" % (base + o, got[o], ref[o])
                                                                       for o in diff[:6]]))
        sb = swap(bytes(mem.r_block(sym["m72_spritebuf"], 0x400)))
        if sb != bytes(m.spritebuf):
            bad.append("sprite buffer differs")
        regs = [mem.r32(ctx + 16 + 4 * k) for k in range(7)]
        want = [c.r[i] for r68, i in DREG]
        segs = [mem.r16(ctx + 2 * k) for k in range(4)]
        sp = (mem.r32(ctx + 56) - mem.r32(ctx + 52)) & 0xFFFFFFFF
        if regs != want or [segs[0], segs[2], segs[3]] != [c.sr[0], c.sr[2], c.sr[3]] or sp != c.sp:
            bad.append("registers %s segs %s SP %X, reference %s %s %X" % (
                ["%X" % x for x in regs], ["%X" % x for x in segs], sp, ["%X" % x for x in want],
                ["%X" % x for x in c.sr], c.sp))
        if (mem.r8(ctx + 8) != 0) != bool(c.ie):
            bad.append("IE %d, reference %d" % (mem.r8(ctx + 8) != 0, c.ie))
        sc = [mem.r16(sym["m72_scroll"] + 2 * k) for k in range(4)]
        if sc != [m.scrolly[0], m.scrollx[0], m.scrolly[1], m.scrollx[1]]:
            bad.append("scroll %s, reference %s" % (sc, [m.scrolly[0], m.scrollx[0], m.scrolly[1], m.scrollx[1]]))
        if mem.r16(sym["m72_raster"]) - 128 != m.raster_line and m.raster_line != 0:
            bad.append("raster %d, reference %d" % (mem.r16(sym["m72_raster"]) - 128, m.raster_line))
        head = mem.r16(sym["sound_head"])
        cmds = [w[1] & 0xFF for w in m.port_writes if w[0] == 0]
        nonlocal_sound[0] = (nonlocal_sound[0] + len(cmds)) % 64
        if head != nonlocal_sound[0]:
            bad.append("sound latch writes: head %d, reference %d" % (head, nonlocal_sound[0]))
        if bad:
            print("frame %d (%d after the start):" % (m.frame, f))
            for b in bad:
                print("   " + b)
            return False
        return True
    nonlocal_sound = [0]
    m.irq_psws = []
    orig_run_irq = m.run_irq

    def run_irq(vector, limit=5000000):
        m.irq_psws.append(((c.ss << 4) + ((c.sp - 2) & 0xFFFF)))
        orig_run_irq(vector, limit)
    m.run_irq = run_irq

    def steplock(f):
        sp7 = cpu.r_reg(R.A7) - 4
        mem.w32(sp7, sym["sim_wait"])
        cpu.w_reg(R.A7, sp7)
        cpu.w_pc(sym["port_frame"])
        at = {}
        for v, k in labels:
            at.setdefault(v, []).append(int(k[1:], 16))
        hist = []
        rom = m.rom
        irqs = [(n, ((rom[4 * n + 2] | rom[4 * n + 3] << 8) << 4) + (rom[4 * n] | rom[4 * n + 1] << 8))
                for n in (0x20, 0x22)]
        for n in range(20_000_000):
            pc = cpu.r_pc()
            if pc == sym["sim_wait"]:
                print("frame done without a difference")
                return
            if pc == sym["sim_badpc"]:
                print("badpc %05X (reference at %05X); before:" % (mem.r32(sym["badpc"]), c.pc))
                for h in hist[-14:]:
                    print("   %s %s | ref %s %s" % (h[0], ["%X" % x for x in h[1]], h[2], ["%X" % x for x in h[3]]))
                return
            if pc in at:
                lins = at[pc]
                if c.pc == 0x4D0 and irqs and irqs[0][1] in lins:
                    m.irq_psws.append(((c.ss << 4) + ((c.sp - 2) & 0xFFFF)))
                    c.interrupt(irqs.pop(0)[0])
                regs = [cpu.r_reg(r68) & 0xFFFF for r68, i in DREG]
                want = [c.r[i] for r68, i in DREG]
                hist.append(("%05X" % lins[0], regs, "%05X" % c.pc, want))
                if c.pc not in lins or regs != want:
                    print("differs before label %s (reference at %05X):" % (["%05X" % x for x in lins], c.pc))
                    for h in hist[-14:]:
                        print("   %s %s | ref %s %s" % (h[0], ["%X" % x for x in h[1]], h[2], ["%X" % x for x in h[3]]))
                    return
                done = {c.pc}
                while not (c.pc == 0x4D0 and m.idle()):
                    c.step()                            # (labels sharing an address: instructions without code)
                    if c.pc not in lins or c.pc in done:
                        break
                    done.add(c.pc)
            cpu.execute(1)
        print("no end")

    rng = random.Random(args.seed)
    state = dict(hold=0, bits=0)
    if args.seed >= 8:
        m.dsw &= ~0x4000
    cycles = 0
    for f in range(args.frames):
        cover.press(m, f, args.seed, rng, state)
        if f < args.start:
            m.run_frame_port()                          # (--start: the reference alone, then its state)
            if f == args.start - 1:
                load_state()
                nonlocal_sound[0] = 0
            continue
        in_ports = sym["in_ports"]
        mem.w16(in_ports, m.in0)
        mem.w16(in_ports + 2, m.in1)
        mem.w16(in_ports + 4, m.dsw)
        m.irq_psws = []
        if f == args.steplock:
            steplock(f)
            return 1
        sp7 = cpu.r_reg(R.A7) - 4
        mem.w32(sp7, sym["sim_wait"])
        cpu.w_reg(R.A7, sp7)
        cpu.w_pc(sym["port_frame"])
        video0 = bytes(mem.r_block(img + 0xC8000, MARKS[1]))
        mem.w_block(sym[MARKS[2]], bytes(MARKS[1] >> 8))
        try:
            if PROFILE and PROFILE["start"] <= f < PROFILE["start"] + PROFILE["frames"]:
                cycles += PROFILE["stepper"](cpu, mem, sym, labels, sym["sim_wait"])
            else:
                cycles += run_to(sym["sim_wait"], trace=f == args.trace)
        except RuntimeError as ex:
            print("frame %d (%d after the start): %s" % (m.frame, f, ex))
            return 1
        video1 = bytes(mem.r_block(img + 0xC8000, MARKS[1]))
        marks = bytes(mem.r_block(sym[MARKS[2]], MARKS[1] >> 8))
        for k in range(MARKS[1] >> 8):
            if video1[256 * k:256 * k + 256] != video0[256 * k:256 * k + 256] and not marks[k] and not os.environ.get("NO_MARKS"):
                print("frame %d: video block %05X changed without its mark" % (f, 0xC8000 + 256 * k))
                return 1
        m.run_frame_port()
        if not compare(f):
            print("stopped after %d good frames" % f)
            return 1
        if f % 100 == 99:
            print("%d frames ok (%.0f 68000 cycles a frame)" % (f + 1, cycles / (f + 1 - args.start)), flush=True)
    print("%d frames identical; %.0f 68000 cycles a frame" % (args.frames - args.start,
                                                              cycles / max(1, args.frames - args.start)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
