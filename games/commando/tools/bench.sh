#!/bin/bash
# Speed of Commando in Hatari: a DEBUG + AUTOPLAY build (scripted coin, start, fire and joystick, period 3000 frames) runs 6000 VBLs
# and writes COUNTERS.BIN.
#
#   games/commando/tools/bench.sh [hatari items ...]        e.g. shot@60 shot@100;  EXTRA="-D ..." extra build.py options,
#                                                          PLAY=1: the recorded play (build/commando/play_inputs.bin) instead,
#                                                          WAIT=400: seconds before Hatari is stopped at the latest
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too):
# HATARI may name a renamed copy of the pinned build.  Screenshots: $OUT (default /tmp/hrun_commando).
#
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second.  The first VBLs are the boot (no ticks).
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
MODE="-D AUTOPLAY=1"; [ -n "$PLAY" ] && MODE="-D PLAYBACK=1"   # PLAY=1: the recorded play (tools/play_search.py) by game tick
$PY games/commando/tools/build.py -D DEBUG=1 $MODE --frames 6000 $EXTRA 2>&1 | grep -v "^(" | tail -1
rm -f run/commando/COUNTERS.BIN run/commando/RATE.BIN run/commando/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun_commando}; mkdir -p "$OUT"; rm -f "$OUT/cmd.fifo"
(cd run/commando && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" COMMANDO.PRG) &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for ITEM in "$@"; do
  S=${ITEM##*@}; sleep $((S - T)); T=$S
  case ${ITEM%@*} in shot) printf 'hatari-debug screenshot %s\n' "$OUT/commando_$S.png" > "$OUT/cmd.fifo"; sleep 1; T=$((T+1)) ;; esac
done
# (the program writes COUNTERS.BIN when its 6000 VBLs are done: waited for, at most WAIT seconds in all; a busy host
# makes Hatari slower than real time)
while [ $T -lt ${WAIT:-400} ] && [ ! -f run/commando/COUNTERS.BIN ] && kill -0 $HP 2>/dev/null; do sleep 1; T=$((T+1)); done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f run/commando/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 run/commando/CRASH.TXT; }
python3 - <<'P'
import struct
d = open('run/commando/COUNTERS.BIN', 'rb').read()
v, h, r, b, i = struct.unpack('>5H', d[:10])
print("VBLs", v, "frames drawn", r, "ticks", i)
print("game ticks %.1f /s (arcade 59.6) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 59.6 * 100, r / v * 50))
import os
if os.path.exists('run/commando/RATE.BIN'):            # the timeline: per 100 VBLs, from the first game tick on
    t = open('run/commando/RATE.BIN', 'rb').read()
    pts = [struct.unpack('>2H', t[k:k + 4]) for k in range(0, len(t) - 3, 4)]
    rows = [((b[0] - a[0]) & 0xffff, (b[1] - a[1]) & 0xffff) for a, b in zip(pts, pts[1:])]
    rows = [r for r in rows]
    print("per 100 VBLs (ticks/s, pictures/s):", " ".join("%d/%d" % (t2 / 2, p2 / 2) for t2, p2 in rows))
    live = [r for r in rows if r[0]]
    if live:
        print("from the first tick: game ticks %.1f /s (%.0f%%), pictures %.1f /s" % (sum(r[0] for r in live) / len(live) / 2,
              sum(r[0] for r in live) / len(live) / 2 / 59.6 * 100, sum(r[1] for r in live) / len(live) / 2))
P
