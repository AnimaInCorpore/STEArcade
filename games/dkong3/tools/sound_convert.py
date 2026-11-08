"""Convert the MAME sound board recordings to STE DMA sound: 8 bit signed mono at 6258 Hz (after games/mario/tools/
sound_convert.py).

    python sound_convert.py [--rate 6258]     -> build/dkong3/dkong3_sound.bin, dkong3_sound.s, sound/pcm/*.wav

Input: build/dkong3/sound/*.wav from sound_capture.py --all (48 kHz): for each sound latch ($7C00, $7C80, $7D00) the
values the game sends in play (ref/sound_values.py):
  P_<latch>_<value>        the value for 3 frames, then 0: the pulse the game sends
  H_<latch>_<value>        the value held 5 s (the values the game holds for 30 frames or more: the tunes)
  S_<latch>_<hold>_<value> a tune's value held 1.5 s, the value of a superset (the tune's bits and an effect's) for 3 frames,
                           the tune again: S - H is the effect alone, on top of the tune that goes on
A value that is a hold value with a sound is a looping clip of its voice (H, 5 s; stops when the latch leaves the value);
a value that holds a hold value's bits and more is that tune plus an effect clip (S - H, the effect voice of the latch);
any other value is a one-shot clip (P, up to the end of its sound, at most the 4 s recorded).  A clip with no sound is no
clip.  One scale for all clips keeps the board's relative levels; the three voices (tune, effect, effect of the second CPU)
are added by the driver, so the peak is 56 of 127.
"""
import argparse, json, os, sys, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import build_dir
import sound_capture as sc
from sound_capture import spans

BUILD = build_dir("dkong3")
SRC = BUILD / "sound"
LATCHES = sc.LATCHES
PEAK = 56
SOUND_THRESH = 0.004                          # a recording with a peak below this is silent


def load(name):
    w = wave.open(str(SRC / (name + ".wav")))
    r = w.getframerate()
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768.0, r


def lowpass(x, r, cut):
    from scipy.signal import firwin, filtfilt
    return filtfilt(firwin(511, cut, fs=r), [1.0], x)


def ensure():
    """For build.py: dkong3_sound.s / .bin, recorded (MAME) and converted only when missing."""
    if not ((BUILD / "dkong3_sound.s").exists() and (BUILD / "dkong3_sound.bin").exists()):
        if not list(SRC.glob("P_*.wav")):
            if not list(BUILD.glob("sound_values_*.json")):
                sys.exit("sound_convert: no build/dkong3/sound_values_*.json: python games/dkong3/ref/sound_values.py <seed> 40000 (seeds 1-8)")
            sc.capture_all()
        build()


