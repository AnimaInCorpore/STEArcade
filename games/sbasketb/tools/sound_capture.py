"""Record the Super Basketball sound board in MAME, driven by a script of sound commands (after games/mario/tools/
sound_capture.py).

    python sound_capture.py NAME "EVENTS" [--seconds S]     # -> build/sbasketb/sound/NAME.wav
    python sound_capture.py --all [--only TEXT] [--workers N]   # the standard set (SETS below)

EVENTS is a list of `frame:command` separated by spaces, frames of the main CPU (60 Hz), commands as the game writes them
to the sound latch $3D00 and then to the trigger $3D80 (which raises the Z80's IRQ), e.g. "0:3 20:0".

The main CPU is parked in its boot's first delay loop ($D585 patched to BRA * in the ROM region: the KONAMI-1 opcode
byte is encrypted) before it can start the game; the script kicks the watchdog every frame and talks to the sound board
only.  The board (MAME
konami/sbasketb.cpp, trackfld_a.cpp): a Z80 with an SN76489A, a DAC and a VLM5030.

MAME: the authoritative source is 0.286 (AGENTS.md); the binary used here is the F030Arcade checkout's WolfMAME 0.248
($MAME overrides it).  Its sound board is the same source (the CPU clock differs, which the main CPU's does not matter
here: the sound CPU's clock, 3.579545 MHz, is the same).
"""
import argparse, os, shutil, subprocess, sys, tempfile, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
from paths import ROMS, build_dir

WOLF248 = "C:/Arbeit/F030Arcade/third_party/wolfmame-0248/mame.exe"
MAME = os.environ.get("MAME") or (WOLF248 if os.path.exists(WOLF248) else shutil.which("mame"))
OUT = build_dir("sbasketb") / "sound"
FPS = 60.0

# the standard captures: every command the coverage's play sends, alone (the game's phrases come as 254, phrase, 255)
EFFECTS = [1, 3, 8, 9, 10, 11, 12, 13, 14, 18, 24, 26, 31, 32, 35, 41, 64]
PHRASES = list(range(128, 175))
SETS = {"base": ("9999:0", 40)}        # no command: the board's own background (subtracted by sound_convert.py)
SETS.update({"cmd_%02x" % c: ("0:%d" % c, 20) for c in EFFECTS})
for p in PHRASES:
    SETS["say_%02x" % p] = ("0:254 1:%d 2:255" % p, 12)
SETS["say_noprefix"] = ("0:171 1:255", 12)
SETS["cmd_ff"] = ("0:255", 6)
SETS["cmd_fe"] = ("0:254", 6)
SETS["cmd_00"] = ("0:3 30:0", 8)

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
  sp:write_u8(0x3c00, 0)
  if frame == 1 then
    -- park the main CPU: the boot's first delay loop ($D585 STA $3C00) becomes BRA * (opcode byte encrypted: $D585 & $A
    -- is 0: xor $22), in the ROM region itself (a write to the ROM's address space is ignored)
    local rg = m.memory.regions[":maincpu"]
    rg:write_u8(0xd585, 0x20 ~ 0x22) rg:write_u8(0xd586, 0xfe)
  end
  local f = frame - settle
  if f == 0 then print("CAPTURE_START", emu.time()) end
  if f >= 0 then
    while idx <= #ev and ev[idx][1] <= f do
      sp:write_u8(0x3d00, ev[idx][2]) sp:write_u8(0x3d80, 0)
      idx = idx + 1
    end
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
        f, c = tok.split(":")
        ev.append((int(f), int(c, 0)))
    return sorted(ev, key=lambda e: e[0])


def capture(name, events, seconds, settle=1.0, rate=48000):
    """Run MAME, return the mono float signal from the first event on (rate Hz) and write NAME.wav."""
    if not MAME:
        sys.exit("sound_capture: no MAME (set $MAME to a build with sbasketb)")
    ev = parse(events)
    tail = max(0.0, seconds - ev[-1][0] / FPS)
    tmp = tempfile.mkdtemp()
    lua = os.path.join(tmp, "cap.lua")
    raw = os.path.join(tmp, "raw.wav")
    with open(lua, "w") as f:
        f.write(LUA % dict(settle_frames=int(round(settle * FPS)), tail_frames=int(round(tail * FPS)) + 2,
                           events=", ".join("{%d, %d}" % e for e in ev)))
    r = subprocess.run([MAME, "sbasketb", "-rompath", str(ROMS), "-video", "none", "-nothrottle", "-skip_gameinfo",
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
    shutil.rmtree(tmp, ignore_errors=True)
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


def one(item):
    name, (events, seconds) = item
    x, rate = capture(name, events, seconds)
    sp = spans(x, rate)
    return "%-14s peak %.2f  sound %s" % (name, np.abs(x).max(), " ".join("%.2f-%.2f" % s for s in sp) or "-")


def capture_all(only=None, workers=4):
    from concurrent.futures import ThreadPoolExecutor
    items = [(n, v) for n, v in SETS.items() if not only or only in n]
    with ThreadPoolExecutor(workers) as ex:
        for line in ex.map(one, items):
            print(line, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("events", nargs="?")
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", help="with --all: names containing this")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.all:
        capture_all(a.only, a.workers)
        return
    print(one((a.name, (a.events, a.seconds))))


if __name__ == "__main__":
    main()
