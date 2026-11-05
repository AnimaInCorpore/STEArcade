"""Adapters for the ports' fixed native palettes; all fitting stays build-time.

The RAM-palette ports retain their approved training histograms in docs so a
normal build never depends on the private screenshot gallery or a replay run.
"""
import collections
import hashlib
import json
from pathlib import Path

import numpy as np

import palette_quantize as PQ


def policy_hash(game):
    from paths import ROOT
    files = [Path(__file__), Path(PQ.__file__), PQ.WORKER,
             ROOT / 'games' / game / 'tools/assets.py']
    return hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()


def changed(game):
    """Invalidate pre-policy assets on an ordinary build, including old checkouts."""
    from paths import build_dir
    stamp = build_dir(game) / 'colour_policy.sha256'
    return not stamp.exists() or stamp.read_text().strip() != policy_hash(game)


def stamp(game):
    from paths import build_dir
    (build_dir(game) / 'colour_policy.sha256').write_text(policy_hash(game) + '\n')


def prom(game, counts, pens, sprites, dither=False):
    from paths import build_dir
    layers = PQ.pen_histograms(counts, pens, sprites)
    return PQ.fit(layers, pens, cache=build_dir(game) / 'palette_cache', dither=dither)


def ram(game, rgb):
    from paths import ROOT, build_dir
    doc = json.loads((ROOT / 'games' / game / 'docs/colour_training.json').read_text())
    layers = [collections.Counter({tuple(c):n for c, n in h}) for h in doc['histograms']]
    return PQ.fit(layers, rgb, cache=build_dir(game) / 'palette_cache', fixed=doc.get('fixed', []))


def spread_tables(label='spread_pairs'):
    """Packed pair -> planar colour bits, even / odd / even (1 KB each).

    A row's first pixel uses bank 0, the next bank +1024. Bank 1 reverses them.
    The repeated bank avoids wrap arithmetic while building the odd-row table.
    """
    values = []
    for phase in (0, 1, 0):
        for pair in range(256):
            c = (pair & 15) if phase else (pair >> 4)
            values.append(sum(((c >> p) & 1) << (24 - 8*p) for p in range(4)))
    return label + ':\n' + '\n'.join('\tdc.l ' + ','.join('$%08x' % v for v in values[i:i+8])
                                     for i in range(0, len(values), 8)) + '\n'
