"""Record the Donkey Kong sound board in MAME, driven by a script of port writes.

    python sound_capture.py NAME "EVENTS" [--seconds S]     # -> build/dkong/sound/NAME.wav
    python sound_capture.py --all                           # the standard set (SETS below)

EVENTS is a list of `frame:addr=value` separated by spaces, frames of the main CPU (60.6 Hz NMI), e.g.
"0:7c00=1 3:7c00=0" (tune 1 held for 3 frames, the way the game sends a one-shot).

The main CPU is parked on a `jr $` in work RAM with the NMI off, so only the script talks to the sound
board: the 8035 (s_3i_b / s_3j_b) and the discrete walk / jump / stomp circuits, exactly as MAME models them.
The game's own sound driver (Z80 $00E0, every NMI) rewrites $7C00, $7D00-$7D07 and $7D80 each frame from
$6080-$608B: one-shot tunes are $608A held for $608B = 3 frames over the background tune $6089.

MAME: a full build is needed (the 0.184 build in F030Arcade is CPS-only): $MAME, else F030Arcade's wolfmame-0162,
else `mame` in the PATH.  Tested with 0.162 only (its Lua API: emu.wait, cpu.state, cpu.spaces).
"""
import argparse, os, shutil, subprocess, sys, tempfile, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import ROMS, build_dir

MAME = os.environ.get("MAME") or next((m for m in (r"C:\Arbeit\F030Arcade\third_party\wolfmame-0162\mame.exe",)
                                       if os.path.exists(m)), None) or shutil.which("mame")
OUT = build_dir("dkong") / "sound"
FPS = 60.606                    # Donkey Kong's VBL rate (MAME: 6.144 MHz pixel clock, 384 x 264)

# the standard captures: the tunes the game sends (dkong.cpp, write map of $7C00), each as the game sends it
TUNES = {1: "intro", 2: "howhigh", 3: "outoftime", 4: "hammer", 5: "rivet2_end", 6: "hammer_hit",
         7: "stage_end", 8: "bg_barrels", 9: "bg_pie", 10: "bg_springs", 11: "bg_rivets",
         12: "rivet1_end", 13: "rivet_removed", 14: "rivet_end", 15: "roar"}
SETS = {}
for n, name in TUNES.items():
    SETS["held_%02d_%s" % (n, name)] = ("0:7c00=%d" % n, 20)            # held: does it loop?
    SETS["shot_%02d_%s" % (n, name)] = ("0:7c00=%d 3:7c00=0" % n, 12)   # one-shot, as the game sends it
for b, name in ((0, "walk"), (1, "jump"), (2, "stomp"), (3, "coin_spring"), (4, "gorilla_fall"), (5, "barrel_prize")):
    SETS["trig_%d_%s" % (b, name)] = ("0:7d0%d=1 3:7d0%d=0" % (b, b), 4)
SETS["death"] = ("0:7d80=1 3:7d80=0", 6)
# priority: a one-shot over a running background tune, and death during it
SETS["prio_shot_over_bg"] = ("0:7c00=8 120:7c00=6 123:7c00=8", 12)
SETS["prio_death_over_bg"] = ("0:7c00=8 120:7d80=1 123:7d80=0", 10)

LUA = """
local m = type(manager.machine) == "function" and manager:machine() or manager.machine
local cpu = m.devices[":maincpu"]
local sp = cpu.spaces["program"]
local function park()
  sp:write_u8(0x7d84, 0)
  sp:write_u8(0x6a00, 0x18) sp:write_u8(0x6a01, 0xfe)
  cpu.state["PC"].value = 0x6a00
end
park()
for a = 0x7d00, 0x7d07 do sp:write_u8(a, 0) end
sp:write_u8(0x7d80, 0)
sp:write_u8(0x7c00, 0)
emu.wait(%(settle)f)
print("CAPTURE_START", emu.time())
local ev = {%(events)s}
local f = 0
for _, e in ipairs(ev) do
  while f < e[1] do emu.wait(1 / %(fps)f) f = f + 1 end
  sp:write_u8(e[2], e[3])
end
emu.wait(%(tail)f)
print("CAPTURE_END", emu.time(), "PC", cpu.state["PC"].value)
m:exit()
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
        sys.exit("sound_capture: no MAME (set $MAME to a full build with dkong; tested with 0.162)")
    ev = parse(events)
    tail = max(0.0, seconds - ev[-1][0] / FPS)
    tmp = tempfile.mkdtemp()
    lua = os.path.join(tmp, "cap.lua")
    raw = os.path.join(tmp, "raw.wav")
    with open(lua, "w") as f:
        f.write(LUA % dict(settle=settle, fps=FPS, tail=tail,
                           events=", ".join("{%d, 0x%x, %d}" % e for e in ev)))
    r = subprocess.run([MAME, "dkong", "-rompath", str(ROMS), "-video", "none", "-nothrottle", "-skip_gameinfo",
                        "-autoboot_delay", "0", "-samplerate", str(rate), "-wavwrite", raw,
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
