"""Sprites at the picture's left and right edges: all 16 fine scrolls and shifts, transparent holes, 64 KB crossings,
both orientations, consecutive frames (the rings' restores of the last frames' sprites).

render_frame runs on Musashi (render_test.Renderer).  The 320-pixel hardware window is checked whole: the 256-pixel
game picture against the reference, and the side bands.  The window's words 0, 1 and 19, 20 are always black: a
sprite across the 16-pixel group boundary of words 1|2 or 18|19 draws only its inner word, so they stay black.  The
game's own edge lies at word 2 (18) + the fine scroll, not group-aligned: the band part of words 2 and 18 shows the
whole sprite, black elsewhere, with the front pens only in the picture.  First with the background and the text off
(the picture is the sprites alone), then with both on and two more frames of the same window without sprites (the
rings' restores of the rectangles over words 2 and 18); the window moves 15-16 pixels and the rows 37 pixels or more a
frame.  Then a random walk: the camera moves 0-3 pixels a frame both ways or jumps, up to 16 sprites anywhere (the
edges favoured, all colours), the orientation changes every 100 frames.  The last frames have no sprites: the bands
black again.  Every band pixel is checked (render_test.py checks the words 0, 1, 19 and 20 black in its frames too).

    python sprite_test.py [frame] [--whole] [--keep] [--walk=N] [-v]   (frame: the reference's frame to start from, default 375;
                                                    --whole: expect the old whole sprites in the bands; --keep: on after a mismatch;
                                                    --walk=N: the random walk's frames, default 400;
                                                    -v: pixels)
"""
import sys
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from render_test import Renderer
from machine import BlackTiger
from assets import Oracle
from logic_test import inputs


def window(r):
    """The hardware window (320 pixels, 224 lines) of the frame just drawn, as STE pens; and its first word's address."""
    mem, sym = r.mem, r.sym
    base = mem.r32(sym['work_base'])
    y = mem.r16(sym['physical_y']) + 16
    x = mem.r16(sym['physical_x']) + 64
    raw = np.frombuffer(bytes(mem.r_block(base + y * 384, 224 * 384)), np.uint8).reshape(224, 48, 4, 2)
    words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
    pixels = np.zeros((224, 768), np.uint8)
    for plane in range(4):
        for bit in range(16):
            pixels[:, bit::16] |= (((words[:, :, plane] >> (15 - bit)) & 1).astype(np.uint8) << plane)
    return pixels[:, x - 32:x + 288], base + y * 384


def pick_codes(gfx):
    """Sprites with transparent holes inside opaque rows (a gap between opaque pixels) and both halves opaque."""
    codes = []
    for code in range(len(gfx.sprites)):
        p = gfx.sprites[code]
        o = p != 15
        if not 60 < o.sum() < 200 or not o[:, :8].any() or not o[:, 8:].any():
            continue
        holes = sum(1 for row in o if row.any() and not row[np.argmax(row):16 - np.argmax(row[::-1])].all())
        if holes >= 3:
            codes.append(code)
        if len(codes) == 2:
            break
    return codes


