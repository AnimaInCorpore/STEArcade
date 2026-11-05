"""Sampled-play colour previews for ports with palette RAM.

Used by palette_gallery.py. Original words and built lookup tables reproduce the
current port colours; new palettes fit the sampled play, not the whole game.
"""
import collections
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from palette_gallery import ROOT, OUT, PQ, load_module, capture_frames, panel

FIXED_PLAYERS = [[255, 0, 0], [0, 136, 255], [255, 255, 0], [0, 255, 0]]


def native_signature(game):
    folder = ROOT / 'build' / game
    files = [folder / 'palette_rgb.bin', folder / ('irgb_map.bin' if game == 'gauntlet' else 'rgb_map.bin'),
             folder / ('irgb_map_flat.bin' if game == 'gauntlet' else 'rgb_map_flat.bin'),
             ROOT / 'games' / game / 'tools/machine.py', ROOT / 'engine/mamegfx.py']
    video = ROOT / 'games' / game / 'tools/video.py'
    if video.exists(): files.append(video)
    return hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()


def reusable(path, signature):
    if not path.exists(): return False
    with np.load(path) as data:
        return 'native_signature' in data and str(data['native_signature']) == signature


def fit(layers, inputs, fixed, dither):
    return PQ.fit(layers, inputs, cache=OUT / 'cache', fixed=fixed, dither=dither)


