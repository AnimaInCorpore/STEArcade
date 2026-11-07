"""Record the Mario Bros. sound board in MAME, driven by a script of port writes (after games/dkongjr/tools/
sound_capture.py).

    python sound_capture.py NAME "EVENTS" [--seconds S]     # -> build/mario/sound/NAME.wav
    python sound_capture.py --all [--only TEXT]             # the standard set (SETS below)

EVENTS is a list of `frame:addr=value` separated by spaces, frames of the main CPU (59.185 Hz NMI), e.g.
"0:7e00=1 3:7e00=0" (tune 1 held for 3 frames).

The main CPU is parked on a `jr $` in work RAM ($6B00) with the NMI off, so only the script talks to the sound board.
The board (MAME nintendo/mario.cpp, mario_state::mario): the M58715 (an 8039 family MCU: its internal ROM has no dump,
MAME bootstraps it into the external ROM 6K) reads the tune from $7E00 (soundlatch 0), P1 = the latch of $7F03-$7F06
(crab, turtle, fly, coin), T0 / T1 = $7F01 / $7F02 (get coin, ice), its INT = $7F00 (death), its DAC goes to the
netlist; $7C00 / $7C80 (the walks) and $7F07 (skid) are discrete circuits of the netlist.

MAME: the authoritative source is 0.286 (AGENTS.md); the binary used here is the F030Arcade checkout's WolfMAME 0.248
($MAME overrides it), whose mario sound board (the netlist, the fake MCU bootstrap) is the same source.
"""
import argparse, os, shutil, subprocess, sys, tempfile, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import ROMS, build_dir

WOLF248 = "C:/Arbeit/F030Arcade/third_party/wolfmame-0248/mame.exe"
MAME = os.environ.get("MAME") or (WOLF248 if os.path.exists(WOLF248) else shutil.which("mame"))
OUT = build_dir("mario") / "sound"
FPS = 59.185                    # the NMI rate (MAME: 6 MHz pixel clock, 384 x 264)

# the standard captures: every tune number held and as a one-shot, every pin pulsed (the driver holds them 1-3 frames)
SETS = {}
for n in range(1, 32):
    SETS["held_%02d" % n] = ("0:7e00=%d" % n, 20)
    SETS["shot_%02d" % n] = ("0:7e00=%d 3:7e00=0" % n, 12)
for n in range(32, 40):                                       # $7E00 values with bit 5 (the game sends $20-$26)
    SETS["shot_%02d" % n] = ("0:7e00=%d 3:7e00=0" % n, 12)
SETS["pin_7f00"] = ("0:7f00=1 48:7f00=0", 5)                  # the death: the game holds the line 48 frames
for a in (0x7f01, 0x7f02, 0x7f03, 0x7f04, 0x7f05, 0x7f06, 0x7f07, 0x7c00, 0x7c80):
    SETS["pin_%04x" % a] = ("0:%04x=1 3:%04x=0" % (a, a), 5)
for a in (0x7f07,):
    SETS["hold_%04x" % a] = ("0:%04x=1 60:%04x=0" % (a, a), 4)

LUA = """
-- an autoboot script can not emu.wait, so everything runs from the frame callback
local m = type(manager.machine) == "function" and manager:machine() or manager.machine
local cpu = m.devices[":maincpu"]
local sp = cpu.spaces["program"]
local ev = {%(events)s}
local settle, tail = %(settle_frames)d, %(tail_frames)d
local last = ev[#ev][1]
local frame, idx = 0, 1
emu.register_frame_done(function()
  frame = frame + 1
  if frame == 1 then
    sp:write_u8(0x7e84, 0)
    sp:write_u8(0x6b00, 0x18) sp:write_u8(0x6b01, 0xfe)
    cpu.state["PC"].value = 0x6b00
    for a = 0x7f00, 0x7f07 do sp:write_u8(a, 0) end
    sp:write_u8(0x7e00, 0)
  end
  local f = frame - settle
  if f == 0 then print("CAPTURE_START", emu.time()) end
  if f >= 0 then
    while idx <= #ev and ev[idx][1] <= f do sp:write_u8(ev[idx][2], ev[idx][3]) idx = idx + 1 end
  end
  if f >= last + tail then
    print("CAPTURE_END", emu.time(), "PC", cpu.state["PC"].value)
    m:exit()
  end
end)
"""


def parse(events):
    ev = []
    for tok in events.split():
        f, rest = tok.split(":")
        a, v = rest.split("=")
        ev.append((int(f), int(a, 16), int(v, 0)))
    return sorted(ev, key=lambda e: e[0])


def capture(name, events, seconds, settle=1.0, rate=48000):
    """Run MAME, return the mono float signal from the first event on (rate Hz) and write NAME.wav."""
    if not MAME:
        sys.exit("sound_capture: no MAME (set $MAME to a build with mario)")
    ev = parse(events)
    tail = max(0.0, seconds - ev[-1][0] / FPS)
    tmp = tempfile.mkdtemp()
    lua = os.path.join(tmp, "cap.lua")
    raw = os.path.join(tmp, "raw.wav")
    with open(lua, "w") as f:
        f.write(LUA % dict(settle_frames=int(round(settle * FPS)), tail_frames=int(round(tail * FPS)) + 2,
                           events=", ".join("{%d, 0x%x, %d}" % e for e in ev)))
    r = subprocess.run([MAME, "mario", "-rompath", str(ROMS), "-video", "none", "-nothrottle", "-skip_gameinfo",
                        "-autoboot_delay", "0", "-samplerate", str(rate), "-wavwrite", raw,
                        "-autoboot_script", lua], capture_output=True, text=True, cwd=tmp)
    t0 = [l for l in r.stdout.splitlines() if l.startswith("CAPTURE_START")]
    if not t0 or not os.path.exists(raw):
        sys.exit("MAME failed:\n" + r.stdout + r.stderr)
    start = float(t0[0].split()[1].replace(",", "."))
    w = wave.open(raw)
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels())[:, 0]
    x = x[int(round(start * rate)):][:int(seconds * rate)]
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / (name + ".wav")), "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(rate)
        o.writeframes(x.tobytes())
    return x.astype(np.float64) / 32768.0, rate


def spans(x, rate, win=0.02, thresh=0.01):
    """The stretches with sound: [(start s, end s)], gaps under 0.25 s joined."""
    n = int(win * rate)
    k = len(x) // n
    rms = np.sqrt((x[:k * n].reshape(k, n) ** 2).mean(1))
    on = rms > thresh
    out = []
    for i, b in enumerate(on):
        if b:
            if out and i * win - out[-1][1] < 0.25:
                out[-1][1] = (i + 1) * win
            else:
                out.append([i * win, (i + 1) * win])
    return [(round(a, 2), round(b, 2)) for a, b in out]


def capture_all(only=None):
    for name, (events, seconds) in SETS.items():
        if only and only not in name:
            continue
        x, rate = capture(name, events, seconds)
        sp = spans(x, rate)
        print("%-18s peak %.2f  sound %s" % (name, np.abs(x).max(), " ".join("%.2f-%.2f" % s for s in sp) or "-"), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("events", nargs="?")
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", help="with --all: names containing this")
    a = ap.parse_args()
    if a.all:
        capture_all(a.only)
        return
    x, rate = capture(a.name, a.events, a.seconds)
    sp = spans(x, rate)
    print("%-18s peak %.2f  sound %s" % (a.name, np.abs(x).max(), " ".join("%.2f-%.2f" % s for s in sp) or "-"))


if __name__ == "__main__":
    main()
