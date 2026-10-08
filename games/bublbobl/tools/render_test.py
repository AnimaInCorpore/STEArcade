"""The 68000 renderer (BUBBLE.PRG built with --sim, on Musashi) against the reference renderer.

The game runs on the 68000 to the idle loop, then the reference is advanced to frame N, its video RAM,
object RAM and palette RAM are copied in and render_frame is called; the screen buffer is decoded and
compared with the reference's bitmap mapped through the renderer's colour table.

    python render_test.py [frame ...]         (default: some frames of the attract mode and play)
"""
import os, sys
from pathlib import Path
import numpy as np
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim
from machine68k import Register as R
from machine import Bublbobl
import logic_test as lt

RUN = lt.RUN


def decode_screen(mem, base, lines0, nlines):
    """[nlines][256] STE colour indices of the game area: game row y at buffer line y + YPAD."""
    raw = np.frombuffer(bytes(mem.r_block(base, 160 * 280)), np.uint8).reshape(280, 160)
    out = np.zeros((nlines, 256), np.uint8)
    for yy in range(nlines):
        line = raw[lines0 + yy]
        for g in range(16):
            for p in range(4):
                w = (int(line[16 + g * 8 + p * 2]) << 8) | int(line[16 + g * 8 + p * 2 + 1])
                for b in range(16):
                    out[yy, g * 16 + b] |= ((w >> (15 - b)) & 1) << p
    return out


def inputs_upto(ref, f):
    i0, i1, i2 = lt.inputs(f)
    ref.in0, ref.in1, ref.in2 = i0, i1, i2