def record(game, machine, cover):
    tools = ROOT / 'games' / game / 'tools'
    frames = capture_frames(game)
    shots, layers = {}, [collections.Counter(), collections.Counter()]
    current = np.frombuffer((ROOT / 'build' / game / 'palette_rgb.bin').read_bytes(), np.uint8).reshape(16, 3)
    mapping = np.frombuffer((ROOT / 'build' / game / ('irgb_map.bin' if game == 'gauntlet' else 'rgb_map.bin')).read_bytes(), np.uint8)
    flat_mapping = np.frombuffer((ROOT / 'build' / game / ('irgb_map_flat.bin' if game == 'gauntlet' else 'rgb_map_flat.bin')).read_bytes(), np.uint8)
    if game == 'blktiger':
        model = machine.BlackTiger()
        controls = load_module('gallery_controls', tools / 'logic_test.py').inputs
        def iterator():
            for frame in range(2200):
                model.inputs[:3] = controls(frame)
                if frame >= 1000:
                    model.mem[0xF3A0] = 3
                    model.inputs[1] = 255 ^ 1 ^ 16 ^ (32 if frame % 90 < 15 else 0)
                model.run_frame_port()
                yield frame, model
        sequence = iterator()
    elif game == 'ddragon':
        dsw1, controls = cover.schedule(11)
        model = machine.DDragonPort(machine.DSW0, dsw1)
        video = machine.Video()
        def iterator():
            for frame in range(2200):
                p1, p2, extra, coins = controls(frame)
                if coins:
                    model.coin(coins)
                model.inputs[:3] = [p1, p2, extra]
                cover.cheats(model, 11, frame)
                model.run_frame_port()
                yield frame, model
        sequence = iterator()
    else:
        render_test = load_module('gallery_scenario', tools / 'render_test.py')
        video = load_module('gallery_video', tools / 'video.py').Video()
        sequence = render_test.scenario(1, level=1, frames=2200)
    for frame, model in sequence:
        if frame not in frames and not (1100 <= frame < 2200 and frame % 30 == 0):
            continue
        if game == 'blktiger':
            raw = model.render_raw(checker=True)[16:240]
            data = np.frombuffer(model.mem, np.uint8).astype(np.int32)
            words = (data[0xD800:0xDC00] | (data[0xDC00:0xE000] << 8)) & 4095
            rgb = np.stack([(words >> 4) & 15, words & 15, (words >> 8) & 15], axis=1).astype(np.uint8) * 17
            sprite = ((raw & 1023) >= 0x200) & ((raw & 1023) < 0x300)
        elif game == 'ddragon':
            raw = video.render_raw(model.mem, model.scrollx, model.scrolly, checker=True)
            rgb = video.pens(model.mem)
            q = (rgb // 17).astype(np.int32)
            words = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
            sprite = ((raw & 1023) >= 128) & ((raw & 1023) < 256)
        else:
            vram = model.vram()
            raw = video.render_raw(vram, model.xscroll, (vram[0x5F6E] << 8) | vram[0x5F6F], checker=True)
            # Match the STE port's playfield crop and retained right-side panel.
            raw = np.hstack([raw[:, 8:232], raw[:, 240:336]])
            words = np.frombuffer(model.palette(), '>u2').astype(np.int32)
            rgb = video.pens(model.palette())
            sprite = ((raw & 1023) >= 0x100) & ((raw & 1023) < 0x200)
        phase, raw = raw >> 10, raw & 1023
        text = (raw >= 0x300) if game == 'blktiger' else (raw < 128) if game == 'ddragon' else (raw < 0x100)
        original = rgb[raw]
        if frame % 30 == 0 and frame >= 1100:
            for layer, mask in zip(layers, (sprite, ~sprite)):
                colors, counts = np.unique(original[mask], axis=0, return_counts=True)
                layer.update({tuple(map(int, c)):int(n) for c, n in zip(colors, counts)})
        if frame in frames:
            pairs = np.where(text, flat_mapping[words[raw]], mapping[words[raw]])
            shots[frame] = dict(rgb=original, current=current[PQ.indices(pairs, phase)], key=words[raw], text=text)
            print('captured', game, frame, flush=True)
    return current, shots, layers


def make_game(game, machine, cover, reuse):
    cache = OUT / (game + '_gameplay_native_phase.npz')
    frames = capture_frames(game)
    signature = native_signature(game)
    if reuse and reusable(cache, signature):
        data = np.load(cache)
        current = data['palette']
        layers = [collections.Counter({tuple(c):n for c, n in entries})
                  for entries in json.loads(str(data['hist']))]
        shots = {f:{k:data[f'{k}_{f}'] for k in ('rgb', 'current', 'key', 'text')} for f in frames}
    else:
        current, shots, layers = record(game, machine, cover)
        hist = [[[list(c), n] for c, n in h.items()] for h in layers]
        np.savez_compressed(cache, palette=current, hist=json.dumps(hist), native_signature=signature,
                            **{f'{k}_{f}':v for f, shot in shots.items() for k, v in shot.items()})
    inputs = np.unique(np.concatenate([shot['rgb'].reshape(-1, 3) for shot in shots.values()]), axis=0)
    fixed = FIXED_PLAYERS if game == 'gauntlet' else []
    treatments = {mode:fit(layers, inputs, fixed, mode == 'checker') for mode in ('flat', 'checker')}
    info = dict(game=game, capture_frames=list(frames), training='Sampled play frames 1100–2199 every 30 frames; not whole-game coverage',
                native_executable_changed=False, text_dither=False, fixed_player_colors=fixed,
                palettes={m:p.tolist() for m, (p, _) in treatments.items()}, frames={})
    for frame, shot in shots.items():
        original, current = shot['rgb'], shot['current']
        unique, inverse = np.unique(original.reshape(-1, 3), axis=0, return_inverse=True)
        shown = dict(current=current, arcade=original)
        y, x = np.indices(original.shape[:2])
        for mode, (palette, pairs) in treatments.items():
            lookup = {tuple(c):int(p) for c, p in zip(inputs, pairs)}
            codes = np.array([lookup[tuple(c)] for c in unique], np.uint8)[inverse].reshape(y.shape)
            indices = np.where((x + y) & 1, codes & 15, codes >> 4)
            text = shot['text']
            indices[text] = PQ.flat_map(palette, original[text])
            shown[mode] = palette[indices]
            assert len(np.unique(shown[mode].reshape(-1, 3), axis=0)) <= 16 and np.all(shown[mode] % 17 == 0)
            if mode == 'checker':
                info['frames'][frame] = dict(checker_fraction=float(np.mean(((codes >> 4) != (codes & 15)) & ~text)))
        for name, pixels in shown.items():
            Image.fromarray(pixels).save(OUT / f'{game}_{frame}_{name}.png')
        panel(game, frame, ['Current palette', 'New quantization'], [current, shown['checker']], 'pair')
        panel(game, frame, ['Arcade RGB', 'Current palette', 'New — flat', 'New — checker'],
              [original, current, shown['flat'], shown['checker']], 'all')
    (OUT / (game + '.json')).write_text(json.dumps(info, indent=2) + '\n')
    print('finished', game, flush=True)
