"""Build-time STE colour fitting, shared by ports and visual experiments.

The default preserves sprite priority after count compression and bounds the
chroma bonus below 2x. It changes importance, never the source RGB values.
Checker choices are two STE indices, anchored in source-image coordinates.
"""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

FREQUENCY_POWER = .75
CHROMA_GAIN = 1.0
SPRITE_WEIGHT = 8.0
WORKER = Path(__file__).with_suffix('.js')


def oklab(rgb):
    rgb = np.asarray(rgb, dtype=float) / 255
    linear = np.where(rgb > .04045, ((rgb + .055) / 1.055)**2.4, rgb / 12.92)
    lms = linear @ np.array([[.4122214708, .5363325363, .0514459929],
                             [.2119034982, .6806995451, .1073969566],
                             [.0883024619, .2817188376, .6299787005]]).T
    return np.cbrt(lms) @ np.array([[.2104542553, .7936177850, -.0040720468],
                                    [1.9779984951, -2.4285922050, .4505937099],
                                    [.0259040371, .7827717662, -.8086757660]]).T


def balanced_weights(histograms, power=FREQUENCY_POWER, chroma_gain=CHROMA_GAIN,
                     sprite_weight=SPRITE_WEIGHT):
    sprites, tiles = histograms
    colors = sorted(sprites.keys() | tiles.keys())
    if not colors:
        return [['0,0,0', 1.0]]
    chroma = np.linalg.norm(oklab(colors)[:, 1:], axis=1)
    bonus = 1 + chroma_gain * chroma**2 / (chroma**2 + .1**2)
    count = np.array([[h.get(c, 0) for c in colors] for h in histograms], float)
    weight = (sprite_weight * count[0]**power + count[1]**power) * bonus
    return [[','.join(map(str, c)), float(w)] for c, w in zip(colors, weight)]


def fit(histograms, inputs, count=16, cache=None, dither=True):
    """Return RGB palette and packed pairs (even-source parity high nibble).

    Inputs and histogram keys are original RGB triples. Black stays index zero.
    The cache includes both source and all policy/input data in its hash.
    """
    job = dict(hist=balanced_weights(histograms), input_colors=np.asarray(inputs).tolist(),
               color_count=count, dither_l=.12 if dither else 0)
    payload = json.dumps(job, sort_keys=True, separators=(',', ':')).encode()
    key = hashlib.sha256(WORKER.read_bytes() + payload).hexdigest()
    path = Path(cache) / (key + '.json') if cache is not None else None
    if path is not None and path.exists():
        result = json.loads(path.read_text())
    else:
        result = json.loads(subprocess.check_output(['node', str(WORKER)], input=payload))
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result) + '\n')
    palette = np.array(result['palette'], np.uint8)
    assert 0 < len(palette) <= count <= 16 and np.all(palette % 17 == 0)
    assert np.all(palette[0] == 0) and len(result['choices']) == len(inputs)
    pairs = np.array([(c['first'] << 4) | c['second'] for c in result['choices']], np.uint8)
    palette = np.pad(palette, ((0, count - len(palette)), (0, 0)))
    return palette, pairs
