"""Convert the MAME sound board recordings to STE DMA sound: 8 bit signed mono at 6258 Hz (games/dkong/tools/
sound_convert.py with Junior's tunes and pins).

    python sound_convert.py [--rate 6258]     -> build/dkongjr/dkjr_sound.bin, dkjr_sound.s, sound/pcm/*.wav

Input: build/dkongjr/sound/*.wav from sound_capture.py --all (48 kHz).
  backgrounds  held_01-06 ($6089: the stage tunes): played in DMA repeat mode while $7C00 holds them.  1, 2, 4, 5 are
               periodic: one period, measured to a fraction of a sample from the autocorrelation (hint below) and
               sampled with an even number of points over exactly it, so the seam is continuous.  3 (no period: the
               8035 varies it) and 6 (8.62 s phrases that differ) loop a stretch of LOOP_STRETCH seconds whose last
               CROSS seconds are faded into its start.
  one-shots    shot_07-14 ($608A: 9-12 the stage clears, 12/13 the level fanfares, 7, 8, 14): to the end of the sound
  effects      the 8035's pins $7C81, $7D03-$7D06 and its IRQ $7D80
The discrete sounds (walk, jump, climb, fall) are YM patches (sound_ym.py), not in the blob.  The signal is low-passed
at 0.45 * rate (the board cuts at ~1.9 kHz); one scale for all clips keeps the board's relative levels.
"""
import argparse, json, os, sys, wave
import numpy as np
from scipy.signal import firwin, filtfilt
from scipy.interpolate import CubicSpline
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import build_dir
from sound_capture import spans

BUILD = build_dir("dkongjr")
SRC = BUILD / "sound"
PERIODS = {1: 8.367, 2: 2.785, 4: 11.16, 5: 1.568}     # s, the autocorrelation's strongest peaks (2026-10-29)
LOOP_STRETCH = {3: 6.0, 6: 8.62}                       # s; 6: one phrase
CROSS = 0.15
SHOTS = range(7, 15)
FX = (("7c81", "pin_7c81"), ("7d03", "pin_7d03"), ("7d04", "pin_7d04"), ("7d05", "pin_7d05"),
      ("7d06", "pin_7d06"), ("irq", "pin_7d80"))


def load(name):
    w = wave.open(str(SRC / (name + ".wav")))
    r = w.getframerate()
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768.0, r


def lowpass(x, r, cut):
    return filtfilt(firwin(511, cut, fs=r), [1.0], x)


