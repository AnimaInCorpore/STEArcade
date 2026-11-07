"""Video states of the reference (tools/machine.py, the port's schedule) for the renderer's tests.

    venv/bin/python games/dspirit/tools/states.py      -> build/dspirit/render_states.pkl

A state is what the renderer reads after an arcade frame: the palette RAM (the C116's three planes, 8192 pens each),
the C116 registers, the tile RAM, the CUS123 control, the sprite RAM (the latched list) and the flip.
    play     1500 consecutive frames from the port's start (seed 5's inputs: coin, start, random stick and buttons)
    attract  every 4th of 2000 attract frames (seed 1: no inputs)
    bench    1600 consecutive frames of dspirit.s' BENCH game (bench_inputs: coin at 60, start at 140, from 300
             right, right + up, left, down 60 frames each, air shot 3 frames in 20, bomb 2 in 90): the game Hatari's benchmark plays
             (build/dspirit/render_bench.pkl)
"""
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from cover import random_bits
from machine import DSpirit
from paths import build_dir


def state(m):
    return dict(pal=[bytes(p) for p in m.pal], regs=list(m.c116_regs), vram=bytes(m.vram), control=bytes(m.control),
                spriteram=bytes(m.spriteram), flip=m.flip, frame=m.frame)


def play_inputs(seed):
    """the inputs of logic_test.py's seeds above 3: f -> (control0, coin) changes, as a generator over frames"""
    rng = random.Random(seed)
    hold = 0
    control, coin = 0xFF, 0xF8
    f = 0
    while True:
        if f == 30:
            coin &= ~0x10
        elif f == 36:
            coin |= 0x10
        elif f == 130:
            control &= ~0x80
        elif f == 136:
            control |= 0x80
        elif f > 180:
            if hold <= 0:
                control = (0xFF & ~random_bits(rng)) | 0x80
                hold = rng.randint(2, 30)
            hold -= 1
            if f % 1500 == 0:
                coin &= ~0x10
            elif f % 1500 == 6:
                coin |= 0x10
            elif f % 1500 == 100:
                control &= ~0x80
            elif f % 1500 == 106:
                control |= 0x80
        yield control, coin
        f += 1


def bench_inputs(f):
    """dspirit.s bench_inputs at arcade frame f (frames counted from the port's start): (control0, coin)"""
    coin, control = 0xFF, 0xFF
    if 60 <= f < 66:
        coin = 0xEF
    elif 140 <= f < 146:
        control = 0x7F
    elif f >= 300:
        control = (0xFE, 0xF6, 0xFD, 0xFB)[(f // 60) & 3]       # right, right + up, left, down
        if f % 20 < 3:
            control &= 0xEF                                    # air shot
        if f % 90 < 2:
            control &= 0xDF                                    # bomb
    return control, coin & 0xF8


def record_bench(frames=1600):
    m = DSpirit()
    m.boot()
    seq = []
    for f in range(frames):
        m.control_in[0], m.coin_in = bench_inputs(f)
        m.run_frame_port()
        seq.append(state(m))
    return {"bench": seq}


def record(play_frames=1500, attract_frames=2000, every=4):
    out = {}
    m = DSpirit()
    m.boot()
    seq = []
    for f, (control, coin) in zip(range(play_frames), play_inputs(5)):
        m.control_in[0], m.coin_in = control, coin
        m.run_frame_port()
        seq.append(state(m))
    out["play"] = seq
    m = DSpirit()
    m.boot()
    seq = []
    for f in range(attract_frames):
        m.run_frame_port()
        if f % every == every - 1:
            seq.append(state(m))
    out["attract"] = seq
    return out


if __name__ == "__main__":
    if "--bench" in sys.argv:
        data = record_bench()
        with open(build_dir("dspirit") / "render_bench.pkl", "wb") as fh:
            pickle.dump(data, fh)
        print({k: len(v) for k, v in data.items()})
        sys.exit(0)
    data = record()
    with open(build_dir("dspirit") / "render_states.pkl", "wb") as fh:
        pickle.dump(data, fh)
    print({k: len(v) for k, v in data.items()})
