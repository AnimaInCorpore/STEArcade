"""Gameplay-frame previews of current, bounded flat and bounded checker colours.

    venv/bin/python tools/palette_gallery.py

Runs each port's reference game with its curated controls and captures the same
visible pens for every treatment. No native executable or palette is modified.
Checker candidates use screen parity; current native colours use source parity.
"""
import argparse
import collections
import concurrent.futures
import importlib.util
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'engine')]
import palette_quantize as PQ

OUT = ROOT / 'build/palette_gallery'
GAMES = {
    'gyruss': ('Gyruss', 'GyrussPort', 4),
    'timeplt': ('Time Pilot', 'TimepltPort', 4),
    'trackfld': ('Track & Field', 'TrackFieldPort', 1),
    'hyperspt': ('Hyper Sports', 'HyperSportsPort', 1),
    'mrdo': ('Mr. Do!', 'MrDoPort', 4),
    'pooyan': ('Pooyan', 'PooyanPort', 4),
    'commando': ('Commando', 'Commando', 1),
    'gunsmoke': ('Gun.Smoke', 'GunSmoke', 1),
    'blktiger': ('Black Tiger', 'BlackTiger', 1),
    'ddragon': ('Double Dragon', 'DDragonPort', 11),
    'gauntlet': ('Gauntlet', 'Gauntlet', 1),
}
FRAMES = (800, 1400)
PREFIX = dict(gyruss='gy', timeplt='tp', trackfld='tf', hyperspt='hs', mrdo='md', pooyan='py')


def capture_frames(game):
    if game in ('blktiger', 'ddragon', 'gauntlet'):
        return (1500, 2100)
    return (1400, 2200) if game in ('commando', 'gunsmoke') else FRAMES


def sprite(game, pen):
    if game == 'commando':
        return 128 <= pen < 192
    if game == 'gunsmoke':
        return 384 <= pen < 640
    return pen >= 256 if game in ('mrdo', 'pooyan') else pen >= 128 if game == 'timeplt' else pen < 256


def text_layer(game, pen):
    if game == 'commando': return (pen >= 192) & (pen < 256)
    if game == 'gunsmoke': return pen < 128
    return ~np.asarray(sprite(game, pen))


def decode_palette(words):
    nib = np.stack([(words >> shift) & 15 for shift in (8, 4, 0)], axis=1)
    return ((((nib & 7) << 1) | (nib >> 3)) * 17).astype(np.uint8)


def capcom_samples(game, machine, cover, reuse):
    """Capture without calling assets.palette(), which writes production files."""
    built = ROOT / 'build' / game
    cached = OUT / (game + '_gameplay_native_phase.npz')
    if game == 'commando':
        video = machine.Gfx()
        pens = video.rgb
    else:
        video = load_module('gallery_video', ROOT / 'games/gunsmoke/tools/video.py').Video()
        pens = np.vstack([video.pens, np.zeros((1, 3), np.uint8)])
    current = decode_palette(np.frombuffer((built / 'palette.bin').read_bytes(), '>u2').astype(np.int32))
    mapping = np.frombuffer((built / 'palmap.bin').read_bytes(), np.uint8)
    frames = capture_frames(game)
    if reuse and cached.exists():
        data = np.load(cached)
        shots = {f:data[str(f)] for f in frames}
        counts = data['training_counts']
    else:
        port = getattr(machine, GAMES[game][1])()
        if game == 'commando':
            port.gfx = video
        rng, controls = random.Random(1), {}
        shots, counts = {}, np.zeros(len(pens), np.int64)
        # Commando's original fit uses exactly these seed-1 samples. Gun.Smoke
        # has a retained histogram covering all rounds, loaded below.
        training = {100, 300, 700, 900, 1000, 1200, 1500, 1800, 2200, 2500}
        last = 2599 if game == 'commando' else max(frames)
        for frame in range(last + 1):
            if game == 'commando':
                port.inputs[:3] = cover.inputs(frame, rng)
            else:
                port.inputs[0], port.inputs[1] = cover.inputs(frame, rng, controls)
            port.run_frame_port()
            if frame not in frames and not (game == 'commando' and frame in training):
                continue
            raw = port.render_raw(checker=True) if game == 'commando' else video.render_raw(port, checker=True)
            raw = raw[16:240]
            if game == 'commando' and frame in training:
                counts += np.bincount((raw & 1023).ravel(), minlength=len(pens))
            if frame in frames:
                shots[frame] = np.ascontiguousarray(raw.T[::-1])
                print('captured', game, frame, flush=True)
        np.savez_compressed(cached, training_counts=counts, **{str(f):r for f, r in shots.items()})
    if game == 'gunsmoke':
        stats = json.loads((ROOT / 'games/gunsmoke/docs/palette_stats.json').read_text())
        counts = np.sum(np.array(list(stats.values()), np.int64), axis=0)
    hist = {int(p):int(counts[p]) for p in np.nonzero(counts)[0]}
    return pens, current, mapping, hist, shots, str(built / 'palette.bin')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gameplay(game, machine, cover, video, seed):
    port = getattr(machine, GAMES[game][1])(*cover.dsw(seed))
    rng = random.Random(seed)
    controls = dict(seed=seed, two=False, coin_at=300)
    shots = {}
    for frame in range(max(FRAMES) + 1):
        if game == 'mrdo':
            cover.apply_inputs(port, frame, rng, controls)
        elif game == 'gyruss':
            port.system, port.p1 = cover.inputs(frame, rng, controls, port)
        elif game == 'trackfld':
            port.system, port.in0, port.in1 = cover.inputs(frame, rng, controls)
        elif game == 'hyperspt':
            port.system, port.p1_p2, port.p3_p4 = cover.inputs(frame, rng, controls)
        else:
            port.system, port.p1, port.p2 = cover.inputs(frame, rng, controls)
        cover.cheats(seed, frame, port, controls)
        port.frame = frame
        port.run_frame_port()
        if frame not in FRAMES:
            continue
        if game == 'mrdo':
            raw = port.render_raw()[machine.VIS_Y0:machine.VIS_Y1, machine.VIS_X0:machine.VIS_X1].T[::-1]
        else:
            if game == 'gyruss':
                raw = video.render_raw(port.mem, port.bands())
            elif game == 'timeplt':
                raw = video.render_raw(port.mem, port.extra)
            else:
                raw = video.render_raw(port.mem)
            raw = raw[16:240]
            if game in ('gyruss', 'timeplt', 'pooyan'):
                raw = np.rot90(raw, -1)
        shots[frame] = np.ascontiguousarray(raw)
        print('captured', game, frame, controls.get('phase'), flush=True)
    return shots