def main():
    first = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 375
    r = Renderer()
    r.no_band_check = True               # (checked here, with the whole sprites in words 2 and 18)
    ref = BlackTiger()
    oracle = Oracle()
    for frame in range(first + 1):
        ref.inputs[:3] = inputs(frame)
        ref.run_frame_port()
    r.render(ref)
    vals = np.frombuffer(ref.mem, np.uint8)
    pal = vals[0xd800:0xdc00].astype(np.uint16) | vals[0xdc00:0xe000].astype(np.uint16) << 8
    ref.render_raw()
    gfx = ref.gfx
    codes = pick_codes(gfx)
    assert codes, 'no sprite with holes'
    cases = clipped = crossings = failed = 0
    frames = 0
    video, control = ref.video_enable, ref.control
    for background, flip in ((0, 0), (0, 64), (1, 0), (1, 64)):
        ref.video_enable = video if background else video | 2
        ref.control = ((control if background else control | 128) & ~64) | flip
        for k, code in enumerate(codes):
            for f in (range(16) if k % 2 == 0 else range(15, -1, -1)):   # (the camera moves 16 pixels at most a frame)
                for half in (0, 1):
                    # rows of sprites: row i has one at the left edge and one at the right edge
                    xs = [(-15 + 8 * half + i, 240 + 8 * half + i) for i in range(8)]
                    sy = 3 + 64 * half + 37 * f + (code & 7) * 11 + (flip >> 2)    # (screen scroll y: the rows' addresses vary)
                    px = 64 + f + 16 * half              # (the window's words move every frame)
                    ref.scroll[:] = bytes([(-px if flip else px) & 255, 0, sy & 255, 0])
                    ref.sprites[:] = bytes(512)
                    placed = []         # (screen x, screen y, pixels as seen)
                    n = 0
                    for i, pair in enumerate(xs):
                        ys = 16 + 16 * i + 8 * half
                        for xs_ in pair:
                            if xs_ > 255:
                                continue
                            hf = 8 if (n & 1) else 0
                            ax, ay = (240 - xs_, 240 - ys) if flip else (xs_, ys)
                            attr = (0x10 if ax < 0 else 0) | hf
                            ref.sprites[4 * n:4 * n + 4] = bytes([code & 255, attr | ((code >> 3) & 0xe0), ay & 255, ax & 255])
                            seen = gfx.sprites[code]
                            if hf:
                                seen = seen[:, ::-1]
                            if flip:
                                seen = seen[::-1, ::-1]
                            placed.append((xs_, ys, seen, 0))
                            n += 1
                    stills = 2 if background else 0      # (then the same window without sprites: the rings' restores)
                    for still in range(stills + 1):
                        if still:
                            ref.sprites[:] = bytes(512)
                            placed = []
                        mine_win, top = render(r, ref)
                        frames += 1
                        fs = r.mem.r16(r.sym['physical_x']) & 15
                        assert fs == f, (fs, f)
                        want = expect(oracle, ref, pal, placed, f)
                        for xs_, ys, seen, _ in placed:
                            if xs_ + f < 0 or (xs_ + f > 256 and (xs_ + f) & 15):
                                clipped += 1
                                line0 = top + (ys - 16) * 384
                                if (line0 >> 16) != ((line0 + 15 * 384) >> 16):
                                    crossings += 1
                            cases += 1
                        if not np.array_equal(mine_win, want):
                            d = np.argwhere(mine_win != want)
                            print('mismatch: background', background, 'flip', flip, 'code', code, 'fine', f, 'half', half,
                                  'still', still, 'pixels', len(d), 'first', d[:6].tolist(), 'columns', sorted(set(d[:, 1].tolist()))[:24])
                            if '-v' in sys.argv:
                                np.set_printoptions(linewidth=250)
                                rows = sorted(set(d[:, 0].tolist()))
                                print('rows', rows[:5], rows[-5:]); y0 = rows[0]
                                print(mine_win[y0:y0 + 3, :64]); print(want[y0:y0 + 3, :64])
                            failed += 1
                            if '--keep' not in sys.argv:
                                return 1
    # a random walk: the camera moves 0-3 pixels a frame both ways, or jumps; up to 16 sprites anywhere (edges
    # favoured), all colours; the orientation changes every 100 frames
    rng = np.random.default_rng(7)
    sx, sy = 64, 40
    ref.video_enable, walk = video, 0
    allcodes = [c for c in range(len(gfx.sprites)) if (gfx.sprites[c] != 15).sum() > 20]
    for i in range(int(next((a[7:] for a in sys.argv if a.startswith('--walk=')), 400))):
        flip = 64 if (i // 100) % 2 else 0
        ref.control = (control & ~64) | flip
        if rng.random() < 0.08:
            sx, sy = int(rng.integers(0, 256)), int(rng.integers(0, 256))
        else:
            sx, sy = (sx + int(rng.integers(-3, 4))) & 255, (sy + int(rng.integers(-3, 4))) & 255
        ref.scroll[:] = bytes([(-sx if flip else sx) & 255, 0, (-sy if flip else sy) & 255, 0])
        ref.sprites[:] = bytes(512)
        placed = []
        for n in range(int(rng.integers(0, 17))):
            xs_ = int(rng.choice([rng.integers(-15, 16), rng.integers(225, 256), rng.integers(-15, 256)]))
            ys = int(rng.integers(1, 240))
            code = int(rng.choice(allcodes))
            colour, hf = int(rng.integers(0, 8)), 8 * int(rng.integers(0, 2))
            ax, ay = (240 - xs_, 240 - ys) if flip else (xs_, ys)
            if not 1 <= ay < 240:
                continue
            ref.sprites[4 * n:4 * n + 4] = bytes([code & 255, (0x10 if ax < 0 else 0) | hf | colour | ((code >> 3) & 0xe0),
                                                  ay & 255, ax & 255])
            seen = gfx.sprites[code][:, ::-1] if hf else gfx.sprites[code]
            placed.append((xs_, ys, seen[::-1, ::-1] if flip else seen, colour))
        mine_win, _ = render(r, ref)
        walk += 1
        f = r.mem.r16(r.sym['physical_x']) & 15
        want = expect(oracle, ref, pal, placed[::-1], f)      # (entry 0 drawn last: on top)
        if not np.array_equal(mine_win, want):
            d = np.argwhere(mine_win != want)
            print('mismatch: walk frame', i, 'flip', flip, 'scroll', sx, sy, 'pixels', len(d), 'first', d[:6].tolist(),
                  'columns', sorted(set(d[:, 1].tolist()))[:24])
            failed += 1
            if '--keep' not in sys.argv:
                return 1
    if failed:
        print(failed, 'frames differ')
        return 1
    # no sprites: the bands black again after the ring's restores
    ref.sprites[:] = bytes(512)
    for _ in range(2):
        mine_win, _ = render(r, ref)
        want = np.zeros((224, 320), np.uint8)
        want[:, 32:288] = oracle.frame(ref)
        assert np.array_equal(mine_win, want), 'bands not restored'
    print(f'{cases} edge sprites in {frames} frames ({clipped} clipped to the inner word, {crossings} across 64 KB; '
          f'{len(codes)} sprites with holes, 16 fine scrolls, all shifts, both orientations), then {walk} frames of a '
          f'random walk: exact, band words black')
    return 0


def expect(oracle, ref, pal, placed, f):
    """The window: black side bands, the reference's picture, and the whole sprites in the band parts of words 2 and 18
    (window pixels 32-f..31 and 288..303-f; placed in drawing order)."""
    want = np.zeros((224, 320), np.uint8)
    want[:, 32:288] = oracle.frame(ref)
    for xs_, ys, seen, colour in placed:
        mapped = oracle.mapping[pal[0x200 + colour * 16 + seen.astype(np.uint16)] & 4095]
        opaque = seen != 15
        for c in range(16):
            wx = 32 + xs_ + c
            band = (32 - f <= wx < 32) or (288 <= wx < 304 - f) or ('--whole' in sys.argv and 0 <= wx < 320 and not 32 <= wx < 288)
            if not band:
                continue
            for rr in range(16):
                ly = ys + rr - 16
                if 0 <= ly < 224 and opaque[rr, c]:
                    want[ly, wx] = mapped[rr, c]
    return want


def render(r, ref):
    r.render(ref)
    return window(r)


if __name__ == '__main__':
    sys.exit(main())