def period(x, r, hint):
    """The loop period in (fractional) samples near hint s, refined on its farthest multiple in the recording."""
    x = x[r:] - x[r:].mean()
    n = len(x)
    f = np.fft.rfft(x, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n] / np.arange(n, 0, -1)
    ac /= ac[0]
    p0 = int(hint * r)
    p0 = p0 - 2000 + int(np.argmax(ac[p0 - 2000:p0 + 2001]))
    k = max(1, (n // 2) // p0)
    c = k * p0
    j = c - 100 + int(np.argmax(ac[c - 100:c + 101]))
    a, b, d = ac[j - 1], ac[j], ac[j + 1]
    return (j + 0.5 * (a - d) / (a - 2 * b + d)) / k, ac[p0]


def sample(spline, t0, step, n):
    return spline(t0 + step * np.arange(n))


def ensure():
    """For build.py: dkjr_sound.s / .bin and dkjr_ym.s, recorded (MAME) and converted only when missing."""
    if not ((BUILD / "dkjr_sound.s").exists() and (BUILD / "dkjr_sound.bin").exists()):
        if not (SRC / "pin_7d80.wav").exists():
            import sound_capture
            sound_capture.capture_all()
        build()
    if not (BUILD / "dkjr_ym.s").exists():
        import sound_ym
        sound_ym.main()


def build(rate=6258, verbose=False):
    clips = {}                                 # name -> (float samples at `rate`, loop)
    report = {}

    def prep(name):
        x, r = load(name)
        y = lowpass(x, r, 0.45 * rate)
        return x, y, r, CubicSpline(np.arange(len(y)), y)

    for n in range(1, 7):
        x, y, r, sp = prep("held_%02d" % n)
        key = "tune_%02d" % n
        if n in PERIODS:
            p, q = period(x, r, PERIODS[n])
            m = int(round(p * rate / r / 2)) * 2
            t0 = p * max(1, int(r / p) + 1)                    # a whole period past the first second (the start)
            loop = sample(sp, t0, p / m, m)
            nxt = sample(sp, t0 + p, p / m, m)
            err = np.abs(loop - nxt).mean() / np.abs(loop).mean()
            report[key] = dict(loop_s=round(p / r, 5), samples=m, corr=round(float(q), 4),
                               next_period_err=round(float(err), 4))
        else:
            L, X = LOOP_STRETCH[n], CROSS
            m = int(round(L * rate / 2)) * 2
            seg = sample(sp, 2.0 * r, r / rate, m + int(X * rate))
            k = len(seg) - m                                     # the tail past the loop, faded into its start
            w = np.linspace(0, 1, k)
            loop = seg[:m].copy()
            loop[:k] = loop[:k] * w + seg[m:] * (1 - w)
            report[key] = dict(loop_s=L, samples=m, crossfade_s=X)
        clips[key] = (loop, True)
    for n in SHOTS:
        x, y, r, sp = prep("shot_%02d" % n)
        end = spans(x, r)[-1][1] + 0.03
        clips["tune_%02d" % n] = (sample(sp, 0, r / rate, int(end * rate)), False)
        report["tune_%02d" % n] = dict(length_s=round(end, 3))
    for fx, src in FX:
        x, y, r, sp = prep(src)
        end = spans(x, r)[-1][1] + 0.03
        clips["fx_" + fx] = (sample(sp, 0, r / rate, int(end * rate)), False)
        report["fx_" + fx] = dict(length_s=round(end, 3))

    peak = max(np.abs(c).max() for c, _ in clips.values())
    scale = 127.0 / peak
    pcm_dir = SRC / "pcm"
    pcm_dir.mkdir(parents=True, exist_ok=True)
    blob = bytearray()
    offs = {}
    for name, (c, loop) in clips.items():
        if not loop:                           # 4 ms fade out, then even length (DMA works on words)
            f = min(len(c), int(0.004 * rate))
            c = c.copy()
            c[len(c) - f:] *= np.linspace(1, 0, f)
        q = np.clip(np.round(c * scale), -128, 127).astype(np.int8)
        if len(q) & 1:
            q = np.append(q, np.int8(0))
        offs[name] = (len(blob), len(blob) + len(q), loop)
        blob += q.tobytes()
        with wave.open(str(pcm_dir / (name + ".wav")), "wb") as o:   # listening copy, 8 bit as the STE plays it
            o.setnchannels(1); o.setsampwidth(1); o.setframerate(rate)
            o.writeframes((np.tile(q, 3 if loop else 1).astype(np.int16) + 128).astype(np.uint8).tobytes())
        report[name]["bytes"] = len(q)

    (BUILD / "dkjr_sound.bin").write_bytes(bytes(blob))
    lines = ["; generated by games/dkongjr/tools/sound_convert.py: 8 bit signed PCM, %d Hz" % rate,
             "; scale %.3f DMA steps per MAME level 1.0 (sound_ym.py sets the YM levels from it)" % scale,
             "SOUND_RATE\tequ\t%d" % rate,
             "SOUND_MODE\tequ\t$%02x\t\t; $ffff8921: mono, the rate" % (0x80 | {6258: 0, 12517: 1, 25033: 2, 50066: 3}[rate]),
             "", "\tsection\tdata,data", "\teven",
             "dk_sound:\tincbin\t\"dkjr_sound.bin\"", "dk_sound_end:", "\teven", "",
             "; $7C00 tune n (5 bits): start, end (dk_sound relative), 1 = loop while held (0, 0 = silence)",
             "sound_tunes:"]
    for n in range(32):
        k = "tune_%02d" % n
        if k in offs:
            s, e, lp = offs[k]
            lines.append("\tdc.l\t%d,%d\n\tdc.w\t%d\t\t; %02X" % (s, e, int(lp), n))
        else:
            lines.append("\tdc.l\t0,0\n\tdc.w\t0\t\t; %02X -" % n)
    lines.append("; one-shot effects of the 8035 (pins $7C81, $7D03-$7D06, the IRQ $7D80)")
    for k, (s, e, lp) in offs.items():
        if not k.startswith("tune_"):
            lines.append("snd_%s:\tequ\t%d\nsnd_%s_end:\tequ\t%d" % (k, s, k, e))
    (BUILD / "dkjr_sound.s").write_text("\n".join(lines) + "\n")
    json.dump(report, open(pcm_dir / "report.json", "w"), indent=1)
    if verbose:
        for k, v in report.items():
            print("%-10s %s" % (k, "  ".join("%s %s" % kv for kv in v.items())))
    print("total %d bytes (%.1f s); scale %.1f (peak %.3f)" % (len(blob), len(blob) / rate, scale, peak))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=6258, choices=(6258, 12517, 25033, 50066))
    build(ap.parse_args().rate, verbose=True)


if __name__ == "__main__":
    main()
