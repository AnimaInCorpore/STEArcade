#!/bin/bash
# Speed of 1942 in Hatari: a DEBUG + AUTOPLAY build (scripted coin, start, fire and joystick, MAME's cheats for 1942b: lives, invincibility
# and, with a period, "Finish Current Level Now!" to reach the later stages) runs 6000 VBLs and writes COUNTERS.BIN.
#
#   games/1942/tools/bench.sh [finish_period] [hatari items ...]      finish_period: frames between level skips, 0 = none (default)
#   EXTRA="-D NOTICK60=1" games/1942/tools/bench.sh 600 shot@70      extra build.py options;  WAIT=128: seconds at most
#
# The DEBUG build goes to run/1942_bench (with the ROM bank files of run/1942), run/1942 keeps the normal build.  Hatari is
# started here and stopped by its PID, not by tools/hatari.sh (that one stops every running "hatari", other benchmarks
# and the user's sessions too); HATARI / TOS may point at other builds.  Items as in tools/hatari.sh (shot@s, key:K@s,
# hold:/tap:/down:/up:K@s, dbg:CMD@s, dump:0xADDR:0xSIZE@s; screenshots and dumps -> run/1942_bench); after them the
# bench waits for COUNTERS.BIN (written when the 6000 VBLs are done), at most WAIT seconds from the start.
#
# Reports the game ticks a second (the arcade: 59.6), the frames drawn a second, a histogram of the VBLs between two ticks and the
# time the CPU idled.  The first 300 VBLs are the boot (no ticks): 95% of 59.6 is full speed.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
FIN=${1:-0}; shift
PY=venv/bin/python; [ -x $PY ] || PY=python3
BENCH=run/1942_bench; mkdir -p $BENCH
[ -f run/1942/srb-03.m3 ] || $PY games/1942/tools/build.py 2>&1 | grep -v translated | tail -1   # (the ROM bank files)
cp run/1942/srb-0* $BENCH/
$PY games/1942/tools/build.py -D DEBUG=1 -D AUTOPLAY=1 $( [ "$FIN" != 0 ] && echo -D FINISH=$FIN ) --frames 6000 $EXTRA \
  --out "$ROOT/$BENCH/1942.PRG" 2>&1 | grep -v translated | tail -2
rm -f $BENCH/COUNTERS.BIN $BENCH/CRASH.TXT $BENCH/cmd.fifo
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --cmd-fifo cmd.fifo --log-file hatari.log 1942.PRG) > $BENCH/hatari.out 2>&1 &
HP=$!
START=$SECONDS
FIFO=$BENCH/cmd.fifo
for i in $(seq 50); do [ -p $FIFO ] && break; sleep 0.2; done
T=0
for ITEM in "$@"; do
  WHAT=${ITEM%@*}; S=${ITEM##*@}
  sleep $((S - T)); T=$S
  kill -0 $HP 2>/dev/null || { echo "hatari exited"; break; }
  case $WHAT in
    shot)   printf 'hatari-debug screenshot %s\n' "$ROOT/$BENCH/1942_$S.png" > $FIFO ;;
    key:*)  printf 'hatari-event keypress %s\n' "${WHAT#key:}" > $FIFO ;;
    hold:*) printf 'hatari-event keydown %s\n' "${WHAT#hold:}" > $FIFO; sleep 0.7
            printf 'hatari-event keyup %s\n' "${WHAT#hold:}" > $FIFO ;;
    tap:*)  printf 'hatari-event keydown %s\n' "${WHAT#tap:}" > $FIFO; sleep 0.2
            printf 'hatari-event keyup %s\n' "${WHAT#tap:}" > $FIFO ;;
    down:*) printf 'hatari-event keydown %s\n' "${WHAT#down:}" > $FIFO ;;
    up:*)   printf 'hatari-event keyup %s\n' "${WHAT#up:}" > $FIFO ;;
    wait)   ;;
    dbg:*)  printf 'hatari-debug %s\n' "${WHAT#dbg:}" > $FIFO ;;
    dump:*) R=${WHAT#dump:}; A=${R%%:*}; Z=${R##*:}
            printf 'hatari-debug savebin %s/1942_%s_%s.bin %s %s\n' "$ROOT/$BENCH" "$S" "$A" "$A" "$Z" > $FIFO ;;
    *) echo "bad item $ITEM"; break ;;
  esac
  sleep 1
done
while [ $((SECONDS - START)) -lt ${WAIT:-128} ]; do
  [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break
  kill -0 $HP 2>/dev/null || break
  sleep 1
done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import struct
d = open('run/1942_bench/COUNTERS.BIN', 'rb').read()
v, h, r, b, i = struct.unpack('>5H', d[:10]); hist = struct.unpack('>10H', d[10:30])
ib, idf, pieced = struct.unpack('>3I', d[30:42]); bd = struct.unpack('>5H', d[42:52])
print("VBLs between two ticks, 0..9+:", hist)
print("idle spins: no free ring", ib, "nothing to do", idf, "; Blitter passes run in pieces", pieced)
print("borders: top border armed by the VBL in %d frames; events that started too late: top border %d, palette on %d, bottom border %d, palette off %d" % bd)
print("VBLs", v, "frames drawn", r, "ticks", i)
print("game ticks %.1f /s (arcade 59.6) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 59.6 * 100, r / v * 50))
P
