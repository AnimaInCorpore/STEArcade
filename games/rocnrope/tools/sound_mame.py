"""The pitches of Roc'n Rope's sound on the STE's YM2149 against MAME's audio (docs/porting-guide.md, "-wavwrite",
semitone spectra).

    python sound_mame.py [ids ...] [--keep DIR]          (default: the commands the game sends)

MAME (MAME=<exe>, default WolfMAME 0.248, Demo Sounds off; -wavwrite, -video none) runs the game from power-on; at frame
START + STEP k the script writes the command to the sound latch ($8100) and pulses the main latch's Q1 ($8081 0 then 1:
the rising edge raises the sound CPU's IRQ), once for each command of the list.  The STE's board model (tools/sound.py
STEBoard: the translated driver, the AYs, the YM mix-down) gets the same commands at the same frames, and the YM registers
it writes each frame are rendered as square waves (2 MHz / 16 / period, 3 dB a level).  Per piece the two audio
signals' semitone spectra (55 Hz - 3.5 kHz) are compared: the cosine of the spectra and of their chroma and the loudest
peak of each in Hz (cents apart).  Writes build/rocnrope/sound_mame.wav and sound_ste.wav.  Nobody listened to either.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "..", "..", "engine")]
from sound import STEBoard
import mamewin
from paths import ROMS, build_dir

MAME = os.environ.get("MAME") or r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe"
FPS = 6144000 / (384 * 264)              # 60.606 Hz
RATE = 22050
START = 600                              # the first poke (frames after power-on; the attract mode's own sounds are over)
STEP = 120
YM_CLOCK = 2000000

# the commands the game sends in play (ref/cover.py seed 12: counts over 14000 frames), most with a tune or effect
IDS = [1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 16, 17, 19, 25, 26, 27, 28, 29, 30, 31, 32, 36, 42]


def pokes(ids):
    """(frame, address, value): the command into the latch, Q1 low and high"""
    out = []
    for k, i in enumerate(ids):
        f = START + STEP * k
        out += [(f, 0x8100, i), (f, 0x8081, 0), (f, 0x8081, 1)]
    return out


LUA = """
local m = type(manager.machine) == "function" and manager:machine() or manager.machine
local cpu = m.devices[":maincpu"]
local sp = cpu.spaces["program"]
local ev = {%(events)s}
local frame, i = 0, 1
for _, port in pairs(m.ioport.ports) do                 -- Demo Sounds off (the attract mode's tune would mix into the pieces)
  for name, fld in pairs(port.fields) do
    if name == "Demo Sounds" then fld.user_value = 0x80 end
  end
end
emu.register_frame_done(function()
  frame = frame + 1                       -- (the frame that just ended; the pokes land at the start of the next)
  while ev[i] and ev[i][1] <= frame do
    sp:write_u8(ev[i][2], ev[i][3])
    i = i + 1
  end
  if frame >= %(last)d then m:exit() end
end)
"""


def mame_audio(ev, seconds, keep):
    tmp = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="rocnrope_snd_"))
    tmp.mkdir(parents=True, exist_ok=True)
    roms = tmp / "roms"
    roms.mkdir(exist_ok=True)
    for z in ("rocnrope.zip",):
        shutil.copy(ROMS / z, roms / z)
    lua = tmp / "cap.lua"
    lua.write_text(LUA % dict(events=", ".join("{%d, 0x%x, %d, 0}" % e for e in ev), last=int(seconds * FPS)))
    raw = tmp / "raw.wav"
    mamewin.run([MAME, "rocnrope", "-rompath", str(roms), "-video", "none", "-nothrottle", "-skip_gameinfo", "-samplerate",
                 str(RATE), "-wavwrite", str(raw), "-autoboot_script", str(lua), "-seconds_to_run", str(int(seconds))],
                cwd=os.path.dirname(MAME), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    w = wave.open(str(raw))
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels())[:, 0].astype(float) / 32768
    return x


def ref_registers(ev, frames):
    """the YM registers 0-13 per frame (the STE's board: the same commands one frame at a time)"""
    by_frame = {}
    for f, a, v in ev:
        if a == 0x8100:
            by_frame.setdefault(f, []).append(v)
    b = STEBoard()
    regs, out = [0] * 16, []
    for f in range(frames):
        b.run_frame(by_frame.get(f, []))
        for r, v in b.ym_log[-1]:
            regs[r] = v
        out.append(list(regs))
    return out


def synth(regs):
    """square waves of the YM's three channels, a frame of registers at a time"""
    ph = [0.0, 0.0, 0.0]
    out = []
    n0 = 0
    for k, r in enumerate(regs):
        n1 = int(round((k + 1) * RATE / FPS))
        n = n1 - n0
        n0 = n1
        buf = np.zeros(n)
        for ch in range(3):
            lvl = r[8 + ch] & 15
            period = r[2 * ch] | (r[2 * ch + 1] & 15) << 8
            if r[7] >> ch & 1 or lvl == 0 or period == 0:
                continue
            f = YM_CLOCK / (16.0 * period)
            t = ph[ch] + f * np.arange(n) / RATE
            buf += (2.0 ** ((lvl - 15) / 2.0)) * np.where((t % 1.0) < 0.5, 1.0, -1.0) * 0.25
            ph[ch] = (ph[ch] + f * n / RATE) % 1.0
        out.append(buf)
    return np.concatenate(out)


SEMI = np.arange(72)                    # 55 Hz * 2^(k/12)


def semitones(x):
    n = len(x)
    if n < 1024:
        return np.zeros(72)
    w = np.hanning(n)
    spec = np.abs(np.fft.rfft(x * w, 1 << 16)) ** 2
    freq = np.fft.rfftfreq(1 << 16, 1.0 / RATE)
    k = np.rint(12 * np.log2(np.maximum(freq, 1e-9) / 55.0)).astype(int)
    out = np.zeros(72)
    ok = (k >= 0) & (k < 72)
    np.add.at(out, k[ok], spec[ok])
    return np.sqrt(out)


def cosine(a, b):
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 0 else 0.0


def chroma(s):
    return np.array([s[c::12].sum() for c in range(12)])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = None
    if "--keep" in sys.argv:
        keep = sys.argv[sys.argv.index("--keep") + 1]
        args = [a for a in args if a != keep]
    ids = [int(a) for a in args] or IDS
    ev = pokes(ids)
    frames = START + STEP * len(ids) + 60
    seconds = frames / FPS + 2
    print("MAME %s: %d sounds, %.0f s of audio" % (os.path.basename(MAME), len(ids), seconds))
    mame = mame_audio(ev, seconds, keep)
    print("reference machine, %d frames ..." % frames)
    mine = synth(ref_registers(ev, frames))
    out = build_dir("rocnrope")
    for name, x in (("sound_mame.wav", mame), ("sound_ste.wav", mine)):
        with wave.open(str(out / name), "wb") as o:
            o.setnchannels(1); o.setsampwidth(2); o.setframerate(RATE)
            o.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    print("%-4s %-10s %-10s %7s %7s %7s" % ("id", "MAME", "STE", "cents", "cosine", "chroma"))
    good = silent = 0
    for k, i in enumerate(ids):
        a = int((START + STEP * k) * RATE / FPS)
        b = a + int(2.0 * RATE)
        sm, ss = semitones(mame[a:b]), semitones(mine[a:b])
        pm, ps = peak(mame[a:b]), peak(mine[a:b])
        c0, ch = cosine(sm, ss), cosine(chroma(sm), chroma(ss))
        if not pm and not ps:
            silent += 1
            print("%-4d %-10s %-10s" % (i, "silent", "silent"))
            continue
        cents = 1200 * np.log2(ps / pm) if pm and ps else float("nan")
        print("%-4d %7.0f Hz %7.0f Hz %7.0f %7.2f %7.2f" % (i, pm, ps, cents, c0, ch))
        good += bool(pm and ps and c0 > 0.7)
    print("%d of %d pieces sound in MAME or on the STE; %d of them alike (semitone spectra cosine > 0.7; the loudest "
          "peak alone can differ in chords: ids 10, 13); %d silent in both" % (len(ids) - silent, len(ids), good, silent))


def peak(x):
    """the loudest frequency (40 Hz - 4 kHz) of a piece, 0 if (nearly) silent"""
    if len(x) < 1024 or np.abs(x).max() < 1e-3:
        return 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), 1 << 17))
    f = np.fft.rfftfreq(1 << 17, 1.0 / RATE)
    spec[(f < 40) | (f > 4000)] = 0
    return float(f[int(np.argmax(spec))])


if __name__ == "__main__":
    main()
