#!/bin/bash
# Speed of Bubble Bobble in Hatari (the pinned F030Arcade build): a DEBUG + AUTOPLAY build (tools/profile.py's input
# script by VBL: coin at 400, start at 440, then moving, jumping and blowing bubbles) runs [frames] VBLs in
# run/bublbobl_bench and writes COUNTERS.BIN (every 300 VBLs: VBLs, game rounds, pictures completed, pictures shown) and
# BORDERS.BIN (engine/rt/borders.s: late border events, blit_go passes run in pieces).
#
#   games/bublbobl/tools/bench.sh [frames]          EXTRA="-D ..." extra build.py options; WAIT=300: seconds to wait at most
#
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too);
# HATARI / TOS may point at other builds.  run/bublbobl gets the normal build back.  Per window of 300 VBLs it reports
# the game rounds a VBL (1.00 = the port's full speed, 50 of the arcade's 59.19 a second) and the pictures a second,
# the windows of tools/profile.py.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
FRAMES=${1:-1500}
BENCH=run/bublbobl_bench; mkdir -p $BENCH
$PY games/bublbobl/tools/build.py --debug -D AUTOPLAY=1 --frames $FRAMES $EXTRA 2>&1 | grep -i "built\|rror" | tail -1
cp run/bublbobl/BUBBLE.PRG $BENCH/BUBBLE.PRG
$PY games/bublbobl/tools/build.py 2>&1 | grep -i "built\|rror" | tail -1
rm -f $BENCH/COUNTERS.BIN $BENCH/BORDERS.BIN $BENCH/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --log-file hatari.log BUBBLE.PRG) > /dev/null 2>&1 &
HP=$!
for i in $(seq ${WAIT:-300}); do sleep 1; [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break; kill -0 $HP 2>/dev/null || break; done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import struct
d = open('run/bublbobl_bench/COUNTERS.BIN', 'rb').read()
snaps = [struct.unpack('>4H', d[i:i + 8]) for i in range(0, len(d) - 7, 8)]
prev = (0, 0, 0, 0)
for s in snaps:
    v, r, c, w = (b - a for a, b in zip(prev, s))
    if v:
        print("VBLs %4d-%4d: game rounds per VBL %.2f, pictures completed %.1f /s, shown %.1f /s"
              % (prev[0], s[0], r / v, c / v * 50, w / v * 50))
    prev = s
try:
    b = open('run/bublbobl_bench/BORDERS.BIN', 'rb').read()
    f, top, on, low, off = struct.unpack('>5H', b[:10])
    print("borders: top border armed by the VBL in %d frames; events that started too late: top %d, palette on %d, "
          "bottom %d, palette off %d; passes run in pieces %d" % (f, top, on, low, off, struct.unpack('>L', b[10:14])[0]))
except FileNotFoundError:
    print("no BORDERS.BIN")
P
