"""Convert the MAME sound board recordings to STE DMA sound: 8 bit signed mono at 6258 Hz.

    python sound_convert.py [--rate 6258]     -> build/dkong/dk_sound.bin, dk_sound.s, sound/pcm/*.wav

Input: build/dkong/sound/*.wav from sound_capture.py --all (48 kHz).
  one-shots   shot_NN_*  and the 8035 effects (pins $7D03-05, death $7D80): trimmed after the last sound
  backgrounds held_NN_*  for 03 04 08 09 0B: one loop period, played in DMA repeat mode
  discrete    trig_0-2   walk / jump / stomp: converted only as the reference for the YM patches

The signal is low-passed at 0.45 * rate (the board itself cuts at ~1.9 kHz) and evaluated at arbitrary times
(cubic, the 48 kHz signal is ~17x oversampled by then).  A loop is one period P of the background, measured
to a fraction of a sample from the autocorrelation over many periods, and sampled with N (even) points over
exactly P, so the seam is continuous and the tempo is off by < 0.01%.  One scale for all clips keeps the
board's relative levels.  dk_sound.s: dk_sound (the blob), sound_tunes (16 x start, end, loop), sound_fx.
"""
import argparse, json, os, sys, wave
import numpy as np
from scipy.signal import firwin, filtfilt
from scipy.interpolate import CubicSpline
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import build_dir
from sound_capture import TUNES, spans

BUILD = build_dir("dkong")
SRC = BUILD / "sound"
LOOPS = (3, 4, 8, 9, 11)                       # backgrounds: played while $7C00 holds them
SILENT = (10,)                                 # elevator stage: no music
FX = (("coin_spring", "trig_3_coin_spring"), ("gorilla_fall", "trig_4_gorilla_fall"),
      ("barrel_prize", "trig_5_barrel_prize"), ("death", "death"))
DISCRETE = ("trig_0_walk", "trig_1_jump", "trig_2_stomp")


def load(name):
    w = wave.open(str(SRC / (name + ".wav")))
    r = w.getframerate()
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768.0, r


def lowpass(x, r, cut):
    return filtfilt(firwin(511, cut, fs=r), [1.0], x)


