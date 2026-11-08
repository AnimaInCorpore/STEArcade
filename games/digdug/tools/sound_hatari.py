"""The STE program's sound in Hatari against MAME's audio: the program with -D SNDTEST=<first VBL> sets the sound CPU's
command cells of the sound ids 9-15, 18 and 19 (the ones tools/sound_mame.py hears in MAME) one every 120 VBLs, Hatari plays
the YM2149 (--sound 44100) and records its audio in an AVI (--avirecord, fast forward), ffmpeg extracts it, and the pieces'
spectra are compared with MAME's (the file sound_mame.py wrote for the same ids), aligned at the first sound.

    python sound_hatari.py        (runs sound_mame.py 9 10 11 12 13 14 15 18 19 first when build/digdug/sound_mame.wav is not
                                   from those ids: delete it to redo)

The STE runs at 50 VBLs a second against the arcade's 60.6 frames: the tunes are slower by that factor (the pitches are not).
"""
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "..", "..", "engine")]
import sound_mame as sm
from paths import ROOT, build_dir

IDS = [9, 10, 11, 12, 13, 14, 15, 18, 19]
FIRST = 1300
HATARI = r"C:\Arbeit\F030Arcade\third_party\hatari\build-ucrt64\src\hatari.exe"
TOS = r"C:\Arbeit\F030Arcade\third_party\tos\tos206de.img"
RATE = sm.RATE


def hatari_audio():
    run = ROOT / "run" / "digdug_sndtest"
    run.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "build.py"), "-D", "SNDTEST=%d" % FIRST, "--out", str(run / "DIGDUG.PRG")],
                   check=True, stdout=subprocess.DEVNULL)
    avi = run / "snd.avi"
    if avi.exists():
        avi.unlink()
    env = dict(os.environ, PATH=r"C:\msys64\ucrt64\bin;" + os.environ["PATH"])
    vbls = FIRST + 120 * len(IDS) + 200
    subprocess.run([HATARI, "--machine", "ste", "--memsize", "4", "--tos", TOS, "--fast-boot", "true", "--cpu-exact", "true",
                    "--compatible", "true", "--sound", "44100", "--confirm-quit", "off", "--statusbar", "false",
                    "--fast-forward", "true", "--run-vbls", str(vbls), "--avirecord", "true", "--avi-vcodec", "bmp",
                    "--avi-fps", "5", "--avi-file", str(avi), "--log-file", str(run / "hatari.log"), str(run / "DIGDUG.PRG")],
                   cwd=run, env=env, timeout=900, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wav = run / "snd.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(avi), "-vn", "-ac", "1", "-ar", str(RATE), str(wav)], check=True)
    w = wave.open(str(wav))
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float) / 32768
    avi.unlink()
    return x


def onset(x, thr=0.002):
    step = RATE // 20
    for i in range(0, len(x) - step, step):
        if np.sqrt((x[i:i + step] ** 2).mean()) > thr:
            return i
    raise SystemExit("no sound found")


def main():
    mame_wav = build_dir("digdug") / "sound_mame.wav"
    if not mame_wav.exists():
        subprocess.run([sys.executable, os.path.join(HERE, "sound_mame.py")] + [str(i) for i in IDS], check=True)
    w = wave.open(str(mame_wav))
    mame = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float) / 32768
    ste = hatari_audio()
    with wave.open(str(build_dir("digdug") / "sound_hatari.wav"), "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(RATE)
        o.writeframes((np.clip(ste, -1, 1) * 32767).astype(np.int16).tobytes())
    om, os_ = onset(mame), onset(ste)
    print("first sound: MAME %.2f s, Hatari %.2f s (audio of %.1f s)" % (om / RATE, os_ / RATE, len(ste) / RATE))
    print("%-4s %-10s %-10s %7s %7s %7s" % ("id", "MAME", "Hatari", "cents", "cosine", "chroma"))
    good = 0
    k0 = int(round((om / RATE * sm.FPS - sm.START) / sm.STEP))      # (the piece the first sound belongs to: the same one in Hatari)
    print("the first sound is the piece of id %d" % IDS[k0])
    for k, i in enumerate(IDS):
        a = om + int((k - k0) * sm.STEP / sm.FPS * RATE)
        b = os_ + int((k - k0) * 120 / 50.0 * RATE)
        if a < 0 or b < 0:
            continue
        xm, xs = mame[a:a + 2 * RATE], ste[b:b + 2 * RATE]
        s1, s2 = sm.semitones(xm), sm.semitones(xs)
        pm, ps = sm.peak(xm), sm.peak(xs)
        if not pm and not ps:
            continue
        c0, ch = sm.cosine(s1, s2), sm.cosine(sm.chroma(s1), sm.chroma(s2))
        cents = 1200 * np.log2(ps / pm) if pm and ps else float("nan")
        print("%-4d %7.0f Hz %7.0f Hz %7.0f %7.2f %7.2f" % (i, pm, ps, cents, c0, ch))
        good += bool(pm and ps and c0 > 0.7)
    print("%d pieces alike (semitone spectra cosine > 0.7); the pieces of ids that are silent in both are not listed" % good)


if __name__ == "__main__":
    main()
