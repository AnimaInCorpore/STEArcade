"""Galaga sound: the logged WSG writes (ref/sound1.py) rendered three ways, to hear what the STE can do.

    python ref/sound2.py [start frame] [frames]   -> build/galaga/sound/{wsg,ym,dma6258}_<start>.wav

  wsg      the Namco WSG as MAME computes it (namco.cpp: 192 kHz, 20 bit frequency, counter >> 16 & 31 picks
           one of the 32 4 bit samples of the PROM's waveform, (sample - 8) * volume), at 48 kHz
  ym       each voice a YM square at the same pitch, its loudness matched to the voice's RMS (YM volumes of
           Hatari's measured table), the registers updated once a 50 Hz frame as an STE driver would
  dma6258  the WSG output low-passed, at 6258 Hz and 8 bit: what DMA sound would play
"""
import os, pickle, sys, wave
import numpy as np
from scipy.signal import resample_poly, firwin, filtfilt
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import CYCLES_PER_FRAME
from paths import build_dir, EXTRACTED

OUT = build_dir("galaga") / "sound"
RATE = 48000
FPS = 3072000 / CYCLES_PER_FRAME
PROM = open(EXTRACTED / "galaga" / "prom-1.1d", "rb").read()
WAVES = np.array([[(b & 15) - 8 for b in PROM[w * 32:w * 32 + 32]] for w in range(8)], np.float64)
YM_LEVEL = np.array([0, 30, 63, 97, 150, 211, 316, 434, 638, 876, 1296, 1775, 2608, 3682, 5769, 8672], float)


def voice_params(regs, v):
    f = (regs[0x10] if v == 0 else 0) + (regs[v * 5 + 0x11] << 4) + (regs[v * 5 + 0x12] << 8) + \
        (regs[v * 5 + 0x13] << 12) + (regs[v * 5 + 0x14] << 16)
    return f, regs[v * 5 + 0x15], regs[v * 5 + 0x05] & 7


def segments(log, f0, nf):
    """The register state over time: [(t0 s, t1 s, regs)] from the first write at or after frame f0."""
    regs = [0] * 32
    ev = log["wsg"]
    out = []
    t_prev = 0.0
    for fr, cyc, r, v in ev:
        t = (fr - f0) + cyc / CYCLES_PER_FRAME
        if t >= nf:
            break
        if t > t_prev and fr >= f0:
            out.append((t_prev / FPS, t / FPS, list(regs)))
            t_prev = t
        elif fr < f0:
            t_prev = 0.0
        regs[r] = v
    out.append((t_prev / FPS, nf / FPS, list(regs)))
    return out


def render_wsg(segs, n):
    """MAME's algorithm at 192 kHz, then down to RATE."""
    hi = 192000
    y = np.zeros(int(n * hi / RATE) + 1)
    cnt = [0, 0, 0]
    for t0, t1, regs in segs:
        a, b = int(t0 * hi), int(t1 * hi)
        if b <= a:
            continue
        k = np.arange(1, b - a + 1, dtype=np.int64)
        for v in range(3):
            f, vol, w = voice_params(regs, v)
            c = cnt[v] + f * k
            if vol and f:
                y[a:b] += WAVES[w][(c >> 16) & 31] * vol
            cnt[v] = int(c[-1]) & 0xFFFFFFF
    return resample_poly(y, 1, 4)[:n] / (8 * 15 * 3)      # full scale: three voices at volume 15


def render_ym(segs, n):
    """Per 50 Hz frame: the state at the frame start; per voice a square, RMS matched; phase continuous."""
    y = np.zeros(n)
    frame = RATE // 50
    ph = [0.0, 0.0, 0.0]
    si = 0
    wave_rms = np.sqrt((WAVES ** 2).mean(1))
    for i in range(n // frame):
        t = i / 50
        while si + 1 < len(segs) and segs[si + 1][0] <= t:
            si += 1
        regs = segs[si][2]
        for v in range(3):
            f, vol, w = voice_params(regs, v)
            if not (vol and f):
                continue
            hz = f * 192000 / 2 ** 21
            per = max(1, round(125000 / hz))                   # YM: 2 MHz / 16 / period
            hz = 125000 / per
            target = wave_rms[w] * vol / (8 * 15 * 3)          # the WSG voice's RMS on the WSG scale
            # YM square 0..L: RMS L/2; one scale for all: YM volume 15 = the WSG's loudest voice (15, rms 8)
            lv = YM_LEVEL / YM_LEVEL[15] * (8 / (8 * 3)) * 2
            ymv = int(np.argmin(np.abs(np.log((lv[1:] / 2) / target)))) + 1
            tt = ph[v] + hz * np.arange(1, frame + 1) / RATE
            y[i * frame:(i + 1) * frame] += np.where(tt % 1 < 0.5, 1.0, -1.0) * lv[ymv] / 2
            ph[v] = tt[-1] % 1
    return y


def to_dma(y, rate=6258):
    lo = filtfilt(firwin(255, 0.45 * rate, fs=RATE), [1.0], y)
    d = resample_poly(lo, rate, RATE)
    q = np.clip(np.round(d / np.abs(d).max() * 127), -128, 127) / 127 * np.abs(d).max()
    return resample_poly(q, RATE, rate)[:len(y)]


def write(name, y):
    y = y / max(np.abs(y).max(), 1e-9) * 0.9
    with wave.open(str(OUT / name), "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(RATE)
        o.writeframes((y * 32767).astype(np.int16).tobytes())


def main():
    f0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2436
    nf = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    log = pickle.load(open(OUT / "log.pkl", "rb"))
    segs = segments(log, f0, nf)
    n = int(nf / FPS * RATE)
    w = render_wsg(segs, n)
    y = render_ym(segs, n)
    d = to_dma(w)
    for name, s in (("wsg", w), ("ym", y), ("dma6258", d)):
        write("%s_%d.wav" % (name, f0), s)
    def bands(s):
        sp = np.abs(np.fft.rfft(s)) ** 2; f = np.fft.rfftfreq(len(s), 1 / RATE)
        return [round(float(100 * sp[(f >= a) & (f < b)].sum() / sp.sum()), 1)
                for a, b in ((0, 500), (500, 1000), (1000, 2000), (2000, 3000), (3000, 6000), (6000, 24000))]
    print("energy %: <500 500-1k 1-2k 2-3k 3-6k >6k Hz")
    for name, s in (("wsg", w), ("ym", y), ("dma6258", d)):
        print("%-8s %s" % (name, bands(s)))
    err = d - w
    print("dma6258 vs wsg: SNR %.1f dB" % (10 * np.log10((w ** 2).sum() / (err ** 2).sum())))


if __name__ == "__main__":
    main()
