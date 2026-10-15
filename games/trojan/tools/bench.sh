#!/bin/bash
# Trojan in the pinned F030Arcade Hatari: a DEBUG + AUTOPLAY build (src/trojan.s ap_inputs: a coin, the start, then
# walking right with attacks and jumps, the lives kept; period 3000 arcade frames) runs FRAMES VBLs (default 6000)
# and writes COUNTERS.BIN and RATE.BIN.
#
#   games/trojan/tools/bench.sh [items ...]     items: shot@SECONDS (a screenshot -> $OUT/trojan_<s>.png)
#   EXTRA="-D ..."   more build.py options;  PLAY=1  the recorded play (build/trojan/play_inputs.bin, PLAYBACK) instead;
#   NOBUILD=1        run the program as it is (run/trojan/TROJAN.PRG);  WAIT=400  seconds before Hatari is stopped
#
# Hatari is started here (its own instance, stopped by its PID; tools/hatari.sh would stop every running "hatari").
# Reports the logic rate (arcade frames a second; the arcade: 55.4) and the picture rate (pictures drawn a second)
# separately, from the first arcade frame on.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
MODE="-D AUTOPLAY=1"; [ -n "$PLAY" ] && MODE="-D PLAYBACK=1"
N=${FRAMES:-6000}
if [ -z "$NOBUILD" ]; then
  $PY games/trojan/tools/build.py -D DEBUG=1 $MODE --frames $N $EXTRA 2>&1 | grep -v "^(" | tail -1
fi
rm -f run/trojan/COUNTERS.BIN run/trojan/RATE.BIN run/trojan/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun_trojan}; mkdir -p "$OUT"; rm -f "$OUT/cmd.fifo"
(cd run/trojan && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" TROJAN.PRG) &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for ITEM in "$@"; do
  S=${ITEM##*@}; sleep $((S - T)); T=$S
  case ${ITEM%@*} in shot) printf 'hatari-debug screenshot %s\n' "$OUT/trojan_$S.png" > "$OUT/cmd.fifo"; sleep 1; T=$((T+1)) ;; esac
done
while [ $T -lt ${WAIT:-400} ] && [ ! -f run/trojan/COUNTERS.BIN ] && kill -0 $HP 2>/dev/null; do sleep 1; T=$((T+1)); done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f run/trojan/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 run/trojan/CRASH.TXT; }
[ -f run/trojan/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import struct, os
d = open('run/trojan/COUNTERS.BIN', 'rb').read()
v, r, t = struct.unpack('>3H', d[:6])
late = struct.unpack('>5H', d[8:18])
print("VBLs %d, pictures %d, arcade frames %d; border events: fallbacks %d, late top %d / on %d / low %d / off %d" % ((v, r, t) + late))
if os.path.exists('run/trojan/RATE.BIN'):            # per 100 VBLs: the arcade frames and pictures so far
    s = open('run/trojan/RATE.BIN', 'rb').read()
    pts = [struct.unpack('>2H', s[k:k + 4]) for k in range(0, len(s) - 3, 4)]
    rows = [((b[0] - a[0]) & 0xffff, (b[1] - a[1]) & 0xffff) for a, b in zip(pts, pts[1:])]
    live = [x for x in rows if x[0]]
    print("per 100 VBLs (logic frames/s, pictures/s):", " ".join("%d/%d" % (a / 2, b / 2) for a, b in rows))
    if live:
        lf = sum(x[0] for x in live) / len(live) / 2
        pf = sum(x[1] for x in live) / len(live) / 2
        print("from the first arcade frame: logic %.1f frames/s (%.0f%% of the arcade's 55.4), pictures %.1f /s" % (lf, lf / 55.4 * 100, pf))
P
