"""Dig Dug: the STE program (a --sim build on Musashi) against the reference machine in the runtime's schedule
(machine.DigDug.run_frame_port) over a scripted game: boot, attract mode, a coin, a start, play.

The STE's main thread runs freely between the VBLs (the arcade's foreground polls), so the two machines are not
cycle-locked as a cooperative port's are: what is compared is what the game has decided.  Every `--every` frames the
video RAM ($8000-$83FF: what is on the screen) and the sprite RAMs (the sprite table the game built, $8B80-$8BFF,
$9380-$93FF, $9B80-$9BFF) of the two are compared; a few frames of difference while something moves are normal, so a
sample counts as equal when it matches the reference at any of the frames within +-`--slack` of it.  The 51XX's credit
count, the video latch, the sprite RAM and the sound chip's registers are summarised.

    python schedule_test.py [frames] [--every N] [--slack K]
"""
import argparse
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import subprocess
from sim import Sim
from paths import ROOT, build_dir
from machine import DigDug

ap = argparse.ArgumentParser()
ap.add_argument("frames", nargs="?", type=int, default=3000)
ap.add_argument("--every", type=int, default=50)
ap.add_argument("--slack", type=int, default=600, help="the reference frames searched for a match: the STE may be behind")
ap.add_argument("--no-build", action="store_true")
a = ap.parse_args()
RUN = ROOT / "run" / "digdug_sim"


def script(f):
    in0 = in1 = 0xff
    if 800 <= f < 806: in1 &= ~0x10
    if 840 <= f < 846: in1 &= ~0x04
    if f >= 900:
        g = f - 900
        in0 &= ~(0x02 if (g // 40) % 2 else 0x08)
        if (g // 70) % 2: in0 &= ~(0x04 if (g // 30) % 2 else 0x01)
        if g % 20 < 3: in1 &= ~0x01
    return in0, in1


if not a.no_build:
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.py"), "--sim"], check=True,
                   stdout=subprocess.DEVNULL)
s = Sim(str(RUN / "DIGDUG.PRG"), ram_kib=16384, run_dir=RUN)
sym = {k: v + s.base for k, v in s.symbols(build_dir("digdug") / "digdug.map").items()}
mem = s.mem
ram = lambda lo, hi: bytes(mem.r_block(sym["g_block"] + lo, hi - lo))     # Z80 $8000-: g_block + $8000 + (addr - $8000)
ref = DigDug(skip_tests=True, mcu_events=True)
hist = []                      # the reference's video RAM and sprite RAM at every frame
BOOT_LAG = 1000          # (the STE is slower in the boot test screen: the frames before this one may differ)
REG = ((0x8000, 0x8400), (0x8B80, 0x8C00), (0x9380, 0x9400), (0x9B80, 0x9C00))


def snapshot_ref():
    r = ref.ram
    return tuple(bytes(r[lo - 0x8000:hi - 0x8000]) for lo, hi in REG)


def press(f):
    in0, in1 = script(f)
    mem.w8(sym["in0_kbd"], (~in0) & 0xff)
    mem.w8(sym["in1_kbd"], (~in1) & 0xff)


state = {"f": 0}


def on_frame(sim):
    f = state["f"] = state["f"] + 1
    press(f)


for f in range(a.frames):
    ref.in0, ref.in1 = script(f)
    ref.run_frame_port()
    hist.append(snapshot_ref())
press(0)
same = diff = late = 0
first = None
lags = []
frame_counter = lambda: mem.r32(sym["frame_counter"])
s.run_frames(0)
for f in range(a.frames):
    s.run_frames(1, on_frame=on_frame)
    press(f + 1)
    if f % a.every:
        continue
    now = tuple(bytes(mem.r_block(sym["g_block"] + lo, hi - lo)) for lo, hi in REG)
    match = [g for g in range(max(f - a.slack, 0), min(f + a.slack, a.frames - 1) + 1) if now == hist[g]]
    if match:
        same += 1
        lags.append(match[0] - f)
    else:
        diff += 1
        if f >= BOOT_LAG:
            late += 1
        if first is None:
            first = f
        r0 = hist[f]
        n = sum(1 for x, y in zip(now[0], r0[0]) if x != y)
        ns = sum(1 for k in (1, 2, 3) for x, y in zip(now[k], r0[k]) if x != y)
        print("frame %d: %d tile RAM bytes, %d sprite RAM bytes differ from the reference's frame %d" % (f, n, ns, f))
print("compared frames: %d equal, %d different (first %s); the reference's matching frame minus the STE's: %s" % (
    same, diff, first, sorted(set(lags))))
print("STE: credits (51XX RAM $03) %d, frame_counter %d, cpu3_state %d, booted2 %d" % (
    mem.r8(sym["N51_state"] + 3), frame_counter(), mem.r8(sym["cpu3_state"]), mem.r8(sym["booted2"])))
print("reference: %d handler runs (CPU1 IRQ, CPU2 IRQ), 51XX RAM $03 = %d" % (ref.handler_runs[0], ref.n51.mcu.ram[3]))
print("differences from frame %d on (after the boot test screen's lag): %d" % (BOOT_LAG, late))
sys.exit(1 if late else 0)
