#!/bin/bash
# Speed of Black Tiger in Hatari: a DEBUG + AUTOPLAY build (scripted coin, start, fire and joystick, logic_test inputs, period 3000 ticks) runs 6000 VBLs
# and writes COUNTERS.BIN.
#
#   games/blktiger/tools/bench.sh [hatari items ...]        e.g. shot@60 shot@100;  EXTRA="-D ..." extra build.py options,
#                                                          WAIT=140: seconds before Hatari is stopped; PLAY=1: the
#                                                          recorded play (build/blktiger/play_inputs.bin) instead
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too):
# HATARI may name a renamed copy of the pinned build.  Screenshots: $OUT (default /tmp/hrun_blktiger).
#
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second.  The first VBLs are the boot (no ticks).
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
MODE="-D AUTOPLAY=1"; [ -n "$PLAY" ] && MODE="-D PLAYBACK=1"   # PLAY=1: the recorded play (tools/play_search.py) by game tick
$PY games/blktiger/tools/build.py -D DEBUG=1 $MODE --frames 6000 $EXTRA 2>&1 | grep -v "^(" | tail -1
rm -f run/blktiger/COUNTERS.BIN run/blktiger/RATE.BIN run/blktiger/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun_blktiger}; mkdir -p "$OUT"; rm -f "$OUT/cmd.fifo"
(cd run/blktiger && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" BLKTIGER.PRG) &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for ITEM in "$@" wait@${WAIT:-128}; do
  S=${ITEM##*@}; sleep $((S - T)); T=$S
  case ${ITEM%@*} in shot) printf 'hatari-debug screenshot %s\n' "$OUT/blktiger_$S.png" > "$OUT/cmd.fifo"; sleep 1; T=$((T+1)) ;; esac
done
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f run/blktiger/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 run/blktiger/CRASH.TXT; }
python3 - <<'P'
import struct
v, r, i, miss = struct.unpack('>4H', open('run/blktiger/COUNTERS.BIN', 'rb').read()[:8])
print("VBLs", v, "frames drawn", r, "ticks", i, "background changes missed by the writer hooks", miss)
print("game ticks %.1f /s (arcade 60) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 60 * 100, r / v * 50))
import os
if os.path.exists('run/blktiger/RATE.BIN'):            # the timeline: per 100 VBLs, from the first game tick on
    t = open('run/blktiger/RATE.BIN', 'rb').read()
    pts = [struct.unpack('>2H', t[k:k + 4]) for k in range(0, len(t) - 3, 4)]
    rows = [((b[0] - a[0]) & 0xffff, (b[1] - a[1]) & 0xffff) for a, b in zip(pts, pts[1:])]
    print("per 100 VBLs (ticks/s, pictures/s):", " ".join("%d/%d" % (t2 / 2, p2 / 2) for t2, p2 in rows))
    live = [r for r in rows if r[0]]
    if live:
        print("from the first tick: game ticks %.1f /s (%.0f%%), pictures %.1f /s" % (sum(r[0] for r in live) / len(live) / 2,
              sum(r[0] for r in live) / len(live) / 2 / 60 * 100, sum(r[1] for r in live) / len(live) / 2))
P
