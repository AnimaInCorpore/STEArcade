"""A MAME recording's inputs as the port's recorded play (build/blktiger/play_inputs.bin, engine/playbot.py's runs).

Input: a MARP recording (.inp, or the .zip it comes in) of a MAME with input file format 3.5 (WolfMAME 0.184, e.g.
fw666_blktiger_2006700_wolf184.zip from replay.marpirc.net), read directly: no MAME plays it back.  Or a dump folder
of F030Arcade's scripts/mame_inp_dump.py (mame.json + mame.bin: per frame IN0 and IN1).
Port tick n gets MAME frame n's inputs (F030Arcade: the frame counter $E003 agrees from power-on).

    python tools/marp_inputs.py fw666_blktiger_2006700_wolf184.zip [--ticks N]
    PLAY=1 tools/bench.sh                     (EXTRA="--frames 30000" WAIT=620 for a longer run)

The .inp: a 64-byte header ('MAMEINP\\0', format 3.5, the set, the MAME version), then a zlib stream of one record a
frame: the time (seconds s32, attoseconds s64), the speed (u32), then each input port (seven for blktiger, in tag
order; IN0 the fifth, IN1 the sixth) as default u32 + pressed bits u32; the board reads default XOR pressed.  The port count is taken
from the record size (the frame times step by 1/60 s).

The port leaves the recorded game about 30 frames after the start press (no Z80 cycle budget: the game's tasks run
in zero frames and its random generator runs ahead), so this is human play's input density, not the expert's game.
The PLAYBACK build keeps the lives at 3 from tick 1000 on (PB_PLAY), so the play does not end at a game over.
"""
import argparse
import json
from pathlib import Path
import sys
import zipfile
import zlib

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'engine'))
from paths import build_dir  # noqa: E402

PORT_IN0 = 4            # the fifth of blktiger's seven ports (tag order; IN1 the sixth): fw666 presses coin and start here
COIN1, START1 = 0x40, 0x01


def inp_inputs(path):
    """IN0 and IN1 a frame from a format 3.5 .inp (or a .zip holding one)."""
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            name, = [n for n in z.namelist() if n.lower().endswith('.inp')]
            data = z.read(name)
    else:
        data = path.read_bytes()
    assert data[:8] == b'MAMEINP\0' and data[16:18] == b'\3\5', 'not a MAME 0.184-style input file (format 3.5)'
    assert data[20:32].rstrip(b'\0') == b'blktiger', data[20:32]
    z = zlib.decompress(data[0x40:])
    rec = next(n for n in range(24, 200, 8)
               if len(z) % n == 0 and int.from_bytes(z[n + 4:n + 12], 'little') in (16666666666666666, 16666666666666667))
    r = np.frombuffer(z, np.uint8).reshape(-1, rec)
    word = lambda o: r[:, o:o + 4].copy().view('<u4')[:, 0]
    port = lambda k: (word(16 + 8 * k) ^ word(20 + 8 * k)) & 0xff
    return np.stack([port(PORT_IN0), port(PORT_IN0 + 1)], 1)


def dump_inputs(folder):
    layout = json.loads((folder / 'mame.json').read_text())
    assert layout['ports'][:2] == [['IN0', 1], ['IN1', 1]], layout['ports']
    raw = np.fromfile(folder / 'mame.bin', np.uint8)
    return raw[:len(raw) // layout['record'] * layout['record']].reshape(-1, layout['record'])[:, :2]


def runs(ticks):
    out, i = bytearray(), 0
    while i < len(ticks):
        j = i
        while j < len(ticks) and j - i < 255 and ticks[j] == ticks[i]:
            j += 1
        out += bytes((j - i, *ticks[i]))
        i = j
    return bytes(out + b'\0')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src', type=Path, help='a .inp, its .zip, or a mame_inp_dump.py folder')
    ap.add_argument('--ticks', type=int, default=65000, help='the PLAYBACK build counts ticks in a word')
    ap.add_argument('--out', type=Path, default=build_dir('blktiger') / 'play_inputs.bin')
    a = ap.parse_args()
    frames = dump_inputs(a.src) if a.src.is_dir() else inp_inputs(a.src)
    ticks = [(int(s), int(p)) for s, p in frames[:a.ticks]]
    data = runs(ticks)
    a.out.write_bytes(data)
    p1 = frames[:, 1].astype(int)
    print(f'{a.out}: {len(ticks)} ticks of {len(frames)} frames, {len(data)} bytes; coin at frame '
          f'{int(np.flatnonzero(~frames[:, 0] & COIN1)[0])}, start at {int(np.flatnonzero(~frames[:, 0] & START1)[0])}; '
          f'P1 {np.count_nonzero(np.diff(p1)) / (len(p1) / 60):.1f} changes a second, {(p1 == 255).mean():.0%} idle')


if __name__ == '__main__':
    main()
