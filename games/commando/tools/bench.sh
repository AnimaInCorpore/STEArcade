#!/bin/bash
# Speed of Commando in Hatari: a DEBUG + AUTOPLAY build (scripted coin, start, fire and joystick, period 3000 frames) runs 6000 VBLs
# and writes COUNTERS.BIN.
#
#   games/commando/tools/bench.sh [hatari items ...]        e.g. shot@60 shot@100;  EXTRA="-D ..." extra build.py options,
#                                                          WAIT=140: seconds before Hatari is stopped
# Hatari is started here, not by tools/hatari.sh (that one stops every running "hatari" first, other benchmarks too):
# HATARI may name a renamed copy of the pinned build.  Screenshots: $OUT (default /tmp/hrun_commando).
#
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second.  The first VBLs are the boot (no ticks).
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
$PY games/commando/tools/build.py -D DEBUG=1 -D AUTOPLAY=1 --frames 6000 $EXTRA 2>&1 | grep -v "^(" | tail -1
rm -f run/commando/COUNTERS.BIN run/commando/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun_commando}; mkdir -p "$OUT"; rm -f "$OUT/cmd.fifo"
(cd run/commando && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" COMMANDO.PRG) &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for ITEM in "$@" wait@${WAIT:-128}; do
  S=${ITEM##*@}; sleep $((S - T)); T=$S
  case ${ITEM%@*} in shot) printf 'hatari-debug screenshot %s\n' "$OUT/commando_$S.png" > "$OUT/cmd.fifo"; sleep 1; T=$((T+1)) ;; esac
done
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f run/commando/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 run/commando/CRASH.TXT; }
python3 - <<'P'
import struct
d = open('run/commando/COUNTERS.BIN', 'rb').read()
v, h, r, b, i = struct.unpack('>5H', d[:10])
print("VBLs", v, "frames drawn", r, "ticks", i)
print("game ticks %.1f /s (arcade 59.6) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 59.6 * 100, r / v * 50))
P
