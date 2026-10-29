#!/bin/bash
# R-Type in Hatari: the program (build.py, -D options in EXTRA) in its own Hatari, the items, then Esc; COUNTERS.BIN read.
#
#   games/rtype/tools/bench.sh [hatari items ...]          e.g. shot@20 tap:06@25 tap:02@27 down:57@30 shot@60 up:57@61
#   EXTRA="-D PIC_EVERY=3" WAIT=200 games/rtype/tools/bench.sh ...
#   MEMSIZE=14 games/rtype/tools/bench.sh ...   (Hatari ST RAM in MB, default 4: test builds larger than a 4 MB STE)
#
# Hatari (the F030Arcade build; HATARI / TOS override) is started here and stopped by its PID, never by tools/hatari.sh
# (that one stops every running "hatari").  Items as in tools/hatari.sh: shot@s, tap:K@s (scancodes in hex: 06 coin 1,
# 02 start 1, 39 space = fire, 38 alternate = the Force, 4d / 4b / 48 / 50 the cursor keys), down:K@s / up:K@s,
# hold:K@s, dbg:CMD@s.  Screenshots -> build/rtype/bench_<s>.png.  After the last item Esc quits (COUNTERS.BIN: VBLs,
# arcade frames, pictures, frames dropped, pictures skipped, renderer calls without a picture); a crash: CRASH.TXT.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
BENCH=run/rtype_bench; mkdir -p $BENCH
$PY games/rtype/tools/build.py $EXTRA 2>&1 | grep -E "^built|rror" | tail -2
cp run/rtype/RTYPE.PRG $BENCH/
rm -f $BENCH/COUNTERS.BIN $BENCH/CRASH.TXT $BENCH/cmd.fifo
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize ${MEMSIZE:-4} --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --cmd-fifo cmd.fifo --log-file hatari.log RTYPE.PRG) > $BENCH/hatari.out 2>&1 &
HP=$!
START=$SECONDS
FIFO=$BENCH/cmd.fifo
for i in $(seq 50); do [ -p $FIFO ] && break; sleep 0.2; done
T=0
for ITEM in "$@"; do
  WHAT=${ITEM%@*}; S=${ITEM##*@}
  [ $S -gt $T ] && sleep $((S - T)); T=$S
  kill -0 $HP 2>/dev/null || { echo "hatari exited"; break; }
  case $WHAT in
    shot)   printf 'hatari-debug screenshot %s\n' "$ROOT/build/rtype/bench_$S.png" > $FIFO ;;
    tap:*)  printf 'hatari-event keydown %s\n' "${WHAT#tap:}" > $FIFO; sleep 0.3
            printf 'hatari-event keyup %s\n' "${WHAT#tap:}" > $FIFO ;;
    hold:*) printf 'hatari-event keydown %s\n' "${WHAT#hold:}" > $FIFO; sleep 0.7
            printf 'hatari-event keyup %s\n' "${WHAT#hold:}" > $FIFO ;;
    down:*) printf 'hatari-event keydown %s\n' "${WHAT#down:}" > $FIFO ;;
    up:*)   printf 'hatari-event keyup %s\n' "${WHAT#up:}" > $FIFO ;;
    dbg:*)  printf 'hatari-debug %s\n' "${WHAT#dbg:}" > $FIFO ;;
    *) echo "bad item $ITEM"; break ;;
  esac
done
sleep 1
if kill -0 $HP 2>/dev/null && [ ! -f $BENCH/CRASH.TXT ]; then
  printf 'hatari-event keypress 01\n' > $FIFO
fi
while [ $((SECONDS - START)) -lt ${WAIT:-400} ]; do
  [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break
  kill -0 $HP 2>/dev/null || break
  sleep 1
done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -3 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import struct
v, lg, pic, drop, skip, late = struct.unpack('>6I', open('run/rtype_bench/COUNTERS.BIN', 'rb').read()[:24])
s = v / 50.0
print("%d VBLs (%.1f s): arcade frames %d (%.1f /s, the arcade 55.0: %.0f%%), pictures %d (%.1f /s), dropped %d, "
      "skipped %d, renderer calls without a picture %d" % (v, s, lg, lg / s, lg / s / 55.017 * 100, pic, pic / s, drop,
                                                            skip, late))
P
