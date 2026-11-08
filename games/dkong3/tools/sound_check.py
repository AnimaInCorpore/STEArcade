"""The STE's sound against MAME's for the same commands (nobody listens: numbers).

    python sound_check.py make [--frames N] [--seed S]      # the command script: build/dkong3/sndtest.s (for -D SNDTEST=1) and
                                                            # MAME's recording of the same commands: build/dkong3/sound/check_mame.wav
    python sound_check.py hatari                            # build the SNDTEST program, run it in Hatari with sound, extract the audio
    python sound_check.py compare                           # the two recordings: levels, timing, which sounds

The script is the reference's own sound latch values in a play (coin, start, random joystick): per STE VBL (20 ms) the value
the latches held at that arcade time (MAME's 60.606 frames a second); MAME gets the same values as events at the arcade frames
(tools/sound_capture.py: its main CPU parked).  The SNDTEST build (src/sound.s) feeds snd_frame from the script, so the
timing does not depend on how fast the translated game runs in Hatari.  Hatari's AVI holds the DMA sound; its level is
the program's (the clips' scale 56 of 127, three voices).
"""
import argparse, os, subprocess, sys, wave
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from paths import build_dir, ROOT
import sound_capture as sc
from machine import DK3

BUILD = build_dir('dkong3')
START = 100                                     # the script starts at this VBL
OUT = BUILD / 'sound'


def make(frames, seed):
    import random
    rnd = random.Random(seed)
    m = DK3()
    log = []
    joy = jl = 0
    last = (0, 0, 0)
    vals = []
    for f in range(frames):
        if jl == 0:
            joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18, 5, 9, 1, 2, 0]); jl = rnd.randint(3, 40)
        jl -= 1
        m.ram[0x6BF1 - 0x6000] = 0x63
        m.set_inputs(p1=joy, coin=f % 600 == 30, start1=f % 600 in (100, 101, 102))
        m.run_frame()
        cur = (m.snd[0x7C00], m.snd[0x7C80], m.snd[0x7D00])
        vals.append(cur)
        if cur != last:
            for a, o, n in zip((0x7C00, 0x7C80, 0x7D00), last, cur):
                if o != n:
                    log.append((f, a, n))
            last = cur
    seconds = frames / sc.FPS
    n = int(seconds / 0.02)
    lines = ['SNDTEST_START = %d' % START, 'SNDTEST_N = %d' % n, 'snd_script:']
    rows = []
    for k in range(n):
        f = min(int(k * 0.02 * sc.FPS), frames - 1)
        rows.append(vals[f])
    for i in range(0, n, 8):
        lines.append('\tdc.b ' + ','.join('%d,%d,%d' % r for r in rows[i:i + 8]))
    lines.append('\teven')
    (BUILD / 'sndtest.s').write_text('\n'.join(lines) + '\n')
    events = ' '.join('%d:%04x=%d' % e for e in log)
    x, rate = sc.capture('check_mame', events, seconds + 1.0)
    print('script: %d VBLs (%.1f s), %d latch changes; MAME: %.1f s recorded, peak %.3f' % (n, n * 0.02, len(log), len(x) / rate, np.abs(x).max()))


def hatari(extra=()):
    import re
    text = (BUILD / 'sndtest.s').read_text()
    n = int(re.search(r'SNDTEST_N = (\d+)', text).group(1))
    frames = START + n + 150
    ps = ROOT / 'games' / 'dkong3' / 'tools' / 'hatari.ps1'
    r = subprocess.run(['powershell', '-ExecutionPolicy', 'Bypass', '-Command',
                        "& '%s' -Frames %d -Every 100000 -Name dkong3_sndcheck -Sound 1 -Extra @('-D','SNDTEST=1','-D','AUTOPLAY=1')" % (ps, frames)],
                       capture_output=True, text=True)
    print(r.stdout[-600:], r.stderr[-300:])
    avi = ROOT / 'run' / 'dkong3_sndcheck' / 'dkong3.avi'
    wav = OUT / 'check_hatari.wav'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(avi), '-vn', '-ac', '1', '-ar', '48000', str(wav)], check=True)
    print('Hatari audio:', wav)


def load(path):
    w = wave.open(str(path))
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels())[:, 0].astype(float) / 32768
    return x, w.getframerate()


def envelope(x, r, win=0.05):
    n = int(win * r)
    k = len(x) // n
    return np.sqrt((x[:k * n].reshape(k, n) ** 2).mean(1))


def compare():
    a, ra = load(OUT / 'check_mame.wav')
    b, rb = load(OUT / 'check_hatari.wav')
    assert ra == rb, (ra, rb)
    ea, eb = envelope(a, ra), envelope(b, rb)
    # align: the Hatari recording has the program's start and the script's START VBLs before the first command
    best = (-2, 0)
    for lag in range(0, min(len(eb) - 40, 400)):
        n = min(len(ea), len(eb) - lag)
        c = np.corrcoef(ea[:n], eb[lag:lag + n])[0, 1] if ea[:n].std() and eb[lag:lag + n].std() else 0
        if c > best[0]:
            best = (c, lag)
    c, lag = best
    n = min(len(ea), len(eb) - lag)
    ea, eb = ea[:n], eb[lag:lag + n]
    print('envelope (50 ms) correlation %.3f at an offset of %.2f s' % (c, lag * 0.05))
    on_a, on_b = ea > 0.004, eb > 0.004
    print('sound present in %.0f%% of the windows in MAME, %.0f%% in Hatari; both %.0f%%; only MAME %.0f%%, only Hatari %.0f%%' % (
        100 * on_a.mean(), 100 * on_b.mean(), 100 * (on_a & on_b).mean(), 100 * (on_a & ~on_b).mean(), 100 * (~on_a & on_b).mean()))
    both = on_a & on_b
    if both.any():
        ratio = eb[both].sum() / ea[both].sum()
        print('level: Hatari / MAME rms over the windows with sound in both: %.2f (%.1f dB)' % (ratio, 20 * np.log10(ratio)))
    for i in range(0, n, 20):                          # per second
        s = slice(i, i + 20)
        print('%5.1f s  MAME rms %.4f  Hatari rms %.4f' % (i * 0.05, ea[s].mean(), eb[s].mean()))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('make', 'hatari', 'compare'))
    ap.add_argument('--frames', type=int, default=2400)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    {'make': lambda: make(a.frames, a.seed), 'hatari': hatari, 'compare': compare}[a.cmd]()
