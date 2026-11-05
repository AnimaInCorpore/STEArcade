"""Default checker palettes: recorded pictures and native sprite fallback edges.

    venv/bin/python games/rtype/tools/palette_test.py

Compares the 68000/Blitter output with independently phased model pixels. Includes
consecutive heavy-stage frames, tile flips, palette changes, cropped/reordered
sprite pieces, all shifts, holes, guard lines and 64 KB destination crossings.
"""
import argparse
import json
import pickle
import struct
import zlib
from pathlib import Path

import numpy as np

import stage_assets as SA
import stage_sprites as SS
from stage_test import Expected, Harness, LB, G

OUT = Path('build/rtype/palette_default_audit')


def state(record):
    return pickle.loads(zlib.decompress(record[1]))


def check(h, expected, st, label):
    h.put_state(st)
    cycles = h.frame()
    assert cycles is not None, (label, 'no free buffer')
    want = expected(st)
    got, _ = h.screen()
    if not all(b[4] for b in st['bands']):
        bad = np.count_nonzero(got != want)
        if bad:
            np.savez_compressed(OUT / 'failure.npz', got=got, want=want, phase=expected.model.phase,
                                pens=expected.pens, label=str(label))
        assert not bad, (label, int(bad), 'pixels differ')
    return sum(cycles)


def recorded():
    results = {}
    for name in ('1', '8', '3', 's2', 's4', 's5', 's6', 's7', 's8'):
        records = pickle.loads(Path(f'build/rtype/stage_states_{name}.pkl').read_bytes())
        indices = set(range(0, len(records), 31))
        if name == '3':
            indices.update(range(1180, 1320))  # enter scrolling-warship mode
            indices.update(range(2200, 2360))
        if name == 's7':
            indices.update(range(1500, 1700))
        h, expected = Harness(['PALETTE_TEST=1']), Expected()
        h.call('m72r_init')
        costs = []
        scenes = set()
        for index in sorted(indices):
            costs.append(check(h, expected, state(records[index]), (name, index)))
            scenes.add(expected.cur)
        results[name] = dict(pictures=len(costs), scenes=sorted(scenes),
                             mean_cycles=float(np.mean(costs[1:])),
                             sprite_cache_bakes=h.r32('st_nbake'))
        print(name, results[name], flush=True)
    return results


