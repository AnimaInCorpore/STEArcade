"""Record the Donkey Kong Junior sound board in MAME, driven by a script of port writes (games/dkong/tools/
sound_capture.py with Junior's ports).

    python sound_capture.py NAME "EVENTS" [--seconds S]     # -> build/dkongjr/sound/NAME.wav
    python sound_capture.py --all [--only TEXT]             # the standard set (SETS below)

EVENTS is a list of `frame:addr=value` separated by spaces, frames of the main CPU (60.6 Hz NMI), e.g.
"0:7c00=7 3:7c00=0" (tune 7 held for 3 frames, the way the game sends a one-shot).

The main CPU is parked on a `jr $` in work RAM ($6B00) with the NMI off, so only the script talks to the sound board.
The board (MAME 0.286 nintendo/dkong_a.cpp, dkongjr_audio): the 8035 (djr1-c_3h.3h) reads the tune from $7C00 (5 bits),
P2 bit 6 = $7C81, bit 5 = $7D03, bit 4 = $7D06 (inverted), T0 = /$7D05, T1 = /$7D04, its IRQ is $7D80; its DAC and the
discrete circuits of $7D00 (walk), $7D01, $7D02, $7D07 and $7D81 (SOUND9) are mixed.  The game's driver (Z80 $00E0,
every NMI) writes $7D00-$7D06 from the counters $6080-$6086 and $7C00 from $6089 (background tune) or $608A (one-shot,
held $608B frames).

MAME: the authoritative source is 0.286 (AGENTS.md); no 0.286 binary has the driver, so this runs WolfMAME 0.184 ($MAME,
default F030Arcade-private's mamearcade64.exe), whose dkongjr sound board is the same (the discrete graph, the latches,
the 8035's ports; checked 2026-10-29) but for the output route: 1.0 instead of 0.5, 6 dB louder; -volume -6 gives 0.286's level
(without it the land effect, $7D02, clipped).
"""
import argparse, os, shutil, subprocess, sys, tempfile, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import ROMS, build_dir

MAME = os.environ.get("MAME") or "C:/Arbeit/F030Arcade-private/third_party/wolfmame-0184/mamearcade64.exe"
OUT = build_dir("dkongjr") / "sound"
FPS = 60.606                    # the VBL rate (MAME: 6.144 MHz pixel clock, 384 x 264)

# the standard captures: every tune number held (does it loop?) and as the game sends a one-shot
SETS = {}
for n in range(1, 16):
    SETS["held_%02d" % n] = ("0:7c00=%d" % n, 60 if n <= 6 else 20)     # 1-6: the backgrounds, long loops
    SETS["shot_%02d" % n] = ("0:7c00=%d 3:7c00=0" % n, 12)
# the 8035's pins and the discrete inputs, pulsed for 3 frames as the driver does
for a in (0x7c81, 0x7d00, 0x7d01, 0x7d02, 0x7d03, 0x7d04, 0x7d05, 0x7d06, 0x7d07, 0x7d80, 0x7d81):
    SETS["pin_%04x" % a] = ("0:%04x=1 3:%04x=0" % (a, a), 6)
# held ones: $7D07 and $7D81 are held for up to seconds by the game
for a in (0x7d07, 0x7d81):
    SETS["hold_%04x" % a] = ("0:%04x=1 180:%04x=0" % (a, a), 6)
# walking with $7D07 set (it switches the walk circuit, SOUND7: silent on its own); the game holds $7D07 for seconds
SETS["walk_7d07"] = ("0:7d07=1 2:7d00=1 5:7d00=0 30:7d07=0", 2)
# priority: a one-shot over a background tune, the IRQ during it
SETS["prio_shot_over_bg"] = ("0:7c00=2 120:7c00=7 123:7c00=2", 12)
SETS["prio_irq_over_bg"] = ("0:7c00=2 120:7d80=1 123:7d80=0", 10)

LUA = """
-- WolfMAME 0.184: an autoboot script can not emu.wait, so everything runs from the frame callback (60.6 Hz)
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
    sp:write_u8(0x7d84, 0)
    sp:write_u8(0x6b00, 0x18) sp:write_u8(0x6b01, 0xfe)
    cpu.state["PC"].value = 0x6b00
    for a = 0x7d00, 0x7d07 do sp:write_u8(a, 0) end
    sp:write_u8(0x7c81, 0) sp:write_u8(0x7d80, 0) sp:write_u8(0x7d81, 0) sp:write_u8(0x7c00, 0)
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
        sys.exit("sound_capture: no MAME (set $MAME to a build with dkongjr)")
    ev = parse(events)
    tail = max(0.0, seconds - ev[-1][0] / FPS)
    tmp = tempfile.mkdtemp()
    lua = os.path.join(tmp, "cap.lua")
    raw = os.path.join(tmp, "raw.wav")
    with open(lua, "w") as f:
        f.write(LUA % dict(settle_frames=int(round(settle * FPS)), tail_frames=int(round(tail * FPS)) + 2,
                           events=", ".join("{%d, 0x%x, %d}" % e for e in ev)))
    r = subprocess.run([MAME, "dkongjr", "-rompath", str(ROMS), "-video", "none", "-nothrottle", "-skip_gameinfo",
                        "-autoboot_delay", "0", "-samplerate", str(rate), "-wavwrite", raw, "-volume", "-6",
                        "-autoboot_script", lua], capture_output=True, text=True, cwd=os.path.dirname(MAME))
    t0 = [l for l in r.stdout.splitlines() if l.startswith("CAPTURE_START")]
    if not t0 or not os.path.exists(raw):
        sys.exit("MAME failed:\n" + r.stdout + r.stderr)
    start = float(t0[0].split()[1])
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
        print("%-28s peak %.2f  sound %s" % (name, np.abs(x).max(), " ".join("%.2f-%.2f" % s for s in sp) or "-"))


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
    for name, events, seconds in [(a.name, a.events, a.seconds)]:
        x, rate = capture(name, events, seconds)
        sp = spans(x, rate)
        print("%-28s peak %.2f  sound %s" % (name, np.abs(x).max(), " ".join("%.2f-%.2f" % s for s in sp) or "-"))


if __name__ == "__main__":
    main()
