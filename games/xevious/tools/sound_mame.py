"""Super Xevious's sound on the STE against MAME's audio (the check of docs/porting-guide.md, "-wavwrite").

    python sound_mame.py mame  [DIR]                 MAME (sxevious, WolfMAME 0.248; MAME=<exe>) inserts a coin at frame
                                                     1200, presses start at 1300 and fires from 1500 to frame 3600;
                                                     -wavwrite DIR/mame.wav (default DIR: F:/claude/tmp/xevious/mame)
    python sound_mame.py ste   STE.wav [MAME.wav]    the dominant notes and levels of the start jingle in both files

The STE side: tools/hatari.ps1 -Frames 800 -Every 100000 -Name xevious_snd -Sound 44100 -AviFps 2 -Extra @('-D','AUTOPLAY=1',
'-D','AP_COIN=60','-D','RATE=250'), then `ffmpeg -i run/xevious_snd/xevious.avi -vn ste.wav` and delete the AVI (it is ~1.5 GB
for 24 s: the borders' bitmaps; Hatari's png codec does not start).  The STE runs the arcade at ~half speed: the jingle takes
twice as long, the notes are the same.  The 54XX's effects and the PROM waveforms' harmonics are not on the STE.
"""
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine")]
MAME = os.environ.get("MAME") or r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe"
LUA = """
local m = manager.machine
local in1 = m.ioport.ports[":IN1"].fields
local frame = 0
emu.register_frame_done(function()
  frame = frame + 1
  in1["Coin 1"]:set_value((frame >= 1200 and frame < 1205) and 1 or 0)
  in1["1 Player Start"]:set_value((frame >= 1300 and frame < 1305) and 1 or 0)
  in1["P1 Button 1"]:set_value((frame > 1500 and frame %% 10 < 3) and 1 or 0)
  if frame >= 3600 then m:exit() end
end)
"""


def run_mame(d):
    import mamewin
    from paths import ROMS
    d = Path(d)
    (d / "roms").mkdir(parents=True, exist_ok=True)
    for z in ("sxevious.zip", "namco50.zip", "namco51.zip", "namco54.zip"):
        shutil.copy(ROMS / z, d / "roms" / z)
    (d / "cap.lua").write_text(LUA)
    mamewin.run([MAME, "sxevious", "-rompath", str(d / "roms"), "-video", "none", "-nothrottle", "-skip_gameinfo", "-samplerate",
                 "22050", "-wavwrite", str(d / "mame.wav"), "-autoboot_script", str(d / "cap.lua"), "-seconds_to_run", "90"],
                cwd=os.path.dirname(MAME), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load(p):
    w = wave.open(str(p))
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels()).astype(float).mean(axis=1) / 32768, w.getframerate()


def notes(x, r, t0, t1):
    """semitone (from 55 Hz) -> windows of 0.2 s it is the loudest peak (100 Hz - 1.2 kHz), and the median RMS"""
    h, rms, st = {}, [], int(0.2 * r)
    for i in range(int(t0 * r), int(t1 * r) - st, st):
        s = x[i:i + st]
        rms.append(np.sqrt((s ** 2).mean()))
        sp = np.abs(np.fft.rfft(s * np.hanning(len(s)), 1 << 15))
        f = np.fft.rfftfreq(1 << 15, 1 / r)
        sp[(f < 100) | (f > 1200)] = 0
        if sp.max() > 0 and rms[-1] > 0.01:
            k = int(round(12 * np.log2(f[int(np.argmax(sp))] / 55.0)))
            h[k] = h.get(k, 0) + 1
    return sorted(h.items(), key=lambda kv: -kv[1])[:8], float(np.median(rms))


def onset(x, r):
    """the first second (from the start) whose RMS exceeds 0.01 after the MAME boot's blip (2 s)"""
    for i in range(int(2 * r), len(x) - r // 5, r // 5):
        if np.sqrt((x[i:i + r // 5] ** 2).mean()) > 0.01:
            return i / r
    return 0.0


if __name__ == "__main__":
    if sys.argv[1] == "mame":
        run_mame(sys.argv[2] if len(sys.argv) > 2 else r"F:\claude\tmp\xevious\mame")
    else:
        for name, p, span in (("STE", sys.argv[2], 15.0), ("MAME", sys.argv[3] if len(sys.argv) > 3 else r"F:\claude\tmp\xevious\mame\mame.wav", 8.3)):
            x, r = load(p)
            t0 = onset(x, r)
            top, rms = notes(x, r, t0, t0 + span)
            print("%s: sound from %.1f s; median RMS %.3f; notes (semitone from 55 Hz, Hz: windows): %s" % (
                name, t0, rms, ", ".join("%d (%.0f): %d" % (k, 55 * 2 ** (k / 12), c) for k, c in top)))
