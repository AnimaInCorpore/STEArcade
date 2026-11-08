"""Hatari's audio against MAME's for the attract mode (nobody listens: levels and pitches by window).

    python games/mikie/ref/wav_cmp.py <hatari.wav> <mame.wav> [--win 0.25]

Per window of --win seconds from each recording's first sound: the RMS level (dB below full scale) and the dominant
frequency (Hz, FFT peak).  The two recordings start at different moments (MAME's self-test, Hatari's boot): the first
window above -60 dB is time 0 of each.  Prints the two series side by side and the share of windows whose dominant pitch
agrees within 3% (the YM has 3 of the 8 SN voices and its own envelope steps: levels are compared in dB, not required equal).
"""
import sys
import wave
import numpy as np


def load(path):
    w = wave.open(path)
    n, ch, sw, fr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    a = np.frombuffer(w.readframes(n), dtype='<i2' if sw == 2 else '<i4').astype(np.float64)
    a = a.reshape(-1, ch).mean(axis=1) / (32768.0 if sw == 2 else 2147483648.0)
    return a, fr


def series(a, fr, win):
    k = int(fr * win)
    out = []
    for i in range(0, len(a) - k, k):
        s = a[i:i + k]
        s = s - s.mean()
        rms = np.sqrt((s * s).mean())
        db = 20 * np.log10(rms + 1e-9)
        if db < -70:
            out.append((db, 0.0))
            continue
        sp = np.abs(np.fft.rfft(s * np.hanning(len(s))))
        lo = int(60 * len(s) / fr)                       # (below 60 Hz: the chips' DC steps, not pitch)
        out.append((db, float(np.argmax(sp[lo:]) + lo) * fr / len(s)))
    return out


def trim(sr):
    for i, (db, f) in enumerate(sr):
        if db > -60:
            return sr[i:]
    return sr


def main():
    win = float(sys.argv[sys.argv.index('--win') + 1]) if '--win' in sys.argv else 0.25
    args = [x for x in sys.argv[1:] if not x.startswith('--') and x != str(win)]
    h = series(*load(args[0]), win)
    m = series(*load(args[1]), win)
    best = (-1, 0)
    for off in range(-int(12 / win), int(24 / win)):          # (MAME's recording has the self-test first: shift to the best fit)
        a = b = 0
        for i in range(len(h)):
            j = i + off
            if 0 <= j < len(m) and h[i][1] and m[j][1]:
                b += 1
                a += abs(h[i][1] - m[j][1]) <= 0.03 * m[j][1]
        if a > best[0]:
            best = (a, off)
    off = best[1]
    print('best alignment: MAME %+.2f s against Hatari' % (off * win))
    h = h[max(0, -off):]
    m = m[max(0, off):]
    n = min(len(h), len(m), int(30 / win))
    agree = both = 0
    for i in range(n):
        (dh, fh), (dm, fm) = h[i], m[i]
        ok = ''
        if fh and fm:
            both += 1
            if abs(fh - fm) <= 0.03 * fm:
                agree += 1
                ok = '='
        print('%5.2fs  hatari %6.1f dB %7.1f Hz   mame %6.1f dB %7.1f Hz %s' % (i * win, dh, fh, dm, fm, ok))
    print('windows with sound in both: %d, pitch within 3%%: %d (%.0f%%); mean level difference %.1f dB' % (
        both, agree, 100.0 * agree / max(1, both),
        np.mean([h[i][0] - m[i][0] for i in range(n) if h[i][1] and m[i][1]] or [0])))


if __name__ == '__main__':
    main()
