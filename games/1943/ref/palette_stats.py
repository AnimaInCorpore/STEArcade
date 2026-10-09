"""How often each of the 256 arcade colours shows: every stage (MAME's cheats as in cover.py: energy, invincibility, the
level select E450), random play, a picture every 50 ticks from tick 1200 on, plus the attract mode.

    palette_stats.py [ticks]     -> docs/palette_stats.json (pixel counts per colour, per stage and in all)
"""
import json
import random
import sys
from multiprocessing import Pool
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from machine import Game1943

DOCS = Path(__file__).resolve().parents[1] / 'docs'


def stage(args):
    level, ticks = args
    rng = random.Random(level + 100)
    m = Game1943()
    m.render_rgb()
    m.scanline = 16
    m.run_to_idle()
    m.booted = True
    counts = np.zeros(256, np.int64)
    for f in range(ticks):
        if level >= 0 and f >= 700:
            m.inputs[0] = 255 & ~(64 if f % 180 < 5 else 0) & ~(1 if f % 120 < 5 else 0)
            if f % 30 == 0:
                m.inputs[1] = 255 ^ rng.choice([0, 1, 2, 4, 8, 16, 32, 17, 18, 20, 24, 33, 34])
        if level >= 0:
            if 700 <= f < 1100:
                m.mem[0xe450] = level
            m.mem[0xf206] = 0x40
            m.mem[0xf214] = 2
        m.run_frame_port()
        if f >= (1200 if level >= 0 else 200) and f % 50 == 0:
            raw = m.video.render_raw(m.mem, m.sprites, m.control, m.layers)[16:240]
            counts += np.bincount(raw.ravel(), minlength=256)
    return level, counts.tolist()


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    with Pool(16) as pool:
        results = dict(pool.map(stage, [(level, ticks) for level in range(-1, 15)]))
    total = np.sum([results[k] for k in results], axis=0)
    out = dict(ticks=ticks, total=total.tolist(), stages={str(k): v for k, v in sorted(results.items())})
    (DOCS / 'palette_stats.json').write_text(json.dumps(out) + '\n')
    print('colours seen:', int((total > 0).sum()))


if __name__ == '__main__':
    main()