def main():
    args = sys.argv[1:]
    if args and args[0] == "seq":                  # consecutive frames: the incremental path
        frames = list(range(int(args[1]), int(args[1]) + int(args[2])))
    else:
        frames = [int(a) for a in args] or [100, 300, 420, 600, 700]
    s = Sim(str(RUN / "BUBBLE.PRG"), run_dir=RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(lt.MAP).items()}
    s.bad = sym["z80_badpc"]
    cpu, mem = s.cpu, s.mem
    stop = sym["sim_frame_done"]
    # to the idle loop
    while True:
        if not lt.run_to(s, stop):
            print("68000 stopped before the idle loop")
            return
        b = mem.r8(sym["booted1"])
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
        if b:
            break
    ref = Bublbobl()
    g_ram = sym["g_block"] + 0x8000
    f = 0
    for target in frames:
        while f <= target:
            inputs_upto(ref, f)
            ref.run_frame_port()
            f += 1
        # the reference state into the 68000's memory
        mem.w_block(g_ram + 0x4000, bytes(ref.vram))
        mem.w_block(g_ram + 0x5D00, bytes(ref.oram))
        mem.w_block(g_ram + 0x7800, bytes(ref.pal))
        # call render_frame
        sp = 0x3FF000
        cpu.w_reg(R.A7, sp - 4)
        mem.w32(sp - 4, stop)
        cpu.w_sr(0x2700)
        cpu.w_pc(sym["render_frame"])
        n = 0
        while cpu.r_pc() != stop:
            r = cpu.execute(20000)
            n += r.cycles
            if n > 400_000_000:
                print("render_frame does not return, pc %06X" % cpu.r_pc())
                return
        scr = mem.r32(sym["draw_screen_address"])
        swap_screens = lambda: (mem.w32(sym["draw_screen_address"], mem.r32(sym["display_screen_address"])), mem.w32(sym["display_screen_address"], scr))   # the VBL swaps after a render
        got = decode_screen(mem, scr, 10 + 16, 224)
        ttab = bytes(mem.r_block(sym["ttab"], 256))
        raw = ref.render_raw()                                 # [224][256] palette indices, 255 = background
        exp = np.array([ttab[v] if v != 255 else 0 for v in raw.ravel()], np.uint8).reshape(224, 256)
        diff = got != exp
        nd = int(diff.sum())
        print("frame %d: %d of %d pixels differ (cycles %d)" % (target, nd, diff.size, n))
        if len(frames) <= 8:
            check_cache(mem, sym)
            check_slots(s, ref, sym)
        if nd:
            ys, xs = np.nonzero(diff)
            print("   first:", [(int(x), int(y), int(got[y, x]), int(exp[y, x])) for x, y in zip(xs[:6], ys[:6])])
            cells = sorted({(int(x) // 8, int(y) // 8) for x, y in zip(xs, ys)})
            print("   %d differing cells, e.g. %s" % (len(cells), cells[:12]))
            from collections import Counter
            print("   differing cells per column:", sorted(Counter(c[0] for c in cells).items()))
            cx, cy = cells[1]
            print("   cell", cx, cy, "got / expected:")
            for r in range(8):
                print("     ", "".join("%x" % got[cy * 8 + r, cx * 8 + c] for c in range(8)), "  ", "".join("%x" % exp[cy * 8 + r, cx * 8 + c] for c in range(8)))
        if len(frames) <= 8 or nd:
            from machine import save_png
            pal = ste_palette(mem, sym)
            save_png(np.hstack([pal[got], ref.render_rgb()]), "/tmp/bbr_cmp_%d.png" % target, 1)
            save_png(pal[got], "/tmp/bbr_got_%d.png" % target, 2)
            save_png(pal[exp], "/tmp/bbr_exp_%d.png" % target, 2)
        if nd and len(frames) > 8:
            return
        swap_screens()


def check_cache(mem, sym):
    """every baked tile against a Python bake with the renderer's colour table"""
    from machine import decode_tiles
    global _tiles
    try:
        _tiles
    except NameError:
        _tiles = decode_tiles()
    ttab = bytes(mem.r_block(sym["ttab"], 256))
    raw = bytes(mem.r_block(sym["tcache"], 4096 * 72))
    bad = good = 0
    for slot in range(4096):
        e = raw[slot * 72:(slot + 1) * 72]
        key = int.from_bytes(e[0:4], "big")
        if key == 0xFFFFFFFF:
            continue
        code, bank, fx, fy = key & 0x3FFF, (key >> 14) & 15, (key >> 18) & 1, (key >> 19) & 1
        t = _tiles[code]
        if fy: t = t[::-1]
        if fx: t = t[:, ::-1]
        ok = True
        opaque = int.from_bytes(e[4:8], "big")
        for r in range(8):
            data = int.from_bytes(e[8 + r * 8:12 + r * 8], "big")
            nmask = int.from_bytes(e[12 + r * 8:16 + r * 8], "big")
            planes = [0, 0, 0, 0]; m = 0
            for x in range(8):
                pen = int(t[r, x])
                idx = 0 if pen == 15 else ttab[bank * 16 + pen]
                for k in range(4):
                    planes[k] |= ((idx >> k) & 1) << (7 - x)
                if pen == 15: m |= 1 << (7 - x)
            want = (planes[0] << 24) | (planes[1] << 16) | (planes[2] << 8) | planes[3]
            wmask = m * 0x01010101
            if data != want or nmask != wmask:
                ok = False
                if bad < 3:
                    print("   bad bake: tile %d bank %d fx %d fy %d row %d: data %08X want %08X mask %08X want %08X" % (code, bank, fx, fy, r, data, want, nmask, wmask))
                break
        if ok: good += 1
        else: bad += 1
    print("   cache: %d entries ok, %d bad" % (good, bad))


def py_slots(oram, prom, i, sx):
    """the reference's tile slots of object i (x, y, vram offset) and the x after it"""
    e = oram[i * 4:i * 4 + 4]
    y0, num, xr, attr = e
    pl = (num & 0xE0) >> 1
    go = (num & 0x1F) * 0x80
    if (num & 0xA0) == 0xA0:
        go |= 0x1000
    sy = (-y0) & 0xFF
    out = []
    for yc in range(32):
        p = prom[pl + yc // 2]
        if p & 8:
            continue
        if not p & 4:
            sx = xr - (256 if attr & 0x40 else 0)
        for xc in range(2):
            out.append((sx + xc * 8, (sy + yc * 8) & 0xFF, go + xc * 0x40 + (yc & 7) * 2 + (p & 3) * 0x10))
    return out, sx


def check_slots(s, ref, sym):
    from machine import load
    prom = load("a71-25.41")[0x80:0x100]
    cpu, mem = s.cpu, s.mem
    g_ram = sym["g_block"] + 0x8000
    oram = bytes(ref.oram)
    sx = 0
    bad = 0
    n = 0
    for i in range(192):
        if oram[i * 4:i * 4 + 4] == b"\0\0\0\0":
            continue
        want, sx_end = py_slots(oram, prom, i, sx)
        sp = 0x3FF000
        cpu.w_reg(R.A7, sp - 4)
        mem.w32(sp - 4, sym["sim_frame_done"])
        cpu.w_reg(R.A4, g_ram + 0x5D00 + 4 * i)
        cpu.w_reg(R.A5, 0x3F0000)
        cpu.w_reg(R.D7, sx & 0xFFFF)
        cpu.w_sr(0x2700)
        cpu.w_pc(sym["obj_slots"])
        while cpu.r_pc() != sym["sim_frame_done"]:
            cpu.execute(2000)
        cnt = cpu.r_reg(R.D0) & 0xFFFF
        got_end = cpu.r_reg(R.D7) & 0xFFFF
        got = []
        for k in range(cnt):
            x = mem.r16(0x3F0000 + 10 * k); y = mem.r16(0x3F0000 + 10 * k + 2); v = mem.r16(0x3F0000 + 10 * k + 4)
            got.append((x - 65536 if x & 0x8000 else x, y, v))
        w16 = [((x + 32768) % 65536 - 32768, y, v) for (x, y, v) in want]
        n += 1
        if got != w16 or got_end != (sx_end & 0xFFFF):
            bad += 1
            if bad <= 3:
                print("   object %d slots differ: got %d slots, want %d; end %04X want %04X; first got %s want %s" % (
                    i, len(got), len(w16), got_end, sx_end & 0xFFFF, got[:3], w16[:3]))
        sx = sx_end + 16
    print("   slots: %d objects, %d differ" % (n, bad))


def ste_palette(mem, sym):
    out = []
    for i in range(16):
        w = mem.r16(sym["ste_pal"] + 2 * i)
        f = lambda n: (((n & 7) << 1) | (n >> 3)) * 17
        out.append((f((w >> 8) & 15), f((w >> 4) & 15), f(w & 15)))
    return np.array(out, np.uint8)


if __name__ == "__main__":
    main()