def build(rate=6258, verbose=False):
    from scipy.interpolate import CubicSpline
    obs = sc.observed()
    clips = []                                 # (name, samples at `rate`, loops from its start, the sample a loop of a sustained sound starts at)
    tabs = {}                                  # (latch, 'hold' | 'eff') -> {value: clip number}
    names = {}

    def resample(x, r, t0, t1):
        y = lowpass(x, r, 0.45 * rate)
        sp = CubicSpline(np.arange(len(y)), y)
        n = int((t1 - t0) * rate)
        return sp(r * t0 + r / rate * np.arange(n))

    def sounds(name):
        x, r = load(name)
        return np.abs(x).max() >= SOUND_THRESH

    def add(name, c, loops, loop_at=0):
        clips.append((name, c, loops, loop_at))
        return len(clips)                      # (clip numbers start at 1)

    for a in LATCHES:
        vals = sorted(obs[a])
        holds = {}
        for v in vals:
            if obs[a][v] >= 30 and (SRC / ("H_%04x_%02x.wav" % (a, v))).exists():
                x, r = load("H_%04x_%02x" % (a, v))
                if np.abs(x[int(4.2 * r):int(4.9 * r)]).max() >= SOUND_THRESH:      # (sounds until its 5 s: held)
                    holds[v] = x
        hold_tab, eff_tab = {}, {}
        for v in vals:
            if v in holds:
                x = holds[v]
                n = add("hold_%04x_%02x" % (a, v), resample(x, 48000, 0.0, 5.0), True)
                hold_tab[v] = n
                continue
            base = max((h for h in holds if v & h == h and v != h), key=lambda h: bin(h).count("1"), default=None)
            if base is not None and (SRC / ("S_%04x_%02x_%02x.wav" % (a, base, v))).exists():
                s, r = load("S_%04x_%02x_%02x" % (a, base, v))
                d = s[:len(holds[base])] - holds[base][:len(s)] if len(s) >= len(holds[base]) else s - holds[base][:len(s)]
                t0 = 1.45                      # the effect starts at 1.5 s
                seg = d[int(t0 * r):int(5.0 * r)]
                sp_ = spans(np.pad(seg, (0, int(0.1 * r))), r, thresh=0.003)
                if not sp_:
                    continue
                end = min(sp_[-1][1] + 0.03, 3.5)
                if np.abs(seg).max() < SOUND_THRESH:
                    continue
                eff_tab[v] = add("eff_%04x_%02x_%02x" % (a, base, v), resample(d, r, t0, t0 + end), False)
                hold_tab[v] = hold_tab[base]
                continue
            if not sounds("P_%04x_%02x" % (a, v)):
                continue
            x, r = load("P_%04x_%02x" % (a, v))
            sp_ = spans(x, r)
            tail = np.sqrt((x[int(11 * r):int(14 * r)] ** 2).mean())
            if tail >= SOUND_THRESH:                        # a sound that goes on: a loop of its steady part
                n, loop_at = sustained(x, r, rate)
                eff_tab[v] = add("keep_%04x_%02x" % (a, v), resample(x, r, 0.0, n / rate), False, loop_at)
                continue
            end = min(sp_[-1][1] + 0.03, 14.0)
            eff_tab[v] = add("fx_%04x_%02x" % (a, v), resample(x, r, 0.0, end), False)
        tabs[(a, "hold")] = hold_tab
        tabs[(a, "eff")] = eff_tab
    peak = max(np.abs(c).max() for _, c, _, _ in clips)
    scale = PEAK / peak
    pcm_dir = SRC / "pcm"
    pcm_dir.mkdir(parents=True, exist_ok=True)
    blob = bytearray(4)                        # (offset 0 means no loop)
    offs = []
    report = {}
    for name, c, loops, loop_at in clips:
        c = c.copy()
        f = min(len(c), int(0.004 * rate))                # 4 ms fade out, then an even length (DMA works on words)
        c[len(c) - f:] *= np.linspace(1, 0, f)
        q = np.clip(np.round(c * scale), -128, 127).astype(np.int8)
        if len(q) & 1:
            q = np.append(q, np.int8(0))
        offs.append((len(blob), len(blob) + len(q), loops, loop_at))
        blob += q.tobytes()
        with wave.open(str(pcm_dir / (name + ".wav")), "wb") as o:   # listening copy, 8 bit as the STE plays it
            o.setnchannels(1); o.setsampwidth(1); o.setframerate(rate)
            o.writeframes((q.astype(np.int16) + 128).astype(np.uint8).tobytes())
        report[name] = dict(bytes=len(q), seconds=round(len(q) / rate, 2), loops=loops, loop_at=loop_at)
    (BUILD / "dkong3_sound.bin").write_bytes(bytes(blob))
    lines = ["; generated by games/dkong3/tools/sound_convert.py: 8 bit signed PCM, %d Hz, %d clips" % (rate, len(clips)),
             "SOUND_RATE\tequ\t%d" % rate,
             "SOUND_MODE\tequ\t$%02x\t\t; $ffff8921: mono, the rate" % (0x80 | {6258: 0, 12517: 1, 25033: 2, 50066: 3}[rate]),
             "", "\tsection\tdata,data", "\teven",
             "dk_sound:\tincbin\t\"dkong3_sound.bin\"", "dk_sound_end:", "\teven", "",
             "; clip number (1 up): start, end, loop start (dk_sound relative; 0: none: a tune loops from its start, a sound that goes on from its steady part)",
             "snd_clips:", "\tdc.l\t0,0,0"]
    for s, e, lp, la in offs:
        lines.append("\tdc.l\t%d,%d,%d" % (s, e, s if lp else (s + la if la else 0)))
    lines.append("snd_clipkind:			; per clip: 1 = a sound that goes on (its own voice)")
    kinds = [0] + [1 if c[3] else 0 for c in clips]
    for r0 in range(0, len(kinds), 16):
        lines.append("	dc.b	" + ",".join(str(k) for k in kinds[r0:r0 + 16]))
    lines.append("	even")
    for k, a in enumerate(LATCHES):
        for kind in ("hold", "eff"):
            lines.append("; latch %d ($%04X), %s: value -> clip number (0: none)" % (k + 1, a, "the tune a value holds" if kind == "hold"
                                                                                  else "the effect a value starts"))
            lines.append("snd_%s%d:" % (kind, k + 1))
            tab = tabs[(a, kind)]
            for r0 in range(0, 256, 16):
                lines.append("\tdc.b\t" + ",".join(str(tab.get(v, 0)) for v in range(r0, r0 + 16)))
    lines.append("\teven")
    (BUILD / "dkong3_sound.s").write_text("\n".join(lines) + "\n")
    json.dump(dict(clips=report, tabs={"%04x_%s" % (a, k): {str(v): n for v, n in t.items()} for (a, k), t in tabs.items()}),
              open(pcm_dir / "report.json", "w"), indent=1)
    if verbose:
        for k, v in report.items():
            print("%-24s %s" % (k, "  ".join("%s %s" % kv for kv in v.items())))
    print("%d clips, total %d bytes (%.1f s); scale %.1f (peak %.3f)" % (len(clips), len(blob), len(blob) / rate, scale, peak))


def sustained(x, r, rate):
    """a sound that goes on to the end of the recording: -> (the samples to keep at `rate`, the sample its loop starts at): the
    start of its steady part and one or more whole periods of it (autocorrelation of the tail)"""
    win = int(0.25 * r)
    rms = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
    ref = rms[-8:].mean()
    steady = np.abs(rms - ref) <= 0.2 * ref
    k = len(steady) - 1
    while k > 0 and steady[k - 1]:
        k -= 1
    s0 = max(k * win, int(1.0 * r))
    tail = x[len(x) - int(3 * r):]
    tail = tail - tail.mean()
    maxlag = int(2.5 * r)
    n = len(tail)
    f = np.fft.rfft(tail, 2 * n)
    c = np.fft.irfft(f * np.conj(f))[:n]
    c /= c[0] if c[0] else 1
    lo, hi = int(0.02 * r), min(int(2.5 * r), n // 2)
    lag = lo + int(np.argmax(c[lo:hi]))
    period = lag / r
    if c[lag] < 0.5:                                   # no period: a noise-like sound: a long loop of its steady part
        period = 1.0
    reps = max(1, int(np.ceil(1.0 / period)))
    length = period * reps
    end_t = s0 / r + length
    return int(end_t * rate), int(s0 / r * rate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=6258, choices=(6258, 12517, 25033, 50066))
    build(ap.parse_args().rate, verbose=True)


if __name__ == "__main__":
    main()
