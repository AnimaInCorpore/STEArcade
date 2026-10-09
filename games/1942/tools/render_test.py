"""The STE renderer (render_frame of 1942.PRG built with --sim, on Musashi with the Blitter model) against the reference renderer
through the palette map: the reference runs in the port's schedule, after every frame its video RAM, sprite RAM, scroll and palette
bank go into the 68000's Z80 block and render_frame draws; the 224 x 256 pixels the Shifter would show (the draw ring from
the window's top line) must be the oracle's picture.

    python render_test.py [frames] [step] [first]    frames drawn, one in `step` reference frames, starting at frame `first`
    python render_test.py seq 300 1 1200               consecutive frames (exercises the restore / overlay logic across frames)
"""
import os, random, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from machine68k import Register as R
from sim import Sim
from machine import Machine1942, save_png
import logic_test as lt
from assets import Oracle

RUN, MAP = lt.RUN, lt.MAP
if os.environ.get("ATTRACT"):                   # no coin: the attract mode only
    lt.inputs = lambda f, rnd: (0xFF, 0xFF, 0xFF)


def window(mem, base, top):
    """The picture of 256 lines from ring address `base` + top line: [256][224] colour indices"""
    out = np.zeros((256, 224), np.uint8)
    raw = np.frombuffer(bytes(mem.r_block(base + top * 256, 256 * 256)), np.uint8).reshape(256, 256)
    area = raw[:, 24:24 + 112].reshape(256, 14, 4, 2)
    words = (area[..., 0].astype(np.uint16) << 8) | area[..., 1]          # [line][chunk][plane]
    for k in range(4):
        w = words[:, :, k]
        for b in range(16):
            out[:, b::16] |= (((w >> (15 - b)) & 1).astype(np.uint8) << k)
    return out


def main():
    a = sys.argv[1:]
    seq = bool(a) and a[0] == "seq"
    if seq:
        a = a[1:]
    frames = int(a[0]) if a else 20
    step = int(a[1]) if len(a) > 1 else (1 if seq else 100)
    first = int(a[2]) if len(a) > 2 else (1200 if seq else 300)
    s = Sim(str(RUN / "1942.PRG"), ram_kib=16384, run_dir=RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    s.bad = sym["z80_badpc"]
    mem, cpu = s.mem, s.cpu
    block = sym["g_block"]
    z = lambda addr: block + addr - 0x8000
    ret = sym["sim_render_ret"]
    if lt.run_to(s, {sym["sim_wait"]}) is None:
        print("the boot failed")
        return
    ref = Machine1942()
    ref.run_to_idle()
    ref.booted = True
    oracle = Oracle()
    rnd = random.Random(1)
    last = {}
    bad = 0
    drawn = 0
    f = 0
    cyc = []
    while drawn < frames:
        ref.sys_in, ref.p1, ref.p2 = lt.inputs(f, rnd)
        ref.run_frame_port()
        f += 1
        if f < first or (not seq and (f - first) % step):
            continue
        if os.environ.get("SCROLLRND"):             # the window jumps: every sign and size of the move between two visits of a ring
            ref.scroll[0], ref.scroll[1] = rnd.randrange(256), rnd.randrange(2)
        # the video state into the sim
        mem.w_block(z(0xCC00), bytes(ref.sprram))
        mem.w_block(z(0xD000), bytes(ref.fg))
        mem.w_block(z(0xD800), bytes(ref.bg))
        mem.w8(z(0xC802), ref.scroll[0])
        mem.w8(z(0xC803), ref.scroll[1])
        mem.w8(z(0xC805), ref.palette_bank)
        # (the harness stands in for the translated code that sets the dirty flags: when the RAM changed since the last frame)
        if bytes(ref.fg) != last.get("fg"):
            mem.w8(sym["fg_dirty"], 1)
        if bytes(ref.bg) != last.get("bg"):
            mem.w8(sym["bg_dirty"], 1)
        last["fg"], last["bg"] = bytes(ref.fg), bytes(ref.bg)
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, ret)
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym["render_frame"])
        mem.set_trace_mode(True)
        c0 = lt.CYCLES[0]
        got = lt.run_to(s, {ret})
        mem.set_trace_mode(False)
        if got is None:
            lt.name_of(sym, cpu.r_pc())
            print("render_frame stopped at %06X (%s)" % (cpu.r_pc(), lt.name_of(sym, cpu.r_pc())))
            print("  d0-d7", " ".join("%08X" % cpu.r_reg(r) for r in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6, R.D7)))
            print("  a0-a7", " ".join("%08X" % cpu.r_reg(r) for r in (R.A0, R.A1, R.A2, R.A3, R.A4, R.A5, R.A6, R.A7)))
            return
        cpu.w_reg(R.A7, sp + 4)
        draw_idx = mem.r16(sym["draw_idx"])         # (render_frame picks the ring: not the shown one, not the one that waits)
        ring = mem.r32(sym["ring_base"] + 4 * draw_idx)
        assert draw_idx not in (mem.r16(sym["shown_idx"]), mem.r16(sym["prev_idx"])), "drew into a ring that is (or was) shown"
        mem.w16(sym["prev_idx"], mem.r16(sym["shown_idx"]))
        if f % 4 != 3:                              # the VBL shows the frame (one in four is not shown before the next is done: dropped)
            mem.w16(sym["shown_idx"], mem.r8(sym["frame_ready"]) - 1)
            mem.w8(sym["frame_ready"], 0)
        cyc.append(lt.CYCLES[0] - c0)
        flip = mem.r32(sym["flip_addr"])
        top = mem.r16(sym["cur_T"])               # (the display starts PIC_TOP lines above it, in black)
        assert (flip - ring) // 256 == top - 10, "display address"
        mine = window(mem, ring, top)
        want = oracle.frame(ref)
        diff = np.argwhere(mine != want)
        drawn += 1
        if len(diff):
            bad += 1
            print("frame %d: %d pixels differ (T %d, bank %d), first (y, x): %s" % (f, len(diff), top, ref.palette_bank,
                                                                                [tuple(map(int, d)) for d in diff[:6]]))
            pal = oracle.pal["rgb"][ref.palette_bank]
            pa = np.array(pal, np.uint8)
            img = np.concatenate([pa[mine], pa[want], np.where((mine != want)[..., None], np.array([255, 0, 255], np.uint8), pa[want])], axis=1)
            save_png(img, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "build", "render_diff_%d.png" % f), 1)
            if bad >= 3:
                break
        else:
            print("frame %d ok (T %d, bank %d, %d cycles)" % (f, top, ref.palette_bank, cyc[-1]), flush=True)
    print("drawn %d frames, %d differ" % (drawn, bad))
    if cyc:
        c = sorted(cyc)
        print("render_frame: mean %d cycles, max %d; median %d, 90%% %d, 99%% %d; %d frames over 100k" % (
            sum(cyc) // len(cyc), max(cyc), c[len(c) // 2], c[len(c) * 9 // 10], c[len(c) * 99 // 100], sum(1 for v in cyc if v > 100000)))


if __name__ == "__main__":
    main()