def panel(game, frame, labels, pictures, suffix):
    h, w = pictures[0].shape[:2]
    image = Image.new('RGB', (2 * w * len(pictures), 2 * h + 88), '#151d27')
    draw = ImageDraw.Draw(image)
    font_path = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
    font = ImageFont.truetype(str(font_path), 21) if font_path.exists() else ImageFont.load_default()
    draw.text((12, 10), f'{GAMES[game][0]} — gameplay frame {frame}', font=font, fill='white')
    for i, (label, pixels) in enumerate(zip(labels, pictures)):
        draw.text((2 * w * i + 12, 48), label, font=font, fill='#c9d7e6')
        image.paste(Image.fromarray(pixels).resize((2 * w, 2 * h), Image.Resampling.NEAREST), (2 * w * i, 88))
    image.save(OUT / f'{game}_{frame}_{suffix}.png')


def make_game(game, reuse=False):
    tools = ROOT / 'games' / game / 'tools'
    refs = tools.parent / 'ref'
    sys.path[:0] = [str(tools), str(refs)]
    machine = load_module('machine', tools / 'machine.py')
    sys.modules['machine'] = machine
    cover = load_module('cover', refs / 'cover.py')
    if game in ('blktiger', 'ddragon', 'gauntlet'):
        from palette_ram_gallery import make_game as make_ram_game
        make_ram_game(game, machine, cover, reuse)
        return
    built = ROOT / 'build' / game
    shots = None
    if game in ('commando', 'gunsmoke'):
        pens, current, current_map, hist, shots, current_source = capcom_samples(game, machine, cover, reuse)
    else:
        assets = load_module('gallery_assets', tools / 'assets.py')
        video = assets.Gfx() if game == 'mrdo' else assets.Video()
        pens = video.rgb[:320] if game == 'mrdo' else video.pens
        prefix = PREFIX[game]
        # Use the built palette/map; a regenerated fit can differ from the port.
        current_source = str(built / (prefix + '_assets.s'))
        text = Path(current_source).read_text()
        line = re.search(prefix + r'_pal:\s*dc.w ([^\n]+)', text).group(1)
        words = np.array([int(v.strip()[1:], 16) for v in line.split(',')])
        current = decode_palette(words)
        current_map = np.frombuffer((built / (prefix + '_penmap.bin')).read_bytes(), np.uint8)
        hist = assets.histogram()
    layers = [collections.Counter(), collections.Counter()]
    for pen, count in hist.items():
        layers[0 if sprite(game, pen) else 1][tuple(map(int, pens[pen]))] += int(count)
    inputs = np.unique(pens, axis=0)
    treatments = {}
    for mode in ('flat', 'checker'):
        palette, pairs = PQ.fit(layers, inputs, cache=OUT / 'cache', dither=mode == 'checker')
        lut = {tuple(c):int(pair) for c, pair in zip(inputs, pairs)}
        treatments[mode] = palette, np.array([lut[tuple(c)] for c in pens], np.uint8)
    cached = OUT / (game + '_gameplay.npz')
    seed = GAMES[game][2]
    if shots is not None:
        pass
    elif reuse and cached.exists():
        data = np.load(cached)
        shots = {f:data[str(f)] for f in FRAMES}
    else:
        shots = gameplay(game, machine, cover, video, seed)
        np.savez_compressed(cached, **{str(f):raw for f, raw in shots.items()})
    info = dict(game=game, seed=seed, capture_frames=list(capture_frames(game)),
                provenance='Port reference emulator, curated controls; offline colour previews',
                checker_phase='screen parity for static comparison', text_dither=False, native_executable_changed=False,
                current_palette=current.tolist(), current_palette_source=current_source,
                palettes={m:p.tolist() for m, (p, _) in treatments.items()}, frames={})
    for frame, raw in shots.items():
        phase, raw = raw >> 10, raw & 1023
        assert raw.min() >= 0 and raw.max() < len(pens)
        original = pens[raw].astype(np.uint8)
        packed = current_map if game in ('commando', 'gunsmoke') and current_map.max() > 15 else current_map * 17
        shown = {'current':current[PQ.indices(packed[raw], phase)]}
        y, x = np.indices(raw.shape)
        for mode, (palette, mapping) in treatments.items():
            pair = mapping[raw]
            indices = np.where((x + y) & 1, pair & 15, pair >> 4)
            text = text_layer(game, raw)
            indices[text] = PQ.flat_map(palette, pens)[raw[text]]
            shown[mode] = palette[indices]
            assert len(np.unique(shown[mode].reshape(-1, 3), axis=0)) <= 16
        for name, pixels in dict(arcade=original, **shown).items():
            Image.fromarray(pixels).save(OUT / f'{game}_{frame}_{name}.png')
        panel(game, frame, ['Current palette', 'New quantization'], [shown['current'], shown['checker']], 'pair')
        panel(game, frame, ['Arcade RGB', 'Current palette', 'New — flat', 'New — checker'],
              [original, shown['current'], shown['flat'], shown['checker']], 'all')
        pal, mapping = treatments['checker']
        pairs = mapping[raw]
        info['frames'][frame] = dict(size=list(raw.shape[::-1]), source_colors=len(np.unique(original.reshape(-1, 3), axis=0)),
                                    checker_fraction=float(np.mean(((pairs >> 4) != (pairs & 15)) & ~text_layer(game, raw))))
    (OUT / (game + '.json')).write_text(json.dumps(info, indent=2) + '\n')
    print('finished', game, flush=True)


