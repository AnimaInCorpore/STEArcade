"""Read-only comparison of current fixed palettes with the bounded shared policy.

    venv/bin/python tools/palette_audit.py

Uses existing coverage histograms and the ports' own PROM-derived reference RGB.
No game assets or palette documents are written. Candidate mappings are flat:
these ports' existing renderers do not yet consume checker index pairs.
"""
import argparse
import collections
import concurrent.futures
import importlib.util
import json
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
import palette_quantize as PQ

GAMES = ('gyruss', 'timeplt', 'trackfld', 'hyperspt', 'mrdo', 'pooyan')
OUT = ROOT / 'build/palette_audit'


def measure(game):
    tools = ROOT / 'games' / game / 'tools'
    sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location('audited_assets', tools / 'assets.py')
    assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assets)
    video = assets.Gfx() if game == 'mrdo' else assets.Video()
    pens = video.rgb[:320] if game == 'mrdo' else video.pens
    result = assets.palette(video)
    current, mapping = np.array(result[0]), np.array(result[1])
    hist = assets.histogram()
    layers = [collections.Counter(), collections.Counter()]
    for pen, n in hist.items():
        sprite = pen >= 256 if game in ('mrdo', 'pooyan') else pen >= 128 if game == 'timeplt' else pen < 256
        layers[0 if sprite else 1][tuple(map(int, pens[pen]))] += int(n)
    inputs = np.unique(pens, axis=0)
    palette, pairs = PQ.fit(layers, inputs, cache=OUT / 'cache', dither=False)
    lut = {tuple(c):int(v >> 4) for c, v in zip(inputs, pairs)}
    candidate = np.array([lut[tuple(c)] for c in pens])
    lab = PQ.oklab(pens)
    metrics = {}
    for name, pal, index in [('current', current, mapping), ('bounded', palette, candidate)]:
        delta = PQ.oklab(pal)[index] - lab
        groups = {}
        for group in ('all', 'nonblack', 'sprites', 'tiles', 'neutral', 'chromatic'):
            count, error = [], []
            for pen, n in hist.items():
                sprite = pen >= 256 if game in ('mrdo', 'pooyan') else pen >= 128 if game == 'timeplt' else pen < 256
                chroma = np.linalg.norm(lab[pen, 1:])
                if (group == 'sprites' and not sprite) or (group == 'tiles' and sprite):
                    continue
                if group == 'nonblack' and not np.any(pens[pen]):
                    continue
                if (group == 'neutral' and chroma >= .06) or (group == 'chromatic' and chroma < .1):
                    continue
                count.append(n); error.append(np.linalg.norm(delta[pen]) * 100)
            if count:
                groups[group] = float(np.average(error, weights=count))
        metrics[name] = groups
    info = dict(game=game, sampled_pixels=sum(hist.values()), used_pens=len(hist),
                current_palette=current.tolist(), candidate_palette=palette.tolist(),
                mean_oklab_error=metrics, mode='flat; no runtime graphics changed')
    if game == 'mrdo':
        critical = {}
        for name, rgb in [('blue', [0, 0, 255]), ('red', [255, 0, 0]), ('orange_red', [255, 88, 0])]:
            pen = int(np.linalg.norm(pens.astype(float) - rgb, axis=1).argmin())
            critical[name] = dict(source=pens[pen].tolist(), current=current[mapping[pen]].tolist(),
                                  bounded=palette[candidate[pen]].tolist())
        info['critical_colours'] = critical
    (OUT / (game + '.json')).write_text(json.dumps(info, indent=2) + '\n')
    print(game, metrics, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', choices=GAMES)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.game:
        measure(args.game)
        return
    def run(game):
        return subprocess.run([sys.executable, str(Path(__file__)), '--game', game],
                              cwd=ROOT, capture_output=True, text=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for game, result in zip(GAMES, pool.map(run, GAMES)):
            print(result.stdout, end='')
            if result.returncode:
                raise RuntimeError(game + '\n' + result.stderr)
    report = {game:json.loads((OUT / (game + '.json')).read_text()) for game in GAMES}
    (OUT / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
