#!/bin/bash
# Galaga's frame rate in Hatari (the Unix tools/bench.ps1): a --debug -D RATE=500 build runs FRAMES VBLs of the attract
# mode in run/<name> (fast forward) and writes RATE.BIN (VBL and render counters every 500 VBLs) and BORDERS.BIN.
#
#   games/galaga/tools/bench.sh [frames] [name]     EXTRA="-D ..." extra build.py options; WAIT=300: seconds at most
#
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first); HATARI / TOS may point
# at other builds.  run/galaga is not touched.  Reports the frames drawn a second per 500 VBLs (the picture rate; the
# game logic runs at every VBL) and the border code's counters.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
FRAMES=${1:-9000}
NAME=${2:-galaga_bench}
BENCH=run/$NAME; mkdir -p $BENCH
$PY games/galaga/tools/build.py --debug -D RATE=500 --frames $FRAMES $EXTRA --out "$ROOT/$BENCH/GALAGA.PRG" 2>&1 | grep -i "built\|rror" | tail -1
cp build/galaga/galaga.map $BENCH/galaga.map
rm -f $BENCH/RATE.BIN $BENCH/BORDERS.BIN $BENCH/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --fast-forward true --run-vbls $((FRAMES + 600)) \
  --log-file hatari.log GALAGA.PRG) > /dev/null 2>&1 &
HP=$!
for i in $(seq ${WAIT:-300}); do sleep 1; [ -f $BENCH/RATE.BIN ] || [ -f $BENCH/CRASH.TXT ] && break; kill -0 $HP 2>/dev/null || break; done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/RATE.BIN ] || { echo "no RATE.BIN"; exit 1; }
BENCH=$BENCH python3 - <<'P'
import os, struct
b = os.environ["BENCH"]
d = open(b + "/RATE.BIN", "rb").read()
pv = pr = 0
rates = []
for i in range(0, len(d) - 3, 4):
    v, r = struct.unpack(">HH", d[i:i + 4])
    if v > pv:
        rates.append((pv, v, 50 * (r - pr) / (v - pv)))
    pv, pr = v, r
print(" ".join("%.1f" % x for _, _, x in rates))
print("frames drawn a second, VBLs %d-%d: %.1f on average" % (rates[0][0], rates[-1][1], sum(x for *_, x in rates) / len(rates)))
if os.path.exists(b + "/BORDERS.BIN"):
    f, top, on, low, off = struct.unpack(">5H", open(b + "/BORDERS.BIN", "rb").read()[:10])
    print("borders: armed by the VBL in %d frames; late events: top %d, palette on %d, bottom %d, palette off %d" % (f, top, on, low, off))
P
