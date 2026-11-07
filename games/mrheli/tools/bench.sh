#!/bin/bash
# Mr. HELI in Hatari (from R-Type's bench.sh of 138cd90): the program (build.py, -D options in EXTRA) in its own Hatari, the items, then Esc; COUNTERS.BIN read.
#
#   games/mrheli/tools/bench.sh [hatari items ...]          e.g. shot@20 tap:06@25 tap:02@27 down:57@30 shot@60 up:57@61
#   EXTRA="-D PIC_EVERY=3" WAIT=200 games/mrheli/tools/bench.sh ...
#   FAST=true NOESC=1 games/mrheli/tools/bench.sh   (Hatari's fast forward: the counters are emulated VBLs, so the
#                                                same numbers sooner; NOESC: no Esc after the items - for PLAYBACK
#                                                runs, which quit at the end of their inputs)
#   REPLAY=8:3000:8000 FAST=true NOESC=1 EXTRA="-D INVULN -D PLAYBACK -D DEBUG" games/mrheli/tools/bench.sh
#                                                (a replay point: the game from seed 8's arcade frame 3000 to 8000)
#   HATARI_ARGS="--avirecord true --avi-file /abs/path.avi" games/mrheli/tools/bench.sh shot@40   (a video)
#   MEMSIZE=4 games/mrheli/tools/bench.sh ...    (Hatari ST RAM in MB, default 14)
#   NOBUILD=1 games/mrheli/tools/bench.sh ...    (run/mrheli/MRHELI.PRG as it is)
#
# Hatari (the F030Arcade build; HATARI / TOS override) is started here and stopped by its PID, never by tools/hatari.sh
# (that one stops every running "hatari").  Items as in tools/hatari.sh: shot@s, tap:K@s (scancodes in hex: 06 coin 1,
# 02 start 1, 39 space = fire, 38 alternate = button 2, 4d / 4b / 48 / 50 the cursor keys), down:K@s / up:K@s,
# hold:K@s, dbg:CMD@s.  Screenshots -> build/mrheli/bench_<s>.png.  After the last item Esc quits (COUNTERS.BIN: VBLs,
# arcade frames, pictures, frames dropped, pictures skipped, renderer calls without a picture); a crash: CRASH.TXT.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python; [ -x $PY ] || PY=python3
BENCH=run/mrheli_bench; mkdir -p $BENCH
if [ -n "$REPLAY" ]; then                       # REPLAY=seed:frame[:end]: start there, PLAYBACK to end (8000)
  IFS=: read RSEED RFRAME REND <<< "$REPLAY"
  $PY games/mrheli/tools/play_inputs.py --seed $RSEED --start $RFRAME --frames ${REND:-8000} | tail -1
  export REPLAY="$RSEED:$RFRAME"
fi
if [ -z "$NOBUILD" ]; then
  OUT=$($PY games/mrheli/tools/build.py $EXTRA 2>&1 | grep -E "^built|rror" | tail -2); echo "$OUT"
  case "$OUT" in *built*) ;; *) echo "build failed"; exit 1;; esac
fi
cp run/mrheli/MRHELI.PRG $BENCH/
rm -f $BENCH/COUNTERS.BIN $BENCH/CRASH.TXT $BENCH/cmd.fifo $BENCH/BORDERS.BIN
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize ${MEMSIZE:-14} --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --fast-forward ${FAST:-false} --confirm-quit off --statusbar false --cmd-fifo cmd.fifo --log-file hatari.log $HATARI_ARGS MRHELI.PRG) > $BENCH/hatari.out 2>&1 &
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
    shot)   printf 'hatari-debug screenshot %s\n' "$ROOT/build/mrheli/bench_$S.png" > $FIFO ;;
    burst)  for k in 0 1 2 3 4 5 6 7 8 9; do
              printf 'hatari-debug screenshot %s\n' "$ROOT/build/mrheli/burst_${S}_$k.png" > $FIFO; sleep 0.13
            done ;;
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
if [ -z "$NOESC" ] && kill -0 $HP 2>/dev/null && [ ! -f $BENCH/CRASH.TXT ]; then
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
RATE=50.0; case "$EXTRA" in *TICK55*) RATE=55.017;; esac; export RATE
python3 - <<'P'
import os
import struct
raw = open('run/mrheli_bench/COUNTERS.BIN', 'rb').read()
v, lg, pic, drop, skip, late = struct.unpack('>6I', raw[:24])
s = v / 50.0
rate = float(os.environ.get("RATE", "50"))
print("%d VBLs (%.1f s): arcade frames %d (%.1f /s, the target %.1f: %.0f%%), pictures %d (%.1f /s), dropped %d, "
      "skipped %d, renderer calls without a picture %d" % (v, s, lg, lg / s, rate, lg / s / rate * 100, pic, pic / s,
                                                            drop, skip, late))
if len(raw) >= 40:
    st = struct.unpack('>%dI' % ((len(raw) - 24) // 4), raw[24:])
    names = ["waiting", "logic", "drawing", "between", "palette", "vram", "compose", "sync", "sprites", "bar"]
    n = st[17] if len(st) > 17 and st[17] else v       # (PROF: Timer C samples, else VBLs)
    print("%s sampled: " % ("Timer C" if n != v else "VBLs") +
          ", ".join("%s %d%%" % (k, 100 * x // max(1, n)) for k, x in zip(names, st) if x))
import os
if os.path.exists('run/mrheli_bench/BORDERS.BIN'):
    b = open('run/mrheli_bench/BORDERS.BIN', 'rb').read()
    fb, lt, lo, ll, lf = struct.unpack('>5H', b[:10])
    print("borders: frames with the top border armed late (fallbacks) %d, late events: top %d, palette on %d, "
          "bottom %d, off %d" % (fb, lt, lo, ll, lf))
P