def gallery():
    cards = []
    for game, (name, _, _) in GAMES.items():
        if not (OUT / (game + '.json')).exists():
            continue
        frames = ''.join(f'<figure><img src="{game}_{f}_pair.png" alt="{name} current and proposed colours">'
                         f'<figcaption>Gameplay frame {f}. <a href="{game}_{f}_all.png">Arcade / current / new flat / new checker</a>'
                         f' · <a href="{game}_{f}_checker.png">Native-size new preview</a></figcaption></figure>' for f in capture_frames(game))
        cards.append(f'<section id="{game}"><h2>{name}</h2>{frames}</section>')
    nav = ' · '.join(f'<a href="#{g}">{name}</a>' for g, (name, _, _) in GAMES.items())
    (OUT / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Other ports: in-game colour comparison</title>'
        '<style>body{background:#101720;color:#edf3fa;font:17px system-ui;margin:28px}a{color:#8bc7ff}img{max-width:100%;image-rendering:pixelated}'
        'figure{margin:20px 0 40px}section{margin-top:48px}p{max-width:1000px}figcaption{font-size:14px;margin-top:10px}</style>'
        '<h1>In-game colour comparisons</h1><p>Left: current STE palette. Right: the new bounded weighting plus restrained checker dithering, '
        'using the same gameplay frame and a fixed 16-colour palette per game. Current colours and pen maps are read from the built port assets.</p><p>These are offline colour previews of captured reference-emulator '
        'gameplay. Running this tool does not modify native assets or executables. Candidate checker phase is screen anchored for these stills; '
        'current native colours use source-anchored pairs where supported. Text/character layers always use flat colours. The four-column views include arcade RGB and the flat candidate.</p>'
        '<p>Black Tiger, Double Dragon and Gauntlet previews fit the new palette to sampled play sequences, rather than claiming whole-game palette coverage. Gauntlet keeps its four fixed player colours.</p>'
        f'<nav>{nav}</nav>' + ''.join(cards))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', choices=GAMES)
    parser.add_argument('--reuse', action='store_true')
    parser.add_argument('--games', nargs='+', choices=GAMES, help='Only generate these ports and refresh the combined gallery')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.game:
        make_game(args.game, args.reuse)
        return
    def run(game):
        cmd = [sys.executable, str(Path(__file__)), '--game', game] + (['--reuse'] if args.reuse else [])
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        print(result.stdout, end='', flush=True)
        if result.returncode:
            raise RuntimeError(game + '\n' + result.stderr)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, args.games or GAMES))
    gallery()
    print(OUT / 'index.html', flush=True)


if __name__ == '__main__':
    main()
