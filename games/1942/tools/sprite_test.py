"""Check the sprite drawing (generated Blitter routines, the generic path and the edge path) on Musashi with the Blitter model: for
sprite codes, every shift and many positions (including the ones where the part reaches a 64 KB boundary of the ring, and the edges)
the part must change exactly its opaque pixels inside the game area (transparent holes kept) and nothing around it - the margin
chunks beside the game area included: a part across the left (x -15..-1) or right edge (x 209..223) draws only its inner word
(draw_edge) - and the rectangle restore must put the seed back.  Every sprite code is also drawn at both edges with all 15 shifts
there, plainly and across a 64 KB boundary of the ring.  (An old build without draw_edge is tested through draw_part: it fails.)
Build with --sim without --debug first (DEBUG paints counters into the screen), then python games/1942/tools/sprite_test.py [all]    (`all`: every code and y, takes a few minutes)
"""
import os
import random
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim
import logic_test as lt
from assets import sprite_screen, one_hot, sprite_orders
from machine import Gfx


def main():
    full = len(sys.argv) > 1 and sys.argv[1] == "all"
    sim = Sim(str(lt.RUN / "1942.PRG"), ram_kib=16384, run_dir=lt.RUN)
    mem, cpu = sim.mem, sim.cpu
    mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(lt.MAP).items()}
    sim.bad = sym["z80_badpc"]
    assert lt.run_to(sim, {sym["sim_wait"]}) is not None

    def call(name, regs=None):
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_render_ret"])
        cpu.w_reg(R.A7, sp)
        for reg, value in (regs or {}).items():
            cpu.w_reg(reg, value & 0xffffffff)
        cpu.w_pc(sym[name])
        mem.set_trace_mode(True)
        assert lt.run_to(sim, {sym["sim_render_ret"]}) is not None
        mem.set_trace_mode(False)
        cpu.w_reg(R.A7, sp + 4)

    gfx = Gfx()
    screens = [sprite_screen(gfx, c) for c in range(512)]
    opaque = one_hot(__import__("numpy").stack([(s != 15).astype("uint8") for s in screens]), 2)[..., 1]
    orders = sprite_orders(opaque)
    clean = mem.r32(sym["clean_base"])
    rng = random.Random(int(os.environ.get("SEED", "7")))
    checks = crossing = 0
    crossing_edge = [0]
    edges = 0
    codes = [c for c in range(512) if opaque[c].any()]
    for code in codes:
        col = rng.randrange(16) if code != 296 else 15
        call("sprite_get", {R.D0: code, R.D1: col})
        source = cpu.r_reg(R.A0)
        baked = bytes(mem.r_block(source, 128))
        natural = bytearray(128)
        for index, row in enumerate(orders[code]):
            natural[row * 8:row * 8 + 8] = baked[index * 8:index * 8 + 8]
        masks = opaque[code]
        positions = [(x, rng.randrange(-15, 256)) for x in range(-15, 224) if full or x % 16 == 0 or rng.random() < 0.15]
        if full:
            positions = [(x, y) for x in (-15, -1, 0, 5, 15, 16, 100, 207, 208, 223) for y in range(-15, 256)]
        elif code % 25 == 0:
            positions += [(x, y) for x in (-15, 0, 9, 223) for y in range(-15, 256, 7)]
        positions = [(x, y, None) for x, y in positions]
        for x in list(range(-15, 0)) + list(range(209, 224)):     # the edges: every shift, plain and across a 64 KB boundary
            positions.append((x, rng.randrange(-15, 256), False))
            positions.append((x, None, True))
        for x, y, cross in positions:
            idx, T = rng.randrange(3), rng.choice((0, 1, 124, 255, 256, 300, 511))
            if cross is not None:
                rb = mem.r32(sym["ring_base"] + 4 * idx)
                ok = []
                for yy in range(-15, 256):
                    inner = rb + (T + yy) * 256 + 24 + (0 if x < 0 else 13 * 8)
                    over = (inner & 0xffff) + 15 * 256 > 0xffff           # the part's lines cross a 64 KB boundary
                    if over == cross:
                        ok.append(yy)
                if not ok:
                    continue
                y = rng.choice(ok)
                if cross:
                    crossing_edge[0] += 1
            mem.w16(sym["cur_T"], T)
            mem.w16(sym["draw_idx"], idx)
            ring = mem.r32(sym["ring_base"] + 4 * idx) + T * 256
            line0 = ring + (y - 1) * 256            # (a line above and below the part check for stray writes)
            seed = bytes(rng.getrandbits(8) for _ in range(18 * 256))
            expected = bytearray(seed)
            shift, column = x & 15, x >> 4
            for row in range(16):
                mask = int(masks[row])
                for plane in range(4):
                    word = int.from_bytes(natural[row * 8 + plane * 2:row * 8 + plane * 2 + 2], "big")
                    for chunk in range(1 if shift == 0 else 2):
                        if not 0 <= column + chunk < 14:      # (a margin chunk: untouched)
                            continue
                        amount = -shift if chunk == 0 else 16 - shift
                        m = (mask >> -amount if amount < 0 else mask << amount) & 65535
                        v = (word >> -amount if amount < 0 else word << amount) & 65535
                        off = (row + 1) * 256 + 24 + (column + chunk) * 8 + plane * 2
                        old = int.from_bytes(expected[off:off + 2], "big")
                        expected[off:off + 2] = ((old & ~m) | (v & m)).to_bytes(2, "big")
            mem.w_block(line0, seed)
            if rng.random() < 0.02:                  # (the part is baked again inside draw_part)
                mem.w32(sym["spr_ptr"] + 4 * ((code << 4) | col), 0)
            mem.w16(sym["spr_pcode"], code)
            mem.w16(sym["spr_col"], col)
            mem.w16(sym["spr_xs"], x & 0xffff)
            mem.w16(sym["spr_ytop"], y & 0xffff)
            mem.w16(sym["rect_cnt"], 0)
            call("spr_begin")
            origin = ring + y * 256 + 24 + column * 8
            low = (origin + 0) & 0xffff
            crossing += low > 0xEFE0 and 0 <= x <= 208
            call("draw_edge" if (x < 0 or x > 208) and "draw_edge" in sym else "draw_part")
            call("spr_end")
            got = bytes(mem.r_block(line0, len(seed)))
            if got != bytes(expected):
                bad = [i for i in range(len(seed)) if got[i] != expected[i]]
                print("FAIL code %d x %d y %d low %04x: %d bytes differ, first %s" % (code, x, y, low, len(bad), bad[:6]))
                return 1
            mem.w_block(clean + (T + y - 1) * 256, seed)
            call("rf_spr_restore")
            if bytes(mem.r_block(line0, len(seed))) != seed:
                got = bytes(mem.r_block(line0, len(seed)))
                bad = [i for i in range(len(seed)) if got[i] != seed[i]]
                print("FAIL restore code %d x %d y %d ring %d T %d: %d bytes, first %s" %
                      (code, x, y, idx, T, len(bad), bad[:12]))
                return 1
            checks += 1
            edges += x < 0 or x > 208
    print("%d part draws and restores passed (%d sprite codes, every shift; %d across the left or right edge, margins untouched, %d of them "
          "across a 64 KB boundary; %d inner parts at a 64 KB boundary)" % (checks, len(codes), edges, crossing_edge[0], crossing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
