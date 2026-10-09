"""The STE renderer (sim build) against the reference picture through the 16 colour map, pixel by pixel.

    python render_test.py [frames] [mode] [--seed N] [--first F]

modes: seq (consecutive frames from --first: incremental scrolling, damage restore, text list), samples (every 97th
frame), scroll (D802 and S jumps over their whole range: full redraws and wraps), edges (a sprite at each edge of the
window: drawn whole into the guard lines above and below, its pixels checked there; at the sides the screen shows the
margin, which must stay black).  Seeds as ref/cover.py (4-14: MAME's cheats, a
round each).  The reference state (text RAM, scroll, latches, sprite latch) is copied into the 68000's memory and
render_frame is called; the window of the drawn buffer is compared.
"""
from pathlib import Path
import argparse
import json
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
import numpy as np
from PIL import Image
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import GunSmoke
from paths import ROOT, build_dir
import cover

BUILD = build_dir('gunsmoke')


def planar(mem, base, lines, first_byte, chunks):
    raw = np.frombuffer(bytes(mem.r_block(base, lines * 256)), np.uint8).reshape(lines, 256)
    area = raw[:, first_byte:first_byte + chunks * 8].reshape(lines, chunks, 4, 2)
    words = (area[..., 0].astype(np.uint16) << 8) | area[..., 1]
    out = np.zeros((lines, chunks * 16), np.uint8)
    for k in range(4):
        for b in range(16):
            out[:, b::16] |= ((words[:, :, k] >> (15 - b)) & 1).astype(np.uint8) << k
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=20)
    ap.add_argument('mode', nargs='?', default='samples', choices=['seq', 'samples', 'scroll', 'edges'])
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--first', type=int, default=900)
    args = ap.parse_args()
    run = ROOT / 'run' / 'gunsmoke_sim'
    s = Sim(str(run / 'GUNSMOKE.PRG'), ram_kib=16384, run_dir=run)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(BUILD / 'gunsmoke_sim.map').items()}
    mem.set_trace_mode(False)
    ret, bad = sym['sim_render_ret'], sym['z80_badpc']
    a6 = sym['g_block'] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    def run_to(target):
        cycles = 0
        while cycles < 400_000_000:
            cycles += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc == target:
                return cycles
            if pc in (bad, bad + 4) or s.terminated:
                raise RuntimeError(f'CPU stopped at {pc - s.base:06x}')
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError(f'CPU timeout {cpu.r_pc() - s.base:06x}')

    word = mem.r16(sym['render_frame'])
    mem.w16(sym['render_frame'], 0x4e75)
    run_to(sym['sim_wait'])
    mem.w16(sym['render_frame'], word)
    m = GunSmoke()
    if args.seed >= 4:
        rom = bytearray(m.rom)
        rom[0x100b] = rom[0x15f9] = 0xc9
        rom[0x08c6:0x08c8] = cover.ROUNDS[min(args.seed - 4, len(cover.ROUNDS) - 1)].to_bytes(2, 'little')
        m.rom = bytes(rom)
    rnd = random.Random(args.seed)
    state = {}
    palette = json.loads((Path(__file__).resolve().parents[1] / 'docs' / 'palette.json').read_text())
    mapping = np.array(palette['map'], np.uint8)
    rgb = np.array(palette['rgb'], np.uint8)
    from video import Video
    video = Video()
    costs = []
    for sample in range(args.frames):
        target = args.first + sample if args.mode == 'seq' else args.first + sample * 97
        while m.frame < target:
            m.inputs[0], m.inputs[1] = cover.inputs(m.frame, rnd, state)
            if args.seed >= 4:
                m.mem[0xe040] = 6
                if m.frame % 300 == 0:
                    m.mem[0xf790] = 1
            m.run_frame_port()
        if args.mode == 'scroll':
            m.mem[0xd800] = (sample * 7919) & 255
            m.mem[0xd801] = (sample * 31337 >> 8) & 255
            m.mem[0xd802] = (sample * 37) & 255
        sprites = bytes(b for off in range(0, 4096, 32) for b in m.sprites[off:off + 4])
        edge = None
        if args.mode == 'edges':
            empty = next(i for i in range(1024) if not video.chars[i].any() or
                         all(video.lookup[p] == 0x4f for p in np.unique(video.chars[i])))
            m.mem[0xd000:0xd400] = bytes([empty & 255]) * 1024
            m.mem[0xd400:0xd800] = bytes([0]) * 1024
            code = next(i for i in range(2048) if np.count_nonzero(video.sprites[i]) > 128)
            edge_x, edge_y = [(216, 128), (-8, 128), (100, -8), (100, 248)][sample % 4]
            raw_x = 240 - edge_y
            attr = (code >> 8) << 6 | (32 if raw_x < 0 else 0) | 3
            sprites = bytes([code & 255, attr, edge_x + 16, raw_x & 255]) + bytes([0, 0, 0, 0]) * 127
            m.sprites[:] = bytes(4096)
            m.sprites[0:4] = sprites[:4]
            m.layers |= 32
            edge = (code, edge_x, edge_y)
        mem.w_block(addr(0xd000), bytes(m.mem[0xd000:0xd803]))
        mem.w8(addr(0xc804), m.control)
        mem.w8(addr(0xd806), m.layers)
        mem.w8(sym['fg_written'], 1)
        mem.w_block(sym['sprite_buffer'], sprites)
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, ret)
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym['render_frame'])
        mem.set_trace_mode(True)
        cost = run_to(ret)
        mem.set_trace_mode(False)
        idx = mem.r16(sym['draw_idx'])
        base = mem.r32(sym['draw_base'])
        wx = mem.r16(sym['cur_wx'])                 # the window's first pixel on the buffer's lines (48 + the hardware offset)
        full = planar(mem, base, 256, 0, 32)
        mine = full[:, wx:wx + 224]
        want = mapping[video.render_raw(m)[16:240].T[::-1]]
        if edge:
            code, edge_x, edge_y = edge
            got = planar(mem, base + edge_y * 256, 16, 0, 32)[:, wx + edge_x:wx + edge_x + 16]
            shape = video.sprites[code].T[::-1]
            opaque = shape != 0
            if edge_y in (-8, 248):             # (above / below the window: the whole sprite is in the guard lines)
                assert np.array_equal(got[opaque], mapping[384 + 3 * 16 + shape.astype(int)][opaque]),                     'the whole sprite was clipped'
        # the side bars (the 48 pixels on each side of the window that the screen shows) must stay black
        if full[:, wx - 48:wx].any() or full[:, wx + 224:wx + 272].any():
            where = np.argwhere(np.hstack((full[:, wx - 48:wx], full[:, wx + 224:wx + 272])))
            raise RuntimeError(f'frame {target}: colour beside the window at (line, x of the 96 side pixels) '
                               f'{where[:4].tolist()} .. {where[-2:].tolist()}, {len(where)} pixels')
        diff = np.count_nonzero(mine != want)
        if diff:
            out = BUILD / f'render_diff_{target}.png'
            Image.fromarray(np.hstack((rgb[mine], rgb[want], (mine != want).astype(np.uint8)[..., None].repeat(3, 2) * 255))).save(out)
            positions = np.argwhere(mine != want)[:10]
            raise RuntimeError(f'{diff} pixels differ at frame {target}, scroll {m.mem[0xd800:0xd803].hex()}, '
                               f'first {positions.tolist()}; {out}')
        mem.w16(sym['prev_idx'], mem.r16(sym['shown_idx']))
        mem.w16(sym['shown_idx'], idx)
        mem.w8(sym['frame_ready'], 0)
        costs.append(cost + s.blitter.cycles)
        s.blitter.cycles = 0
        print(f'frame {target}: exact, CPU + Blitter {costs[-1]} cycles, cache misses {mem.r32(sym["cache_misses"])}',
              flush=True)
    print(f'PASS: {args.frames} {args.mode} frames (seed {args.seed}); CPU + Blitter median {int(np.median(costs))} cycles')


if __name__ == '__main__':
    main()
