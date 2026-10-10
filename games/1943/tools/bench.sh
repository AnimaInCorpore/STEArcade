#!/bin/bash
# Speed of 1943 in Hatari: a DEBUG + AUTOPLAY build (logic_test.py's inputs: coin, start, fire and left / right, period
# 3000 ticks) runs 4000 VBLs and writes COUNTERS.BIN.
#
#   games/1943/tools/bench.sh [hatari items ...]        e.g. shot@60 shot@100;  EXTRA="-D STAGE=9" extra build.py options,
#                                                      VBLS=4000, WAIT=100: seconds before Hatari is stopped
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too):
# HATARI may name a renamed copy of the pinned build.  Screenshots: $OUT (default /tmp/hrun_1943).
#
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second.  The first VBLs are the boot.
# The DEBUG + AUTOPLAY build stays in run/1943/: run port.py build 1943 before playing.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
$PY games/1943/tools/build.py -D DEBUG=1 -D AUTOPLAY=1 --frames ${VBLS:-4000} $EXTRA 2>&1 | grep -v "^(" | tail -1
rm -f run/1943/COUNTERS.BIN run/1943/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun_1943}; mkdir -p "$OUT"; rm -f "$OUT/cmd.fifo"
(cd run/1943 && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" 1943.PRG) &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for ITEM in "$@" wait@${WAIT:-100}; do
  S=${ITEM##*@}
  while [ $T -lt $S ]; do
    [ -f run/1943/COUNTERS.BIN ] && break 2           # (the program has quit after its VBLs)
    sleep 1; T=$((T + 1))
  done
  case ${ITEM%@*} in shot) printf 'hatari-debug screenshot %s\n' "$OUT/1943_$S.png" > "$OUT/cmd.fifo"; sleep 1; T=$((T+1)) ;; esac
done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f run/1943/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 run/1943/CRASH.TXT; }
python3 - <<'P'
import struct
v, r, i, dma, mcu = struct.unpack('>5H', open('run/1943/COUNTERS.BIN', 'rb').read()[:10])
print("VBLs", v, "frames drawn", r, "ticks", i, "sprite list buffers", dma, "MCU replies", mcu)
print("game ticks %.1f /s (arcade 59.6) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 59.6 * 100, r / v * 50))
P