def edges():
    base = state(pickle.loads(Path('build/rtype/stage_states_3.pkl').read_bytes())[2200])
    md = Expected().model
    fgempty = np.flatnonzero(np.frombuffer(Path('build/rtype/stage_fgempty.bin').read_bytes(), np.uint8))[0]
    bgempty = np.flatnonzero(md.star)[0]
    base = dict(base)
    for key, code in [('fg', fgempty), ('bg', bgempty)]:
        ram = np.zeros((64, 64, 2), np.uint16)
        ram[:, :, 0] = code
        base[key] = ram.astype('<u2').tobytes()
    base['objs'] = bytes(0x400)
    base['objs_end'] = 0xC8
    rom = SS.load_regions('rtype')['main']
    # Choose a recorded definition with holes and an odd crop origin.
    best = None
    for bw, n in SS.definitions([str(Path('build/rtype/stage_states_3.pkl'))]):
        composed = SS.compose(md.video.sprites, SS.entries(rom, bw, n))
        if composed is None:
            continue
        img, ox, oy = composed
        if not 16 <= img.shape[1] <= 64 or img.shape[0] > 64:
            continue
        holes = np.count_nonzero((img == 0) & np.maximum.accumulate(img != 0, axis=1) &
                                np.maximum.accumulate((img != 0)[:, ::-1], axis=1)[:, ::-1])
        score = holes + 100 * ((ox + oy) & 1)
        if best is None or score > best[0]:
            best = score, bw, n, composed
    assert best is not None
    _, bw, n, (img, ox, oy) = best
    h, expected = Harness(['PALETTE_EDGE_TEST=1']), Expected()
    h.call('m72r_init')
    cases = 0
    for aligned in (True, False):
        scroll = -96 if aligned else -91
        empty = dict(base, bands=[(y0, y1, (scroll & 511, sx[1]), sy, off)
                                 for y0, y1, sx, sy, off in base['bands']])
        # Bring every display buffer to the same empty picture.
        for _ in range(4):
            check(h, expected, empty, 'empty')
        positions = [(120 + shift, 100) for shift in range(16)]
        positions += [(x, 60) for x in range(-img.shape[1] - 1, 3)]
        positions += [(x, 60) for x in range(318, 338)]
        positions += [(100, y) for y in (-img.shape[0], -15, -1, 239, 248, 255)]
        for b in range(3):
            addr = h.r32('st_bufs', 4 * b) + G * LB
            line = ((65536 - (addr & 65535)) % 65536) // LB
            positions += [(130 + b, line - 7)]
        for x, y in positions:
            objs = bytearray(0x400)
            objs[0xC0:0xC8] = struct.pack('>HBBhh', bw, n, 0, x + 352 - ox, 384 + oy - y)
            st = dict(empty, objs=bytes(objs))
            check(h, expected, st, ('edge', aligned, x, y))
            # Force the native miss path and compare with the same precoloured result.
            h.mem.w_block(h.sym['st_hash'], bytes(65536 * 16))
            h.call('st_dt2inv')
            check(h, expected, st, ('native bake', aligned, x, y))
            check(h, expected, empty, 'restore damage')
            cases += 1
    print('edges', cases, 'definition', hex(bw), 'crop', (ox, oy), 'shape', img.shape, flush=True)
    return dict(cases=cases, definition=bw, crop=[int(ox), int(oy)], shape=list(img.shape),
                forced_cache_bakes=h.r32('st_nbake'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-only', action='store_true', help='Capture actual simulator pictures for visual review')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    SA.ensure()
    if args.capture_only:
        captures()
        return
    scenes = SA.load_scenes()
    for _, _, _, spr, tile, hud, _, ded, _ in scenes:
        free = 16 - len(ded)
        assert np.max(spr >> 4) < free and np.max(spr & 15) < free
        assert np.max(tile >> 4) < free and np.max(tile & 15) < free
        assert np.array_equal(hud >> 4, hud & 15)
    results = dict(recorded=recorded(), scenes=len(scenes))
    (OUT / 'renderer_results.json').write_text(json.dumps(results, indent=2) + '\n')
    results['edges'] = edges()
    (OUT / 'renderer_results.json').write_text(json.dumps(results, indent=2) + '\n')
    print('PASS', flush=True)


def captures():
    from PIL import Image, ImageDraw, ImageFont
    from quantization_preview import ste_palette, rgb12
    oldpath = OUT / 'baseline/stage_scenes.bin'
    old = oldpath.read_bytes() if oldpath.exists() else None
    rom = SS.load_regions('rtype')['main']
    font_path = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
    font = ImageFont.truetype(str(font_path), 22) if font_path.exists() else ImageFont.load_default()
    for slug, name, frame in [('title', '1', 200), ('stage1', '8', 4200), ('warship', '3', 2200), ('stage7', 's7', 1600)]:
        records = pickle.loads(Path(f'build/rtype/stage_states_{name}.pkl').read_bytes())
        st = state(records[frame])
        h, expected = Harness(['PALETTE_CAPTURE=1']), Expected()
        h.call('m72r_init')
        check(h, expected, st, ('capture', slug))
        got, _ = h.screen()
        shown = h.r16('m72r_shown')
        pal = ste_palette(bytes(h.mem.r_block(h.sym['m72r_disp_pal'] + shown * 32, 32)))
        hpal = ste_palette(bytes(h.mem.r_block(h.sym['m72r_disp_hpal'] + shown * 32, 32)))
        current = pal[got]
        bar = any(b[0] == 240 for b in st['bands'])
        if bar:
            current[240:] = hpal[got[240:]]
        ref, _, _, _, _, _, _, ded, frz = expected.scenes[expected.cur]
        targets = np.frombuffer(st['recs'], np.uint8).copy()
        for row in range(16):
            if frz >> row & 1:
                targets[16 + row] = ref[row]
        colors = np.concatenate([SA.target_rgb(rom, int(row >= 16), target) for row, target in enumerate(targets)] +
                                [np.zeros((1, 3), np.uint8)])
        arcade = colors[expected.pens]
        labels, images = ['Arcade target colours'], [arcade]
        if old:
            data = old[2 + SA.SC_SIZE * expected.cur:]
            legacy_pal, legacy_hpal = ste_palette(data[16:48]), ste_palette(data[48:80])
            spm, tpm, hpm = np.frombuffer(data[80:80 + 3 * 4096], np.uint8).reshape(3, 256, 16)
            pidx = np.concatenate([spm[targets[r]] if r < 16 else tpm[targets[r]] for r in range(32)] + [np.zeros(1, np.uint8)])
            c12 = SA.pen_colours(dict(st, recs=bytes(targets)))
            for row, pen, idx in ded:
                pidx[row * 16 + pen] = idx
                legacy_pal[idx] = rgb12(c12[row * 16 + pen])
            previous = legacy_pal[pidx[expected.pens]]
            if bar:
                hidx = np.concatenate([np.zeros(256, np.uint8)] + [hpm[targets[r]] for r in range(16, 32)] + [np.zeros(1, np.uint8)])
                previous[240:] = legacy_hpal[hidx[expected.pens[240:]]]
            labels.append('Previous default'); images.append(previous)
        labels.append('New default — native renderer'); images.append(current)
        panel = Image.new('RGB', (640 * len(images), 562), '#161d26')
        draw = ImageDraw.Draw(panel)
        for k, (label, pixels) in enumerate(zip(labels, images)):
            draw.text((640 * k + 12, 12), label, font=font, fill='white')
            panel.paste(Image.fromarray(pixels).resize((640, 512), Image.Resampling.NEAREST), (640 * k, 50))
        panel.save(OUT / (slug + '_default_comparison.png'))
        Image.fromarray(current).save(OUT / (slug + '_default.png'))
        print('captured', slug, 'scene', expected.cur, flush=True)
    cards = ''.join(f'<h2>{name}</h2><img src="{slug}_default_comparison.png">' for slug, name in
                    [('title', 'Title'), ('stage1', 'Stage 1 middle section'), ('warship', 'Stage 3 warship'), ('stage7', 'Stage 7')])
    (OUT / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>R-Type default colours</title>'
        '<style>body{background:#111820;color:#edf3fa;font:16px system-ui;margin:24px}img{max-width:100%;image-rendering:pixelated}</style>'
        '<h1>R-Type default colour quantization</h1><p>Arcade target colours in the same simplified composition, previous default, new default captured from the native 68000/Blitter renderer in the simulator.</p>' + cards)


if __name__ == '__main__':
    main()
