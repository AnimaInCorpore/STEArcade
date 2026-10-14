#!/bin/bash
# Speed of Gun.Smoke in Hatari (macOS / Linux; tools/bench.ps1 is the Windows version): a DEBUG + AUTOPLAY build (scripted
# coin, start, movement and the shots, period 3000 ticks) runs 6000 VBLs in run/gunsmoke_bench and writes COUNTERS.BIN.
#
#   games/gunsmoke/tools/bench.sh [frames]          EXTRA="-D ..." extra build.py options; WAIT=300: seconds to wait at most;
#                                                   PLAY=1: the recorded play (build/gunsmoke/play_inputs.bin) instead
#
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too);
# HATARI / TOS may point at other builds.  run/gunsmoke gets the normal build back.
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second; the first VBLs are the boot.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
FRAMES=${1:-6000}
BENCH=run/gunsmoke_bench; mkdir -p $BENCH
MODE="-D AUTOPLAY=1"; [ -n "$PLAY" ] && MODE="-D PLAYBACK=1"   # PLAY=1: the recorded play (tools/play_search.py) by game tick
$PY games/gunsmoke/tools/build.py --debug $MODE --frames $FRAMES $EXTRA 2>&1 | grep -i "built\|rror" | tail -1
cp run/gunsmoke/GUNSMOKE.PRG $BENCH/GUNSMOKE.PRG
$PY games/gunsmoke/tools/build.py 2>&1 | grep -i "built\|rror" | tail -1
rm -f $BENCH/COUNTERS.BIN $BENCH/RATE.BIN $BENCH/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --log-file hatari.log GUNSMOKE.PRG) > /dev/null 2>&1 &
HP=$!
for i in $(seq ${WAIT:-300}); do sleep 1; [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break; kill -0 $HP 2>/dev/null || break; done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import struct
d = open('run/gunsmoke_bench/COUNTERS.BIN', 'rb').read()
v, r, i = struct.unpack('>3H', d[:6])
print("VBLs", v, "frames drawn", r, "ticks", i)
print("game ticks %.1f /s (arcade 59.6) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 59.6 * 100, r / v * 50))
if len(d) >= 20:
    f, top, on, low, off = struct.unpack('>5H', d[6:16])
    print("borders: top border armed by the VBL in %d frames; events that started too late: top %d, palette on %d, bottom %d, palette off %d; passes run in pieces %d" % (f, top, on, low, off, struct.unpack('>L', d[16:20])[0]))
import os
if os.path.exists('run/gunsmoke_bench/RATE.BIN'):      # the timeline: per 100 VBLs, from the first game tick on
    t = open('run/gunsmoke_bench/RATE.BIN', 'rb').read()
    pts = [struct.unpack('>2H', t[k:k + 4]) for k in range(0, len(t) - 3, 4)]
    rows = [((b[0] - a[0]) & 0xffff, (b[1] - a[1]) & 0xffff) for a, b in zip(pts, pts[1:])]
    print("per 100 VBLs (ticks/s, pictures/s):", " ".join("%d/%d" % (t2 / 2, p2 / 2) for t2, p2 in rows))
    live = [r for r in rows if r[0]]
    if live:
        print("from the first tick: game ticks %.1f /s (%.0f%%), pictures %.1f /s" % (sum(r[0] for r in live) / len(live) / 2,
              sum(r[0] for r in live) / len(live) / 2 / 59.6 * 100, sum(r[1] for r in live) / len(live) / 2))
P
