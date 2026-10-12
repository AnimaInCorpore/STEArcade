"""The renderer's cost on a fixed workload, and its pictures: arcade RAM states of the attract mode, recorded once, are
drawn by a build's render_frame on Musashi (the two draw screens alternating, as in the game), CPU cycles plus the
Blitter model's bus cycles.  Every build draws exactly the same frames, so builds compare by cycles and by picture.

    python perf_test.py capture DIR [first] [count]    (DIR's --sim GALAGA.PRG / galaga.map, VBLs first.., default
                                                        2400 1200: build/galaga/perf_frames.bin)
    python perf_test.py replay DIR [--frames FILE]     (DIR holds GALAGA.PRG and galaga.map; writes DIR/perf_pics.npz)
    python perf_test.py compare OLD_DIR NEW_DIR        (the pictures in the game area identical; NEW's side bands (left
                                                        and right of it, all lines): no sprite pixel)

capture records the shared RAM ($8000-$A007) at each VBL of the sim build's own schedule (run_frames); replay marks the
video RAM blocks that changed since the previous state (as the translated writers would) and calls render_frame.  The
game logic's cost is not in these numbers (logic speed and picture rate are separate: see the README).
"""
import argparse
import os
import sys
from pathlib import Path

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir

RAM = 0x2008
FRAMES = build_dir("galaga") / "perf_frames.bin"
STOP = 0x700
SCREENS = (0x300000, 0x318000)
SOURCE = 0x330000
DISP_TOP, GAME_X, STRIDE = 32, 24, 256


def capture(directory, first, count):
    run = Path(directory)
    s = Sim(str(run / "GALAGA.PRG"), ram_kib=16384, run_dir=run)
    sym = {k: v + s.base for k, v in s.symbols(run / "galaga.map").items()}
    out = bytearray()

    def on_frame(sim):
        if sim.frames >= first:
            out.extend(sim.mem.r_block(sym["g_ram"], RAM))
    s.run_frames(first + count, on_frame)
    FRAMES.write_bytes(bytes(out))
    print("captured VBLs %d-%d: %s" % (first, first + count, FRAMES))


def replay(directory, frames_file):
    d = Path(directory)
    s = Sim(str(d / "GALAGA.PRG"), ram_kib=16384, run_dir=d)
    s.mem.set_trace_mode(True)
    syms = s.symbols(d / "galaga.map")
    sym = lambda k: s.base + syms[k]
    cpu, mem = s.cpu, s.mem
    edge = syms.get("edge_blits")
    edge = None if edge is None else s.base + edge

    def call(addr, watch=None):
        cpu.w_sr(0x2700)
        cpu.w_reg(R.A7, 0x8000)
        mem.w32(0x8000, STOP)
        cpu.w_pc(addr)
        total = inside = edges = 0
        depth = None
        while True:
            pc = cpu.r_pc()
            if pc == STOP:
                return total, inside, edges
            if pc == watch and depth is None:
                depth = cpu.r_reg(R.A7) + 4
                ret = mem.r32(depth - 4)
            if pc == edge:
                edges += 1
            c = cpu.execute(1).cycles + s.blitter.cycles
            s.blitter.cycles = 0
            total += c
            if depth is not None:
                inside += c
                if cpu.r_pc() == ret and cpu.r_reg(R.A7) == depth:
                    depth = None

    data = Path(frames_file).read_bytes()
    n = len(data) // RAM
    mem.w32(sym("bg_address"), SOURCE)
    for a in (*SCREENS, SOURCE):
        mem.w_block(a, bytes(384 * STRIDE))
    call(sym("init_render"))
    s.blitter.cycles = 0
    prev = None
    tot = spr = edges = 0
    pics, bands = [], []
    for f in range(n):
        ram = data[f * RAM:(f + 1) * RAM]
        mem.w_block(sym("g_ram"), ram)
        for b in range(64):
            if prev is None or ram[b * 32:b * 32 + 32] != prev[b * 32:b * 32 + 32]:
                mem.w8(sym("vblocks") + b, 0xFF)
        prev = ram
        index = f & 1
        mem.w16(sym("draw_index"), index)
        mem.w32(sym("draw_screen_address"), SCREENS[index])
        t, i, e = call(sym("render_frame"), sym("draw_sprites"))
        tot += t
        spr += i
        edges += e
        img = np.frombuffer(bytes(mem.r_block(SCREENS[index], 384 * STRIDE)), np.uint8).reshape(384, STRIDE)
        pics.append(img[DISP_TOP:DISP_TOP + 288, GAME_X:GAME_X + 112].copy())
        bands.append(int(np.count_nonzero(img[:, :GAME_X]) + np.count_nonzero(img[:, GAME_X + 112:])))   # (all lines)
    np.savez_compressed(d / "perf_pics.npz", pics=np.array(pics), bands=np.array(bands))
    print("%s: %d renders, render_frame %d cycles (%.0f a render), draw_sprites %d (%.0f a render), CPU + Blitter; "
          "edge parts %d; renders with bytes in the side bands %d" % (
              d.name, n, tot, tot / n, spr, spr / n, edges, sum(1 for b in bands if b)))
    s.m.cleanup()


def compare(old, new):
    a = np.load(Path(old) / "perf_pics.npz")
    b = np.load(Path(new) / "perf_pics.npz")
    diff = [f for f in range(len(a["pics"])) if not np.array_equal(a["pics"][f], b["pics"][f])]
    print("game area: %d of %d renders differ%s; side bands with bytes: old %d, new %d renders" % (
        len(diff), len(a["pics"]), (" (first %s)" % diff[:8]) if diff else "",
        int((a["bands"] > 0).sum()), int((b["bands"] > 0).sum())))
    return 1 if diff or (b["bands"] > 0).any() else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("capture", "replay", "compare"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--frames", default=str(FRAMES))
    a = ap.parse_args()
    if a.cmd == "capture":
        v = [int(x) for x in a.args[1:]] + [2400, 1200][len(a.args) - 1:]
        capture(a.args[0], v[0], v[1])
    elif a.cmd == "replay":
        replay(a.args[0], a.frames)
    else:
        return compare(*a.args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
