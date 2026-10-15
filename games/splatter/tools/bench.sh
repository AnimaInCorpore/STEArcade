#!/bin/bash
# Speed of Splatterhouse in Hatari: a BENCH build (splatter.s: scripted coin, start and play, counted from arcade frame
# BENCH_FROM to BENCH_TO, then it quits) runs in run/splatter_bench and writes COUNTERS.BIN.
#
#   games/splatter/tools/bench.sh [TAG]         EXTRA="-D ..." extra build.py options; WAIT=400: seconds at most;
#                                                PHASES=1: render.s' REN_PHASES (VBLs per phase of render_frame)
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too);
# HATARI / TOS may point at other builds.  run/splatter gets the normal build back.
# Reports the arcade frames a second (the arcade: 60), the pictures a second, and where the VBLs went.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
TAG=${1:-bench}
BENCH=run/splatter_$TAG; mkdir -p $BENCH
PH=""; [ -n "$PHASES" ] && PH="-D REN_PHASES=1"
$PY games/splatter/tools/build.py -D BENCH=1 $PH $EXTRA 2>&1 | grep -i "built\|rror" | tail -3
cp run/splatter/SPLATTER.PRG $BENCH/SPLATTER.PRG
[ -n "$KEEP" ] || $PY games/splatter/tools/build.py 2>&1 | grep -i "rror" | tail -1
rm -f $BENCH/COUNTERS.BIN $BENCH/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --fast-forward true --log-file hatari.log SPLATTER.PRG) > /dev/null 2>&1 &
HP=$!
for i in $(seq ${WAIT:-400}); do sleep 1; [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break; kill -0 $HP 2>/dev/null || break; done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
BENCH=$BENCH python3 - <<'P'
import os, struct
d = open(os.environ['BENCH'] + '/COUNTERS.BIN', 'rb').read()
end, start = struct.unpack('>8L', d[:32]), struct.unpack('>8L', d[32:64])
v, f, p, drop, skip, newc, lv, rv = [a - b for a, b in zip(end, start)]
print("VBLs %d, arcade frames %d, pictures %d (new colours %d), dropped %d, skipped %d" % (v, f, p, newc, drop, skip))
print("arcade frames %.2f /s (arcade 60) = %.0f%%;  pictures %.2f /s" % (50 * f / v, 50 * f / v / 60 * 100, 50 * p / v))
print("logic %.3f VBLs an arcade frame, render %.2f VBLs a picture" % (lv / f, rv / max(p, 1)))
if len(d) >= 104:
    ph = struct.unpack('>10L', d[64:104])
    names = "config fixed list palette newcols bg restore bars objects clipwin".split()
    print("render phases (VBLs):", "  ".join("%s %d" % (n, x) for n, x in zip(names, ph)))
P
