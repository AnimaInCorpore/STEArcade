#!/bin/bash
# Speed of 1943 in Hatari: a DEBUG + AUTOPLAY build (scripted coin, start and play) runs 6000 VBLs in run/1943_bench and
# writes COUNTERS.BIN (and BORDERS.BIN, the border code's counters).
#
#   games/1943/tools/bench.sh [frames]          EXTRA="-D ..." extra build.py options (-D STAGE=n: a stage with the cheats);
#                                                WAIT=300: seconds to wait at most
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too);
# HATARI / TOS may point at other builds.  run/1943 gets the normal build back.
# Reports the game ticks a second (the arcade: 60) and the frames drawn a second; the first VBLs are the boot.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
FRAMES=${1:-6000}
BENCH=run/1943_bench; mkdir -p $BENCH
$PY games/1943/tools/build.py --debug -D AUTOPLAY=1 --frames $FRAMES $EXTRA 2>&1 | grep -i "built\|rror" | tail -1
cp run/1943/1943.PRG $BENCH/1943.PRG
$PY games/1943/tools/build.py 2>&1 | grep -i "built\|rror" | tail -1
rm -f $BENCH/COUNTERS.BIN $BENCH/BORDERS.BIN $BENCH/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --log-file hatari.log 1943.PRG) > /dev/null 2>&1 &
HP=$!
for i in $(seq ${WAIT:-300}); do sleep 1; [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break; kill -0 $HP 2>/dev/null || break; done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import os, struct
d = open('run/1943_bench/COUNTERS.BIN', 'rb').read()
v, r, i, dma, mcu = struct.unpack('>5H', d[:10])
print("VBLs", v, "frames drawn", r, "ticks", i, "sprite list buffers", dma, "MCU replies", mcu)
print("game ticks %.1f /s (arcade 60) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 60 * 100, r / v * 50))
if os.path.exists('run/1943_bench/BORDERS.BIN'):
    b = open('run/1943_bench/BORDERS.BIN', 'rb').read()
    f, top, on, low, off = struct.unpack('>5H', b[:10])
    print("borders: top border armed by the VBL in %d frames; events that started too late: top %d, palette on %d, bottom %d, palette off %d; passes run in pieces %d" % (f, top, on, low, off, struct.unpack('>L', b[10:14])[0]))
P