def period(x, r):
    """Loop period in (fractional) samples: the shortest strong autocorrelation peak, refined on a far multiple.
    (Out of time: 0.967 in the recordings of 2026-10-09 19:40, hence 0.96.)"""
    x = x[r:] - x[r:].mean()
    n = len(x)
    f = np.fft.rfft(x, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n] / np.arange(n, 0, -1)
    ac /= ac[0]
    lo, hi = int(0.3 * r), int(6 * r)
    peaks = [i for i in range(lo, hi) if ac[i] > 0.96 and ac[i] == ac[max(0, i - 300):i + 300].max()]
    p0 = peaks[0]
    k = (n // 2) // p0                         # the farthest multiple with enough overlap
    c = k * p0
    j = c - 50 + int(np.argmax(ac[c - 50:c + 51]))
    a, b, d = ac[j - 1], ac[j], ac[j + 1]
    return (j + 0.5 * (a - d) / (a - 2 * b + d)) / k, ac[p0]


def sample(spline, t0, step, n):
    return spline(t0 + step * np.arange(n))


def ensure():
    """For build.py: dk_sound.s / dk_sound.bin / dk_ym.s, recorded (MAME) and converted only when missing."""
    if not ((BUILD / "dk_sound.s").exists() and (BUILD / "dk_sound.bin").exists()):
        if not (SRC / "death.wav").exists():
            import sound_capture
            sound_capture.capture_all()
        build()
    if not (BUILD / "dk_ym.s").exists():
        import sound_ym                  # the YM patches of walk, jump and stomp
        sound_ym.main()


def build(rate=6258, verbose=False):
    clips = {}                                 # name -> (float samples at `rate`, loop)
    report = {}

    def prep(name):
        x, r = load(name)
        y = lowpass(x, r, 0.45 * rate)
        return x, y, r, CubicSpline(np.arange(len(y)), y)

    for n, tname in TUNES.items():
        key = "%02d_%s" % (n, tname)
        if n in SILENT:
            continue
        if n in LOOPS:
            x, y, r, sp = prep("held_" + key)
            p, q = period(x, r)
            m = int(round(p * rate / r / 2)) * 2
            loop = sample(sp, p, p / m, m)                     # the second period: past the start transient
            nxt = sample(sp, 2 * p, p / m, m)                  # the third, to check the loop against
            err = np.abs(loop - nxt).mean() / np.abs(loop).mean()
            clips["tune_" + key] = (loop, True)
            report["tune_" + key] = dict(loop_s=round(p / r, 5), samples=m, corr=round(float(q), 4),
                                         next_period_err=round(float(err), 4),
                                         rate_err_ppm=round((m / (p / r) / rate - 1) * 1e6))
        else:
            x, y, r, sp = prep("shot_" + key)
            end = spans(x, r)[-1][1] + 0.03
            out = sample(sp, 0, r / rate, int(end * rate))
            clips["tune_" + key] = (out, False)
            report["tune_" + key] = dict(length_s=round(len(out) / rate, 3))
    for fx, src in FX + tuple((d[7:], d) for d in DISCRETE):
        x, y, r, sp = prep(src)
        end = spans(x, r)[-1][1] + 0.03
        out = sample(sp, 0, r / rate, int(end * rate))
        clips[("disc_" if src in DISCRETE else "fx_") + fx] = (out, False)
        report[("disc_" if src in DISCRETE else "fx_") + fx] = dict(length_s=round(len(out) / rate, 3))

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
            reps = 3 if loop else 1
            o.setnchannels(1); o.setsampwidth(1); o.setframerate(rate)
            o.writeframes((np.tile(q, reps).astype(np.int16) + 128).astype(np.uint8).tobytes())
        report[name]["bytes"] = len(q)

    (BUILD / "dk_sound.bin").write_bytes(bytes(blob))
    lines = ["; generated by games/dkong/tools/sound_convert.py: 8 bit signed PCM, %d Hz" % rate,
             "; scale %.3f DMA steps per MAME level 1.0 (sound_ym.py sets the YM levels from it)" % scale,
             "SOUND_RATE\tequ\t%d" % rate,
             "SOUND_MODE\tequ\t$%02x\t\t; $ffff8921: mono, the rate" % (0x80 | {6258: 0, 12517: 1, 25033: 2, 50066: 3}[rate]), "", "\tsection\tdata,data", "\teven",
             "dk_sound:\tincbin\t\"dk_sound.bin\"", "dk_sound_end:", "\teven", "",
             "; $7C00 tune n: start, end (dk_sound relative), 1 = loop while held (0, 0 = silence)",
             "sound_tunes:"]
    for n in range(16):
        k = [k for k in offs if k.startswith("tune_%02d_" % n)]
        if k:
            s, e, lp = offs[k[0]]
            lines.append("\tdc.l\t%d,%d\n\tdc.w\t%d\t\t; %02X %s" % (s, e, int(lp), n, k[0][8:]))
        else:
            lines.append("\tdc.l\t0,0\n\tdc.w\t0\t\t; %02X -" % n)
    lines.append("; one-shot effects of the 8035 (pins $7D03-$7D05, $7D80) and the discrete references")
    for k, (s, e, lp) in offs.items():
        if not k.startswith("tune_"):
            lines.append("snd_%s:\tequ\t%d\nsnd_%s_end:\tequ\t%d" % (k, s, k, e))
    (BUILD / "dk_sound.s").write_text("\n".join(lines) + "\n")
    json.dump(report, open(SRC / "pcm" / "report.json", "w"), indent=1)

    if verbose:
        for k, v in report.items():
                print("%-26s %s" % (k, "  ".join("%s %s" % kv for kv in v.items())))
    disc = sum(e - s for k, (s, e, _) in offs.items() if k.startswith("disc_"))
    print("total %d bytes (%.1f s), of which discrete references %d; scale %.1f (peak %.3f)"
          % (len(blob), len(blob) / rate, disc, scale, peak))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=6258, choices=(6258, 12517, 25033, 50066))
    build(ap.parse_args().rate, verbose=True)


if __name__ == "__main__":
    main()
