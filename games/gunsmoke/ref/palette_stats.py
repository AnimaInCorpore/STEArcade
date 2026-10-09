"""How often each of the 640 pens shows, per coverage seed (seed 1: attract and play from round 1, seeds 4-14: rounds 1-10
and the ending with MAME's cheats, see cover.py), counted on the visible picture every 40th frame of the port schedule.

    python ref/palette_stats.py [frames]   ->  docs/palette_stats.json  {seed: [641 counts]} (640: no layer, black)
"""
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import GunSmoke
import cover

SEEDS = [1] + list(range(4, 15))


def stats(args):
    seed, frames = args
    rnd = random.Random(seed)
    m = GunSmoke()
    if seed >= 4:
        rom = bytearray(m.rom)
        rom[0x100b] = rom[0x15f9] = 0xc9
        rom[0x08c6:0x08c8] = cover.ROUNDS[min(seed - 4, len(cover.ROUNDS) - 1)].to_bytes(2, 'little')
        m.rom = bytes(rom)
    counts = np.zeros(641, np.int64)
    state = {}
    for f in range(frames):
        m.inputs[0], m.inputs[1] = cover.inputs(f, rnd, state)
        if seed >= 4:
            m.mem[0xe040] = 6
            if f % 300 == 0:
                m.mem[0xf790] = 1
        m.run_frame_port()
        if f % 40 == 0 and f >= 300:
            if m.video is None:
                from video import Video
                m.video = Video()
            counts += np.bincount(m.video.render_raw(m)[16:240].ravel(), minlength=641)
    return seed, counts.tolist()


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    with ProcessPoolExecutor() as ex:
        result = dict(ex.map(stats, [(s, frames) for s in SEEDS]))
    out = Path(__file__).resolve().parents[1] / 'docs' / 'palette_stats.json'
    out.write_text(json.dumps({str(k): v for k, v in sorted(result.items())}) + '\n')
    print(out)


if __name__ == '__main__':
    main()
