"""Record the Donkey Kong 3 sound board in MAME, driven by a script of latch writes (after games/mario/tools/sound_capture.py).

    python sound_capture.py NAME "EVENTS" [--seconds S]     # -> build/dkong3/sound/NAME.wav
    python sound_capture.py --all [--only TEXT]             # the standard set (jobs())

EVENTS is a list of `frame:addr=value` separated by spaces, frames of the main CPU (60.6 Hz NMI), e.g.
"0:7c00=16 240:7c00=0" (the music of latch 1 held for 240 frames).

The main CPU is parked on a `jr $` in work RAM ($6B00) with the NMI off, so only the script talks to the sound board.
The board (MAME nintendo/dkong.cpp, dkong_state::dkong3_audio): two N2A03s (a 6502 with the NES's sound generator, NTSC clock)
read the main CPU's latches in their own NMI (the vertical blank): the first CPU latch 1 ($7C00) and latch 2 ($7C80), the
second latch 3 ($7D00).  Both mix into one mono output.  The CPUs run from the game's $7D80 write (bit 0) on: the game
writes it at its start, before the capture's settle time.

MAME: the authoritative source is 0.286 (AGENTS.md); the binary used here is the F030Arcade checkout's WolfMAME 0.248
($MAME overrides it), whose dkong3 sound board is the same source.
"""
import argparse, os, shutil, subprocess, sys, tempfile, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import ROMS, build_dir

WOLF248 = "C:/Arbeit/F030Arcade/third_party/wolfmame-0248/mame.exe"
MAME = os.environ.get("MAME") or (WOLF248 if os.path.exists(WOLF248) else shutil.which("mame"))
OUT = build_dir("dkong3") / "sound"
FPS = 60.606                    # the NMI rate (MAME: 6.144 MHz pixel clock, 384 x 264)

LATCHES = (0x7C00, 0x7C80, 0x7D00)


def observed():
    """-> {latch address: {value: longest time held in play (frames)}} from ref/sound_values.py's runs"""
    import glob, json
    out = {a: {} for a in LATCHES}
    for fn in glob.glob(str(build_dir("dkong3") / "sound_values_*.json")):
        log = json.load(open(fn))
        for k, a in enumerate(LATCHES):
            for i, e in enumerate(log):
                v = e[1 + k]
                if v and (i == 0 or log[i - 1][1 + k] != v):
                    j = i
                    while j + 1 < len(log) and log[j + 1][1 + k] == v:
                        j += 1
                    held = (log[j + 1][0] if j + 1 < len(log) else e[0]) - e[0]
                    out[a][v] = max(out[a].get(v, 0), held)
    return out


def jobs():
    """The standard captures (NAME -> (events, seconds)): every value the game sends to a latch as a pulse (3 frames, then 0;
    P_), the values held for 30 frames or more in play as a hold (8 s; H_), and every pulse of a value that contains a hold
    value as the base's bits (the base held 2 s, the value 3 frames, the base again, to 5 s; S_): the effect on top of a tune
    is S_ minus H_ (tools/sound_convert.py)."""
    obs = observed()
    out = {}
    f = lambda sec: int(round(sec * FPS))
    for a, vals in obs.items():
        holds = sorted(v for v, h in vals.items() if h >= 30)
        for v in sorted(vals):
            out["P_%04x_%02x" % (a, v)] = ("0:%04x=%d 3:%04x=0" % (a, v, a), 14.0)
        for h in holds:
            out["H_%04x_%02x" % (a, h)] = ("0:%04x=%d %d:%04x=0" % (a, h, f(5.0), a), 7.0)
            for v in sorted(vals):
                if v != h and v & h == h:
                    out["S_%04x_%02x_%02x" % (a, h, v)] = ("0:%04x=%d %d:%04x=%d %d:%04x=%d %d:%04x=0" % (
                        a, h, f(1.5), a, v, f(1.5) + 3, a, h, f(5.0), a), 7.0)
    return out


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
  if frame == settle - 20 then
    sp:write_u8(0x7e84, 0)
    sp:write_u8(0x6b00, 0x18) sp:write_u8(0x6b01, 0xfe)
    cpu.state["PC"].value = 0x6b00
    sp:write_u8(0x7c00, 0) sp:write_u8(0x7c80, 0) sp:write_u8(0x7d00, 0)
    sp:write_u8(0x7d80, 0)                     -- (both sound CPUs reset: their own start)
  end
  if frame == settle - 10 then sp:write_u8(0x7d80, 1) end
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


def capture(name, events, seconds, settle=4.0, rate=48000):
    """Run MAME, return the mono float signal from the first event on (rate Hz) and write NAME.wav."""
    if not MAME:
        sys.exit("sound_capture: no MAME (set $MAME to a build with dkong3)")
    ev = parse(events)
    tail = max(0.0, seconds - ev[-1][0] / FPS)
    tmp = tempfile.mkdtemp()
    lua = os.path.join(tmp, "cap.lua")
    raw = os.path.join(tmp, "raw.wav")
    with open(lua, "w") as f:
        f.write(LUA % dict(settle_frames=int(round(settle * FPS)), tail_frames=int(round(tail * FPS)) + 2,
                           events=", ".join("{%d, 0x%x, %d}" % e for e in ev)))
    r = subprocess.run([MAME, "dkong3", "-rompath", str(ROMS), "-video", "none", "-nothrottle", "-skip_gameinfo",
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


def capture_all(only=None, workers=8):
    import concurrent.futures as cf
    todo = {k: v for k, v in jobs().items() if not only or only in k}

    def one(item):
        name, (events, seconds) = item
        x, rate = capture(name, events, seconds)
        return name, x, rate

    with cf.ThreadPoolExecutor(workers) as ex:
        for name, x, rate in ex.map(one, todo.items()):
            sp = spans(x, rate)
            print("%-18s peak %.2f  sound %s" % (name, np.abs(x).max(), " ".join("%.2f-%.2f" % t for t in sp) or "-"), flush=True)


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
