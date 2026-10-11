#!/bin/bash
# Speed of Gun.Smoke in Hatari (macOS / Linux; tools/bench.ps1 is the Windows version): a DEBUG + AUTOPLAY build (scripted
# coin, start, movement and the shots, period 3000 ticks) runs 6000 VBLs in run/gunsmoke_bench and writes COUNTERS.BIN.
#
#   games/gunsmoke/tools/bench.sh [frames]          EXTRA="-D ..." extra build.py options; WAIT=300: seconds to wait at most
#
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too);
# HATARI / TOS may point at other builds.  run/gunsmoke gets the normal build back.
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second; the first VBLs are the boot.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
FRAMES=${1:-6000}
BENCH=run/gunsmoke_bench; mkdir -p $BENCH
$PY games/gunsmoke/tools/build.py --debug -D AUTOPLAY=1 --frames $FRAMES $EXTRA 2>&1 | grep -i "built\|rror" | tail -1
cp run/gunsmoke/GUNSMOKE.PRG $BENCH/GUNSMOKE.PRG
$PY games/gunsmoke/tools/build.py 2>&1 | grep -i "built\|rror" | tail -1
rm -f $BENCH/COUNTERS.BIN $BENCH/CRASH.TXT
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
P
