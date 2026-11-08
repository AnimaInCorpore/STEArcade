"""Hatari's audio against MAME's for the same sound commands (nobody listens: levels, timing, which commands play).

    python sound_hatari.py <run dir with sbasketb.avi (hatari.ps1 -Sound 44100) and SNDLOG.BIN> [mame wav]

SNDLOG.BIN: (the VBL, the command) words the program's sound driver took (DEBUG builds).  The MAME wav is
recorded here by MAME (sound_capture.capture) from the commands the program logged, at the same times.  For each command: the RMS of the first 0.25 s (to the next command) in both recordings, in 16-bit units, and
how often Hatari is silent where MAME is not.
"""
import collections, os, struct, subprocess, sys, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import build_dir


def load(p):
    w = wave.open(str(p))
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels()).astype(float).mean(1)
    return x - np.median(x), w.getframerate()      # (the DAC's rest level removed)


def main():
    d = sys.argv[1]
    raw = open(os.path.join(d, "SNDLOG.BIN"), "rb").read()
    log = [struct.unpack(">HH", raw[i:i + 4]) for i in range(0, len(raw), 4)]
    # MAME gets the program's own commands at the same times (an arcade frame is 1 / 60 s, a VBL 1 / 50 s)
    ev = [(int(round(v * 1.2)), c) for v, c in log]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sound_capture
    name = "seq_" + os.path.basename(os.path.normpath(d))
    mame = str(build_dir("sbasketb") / "sound" / (name + ".wav"))
    if len(sys.argv) < 3:
        sound_capture.capture(name, " ".join("%d:%d" % e for e in ev), ev[-1][0] / 60.0 + 4.0)
    else:
        mame = sys.argv[2]
    wav = os.path.join(d, "hatari.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(d, "sbasketb.avi"), "-vn", "-ac", "1", wav], check=True)
    h, hr = load(wav)
    m, mr = load(mame)
    n = min(len(log), len(ev))
    cmds = [c for _, c in log[:n]]
    if cmds != [c for _, c in ev[:n]]:
        bad = next(i for i in range(n) if cmds[i] != ev[i][1])
        print("warning: the program's commands differ from the reference's at #%d: %s / %s" % (bad, log[bad], ev[bad]))
        n = bad
    tv = np.array([v for v, _ in log[:n]]) / 50.0       # the VBL counts: Hatari's audio time (+ an offset found below)
    tm = 1.0 + np.array([f for f, _ in ev[:n]]) / 60.0   # MAME's capture starts one settle second before frame 0

    def rms(x, r, t0, t1):
        a, b = int(t0 * r), int(t1 * r)
        seg = x[a:b]
        return float(np.sqrt((seg ** 2).mean())) if len(seg) else 0.0
    best = max(np.arange(0.0, 20.0, 0.02), key=lambda o: sum(rms(h, hr, t + o, t + o + 0.1) for t in tv[:200]))
    print("Hatari audio %.1f s, MAME %.1f s, %d commands compared; the VBL clock's offset to the audio: %.2f s" % (
        len(h) / hr, len(m) / mr, n, best))
    stats = collections.defaultdict(list)
    for i in range(n):
        gap_h = min(0.25, (tv[i + 1] - tv[i]) if i + 1 < n else 0.25)
        gap_m = min(0.25, (tm[i + 1] - tm[i]) if i + 1 < n else 0.25)
        g = min(gap_h, gap_m)
        if g < 0.04:
            continue
        stats[cmds[i]].append((rms(h, hr, tv[i] + best, tv[i] + best + g), rms(m, mr, tm[i], tm[i] + g)))
    print("command  n   Hatari rms  MAME rms  ratio   Hatari silent / MAME audible")
    for c in sorted(stats):
        a = np.array(stats[c])
        mh, mm = a[:, 0].mean(), a[:, 1].mean()
        sil = int(((a[:, 0] < 50) & (a[:, 1] > 200)).sum())
        print("  $%02X  %3d  %9.0f  %9.0f  %5.2f   %d / %d" % (c, len(a), mh, mm, mh / mm if mm else 0, sil, int((a[:, 1] > 200).sum())))


if __name__ == "__main__":
    main()
