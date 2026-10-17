#!/bin/bash
# Gyruss in its own Hatari (the F030Arcade build; not tools/hatari.sh, which stops every running hatari):
# scripted keys and screenshots, as tools/hatari.sh's items:
#   games/gyruss/tools/shots.sh shot@20 tap:5@25 tap:1@28 down:Right@30 up:Right@36 shot@40 ...
# PRG=... another build (default run/gyruss/GYRUSS.PRG); OUT=dir (default /tmp/gyshots).  Kills only its own Hatari.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/gyshots}
PRG=${PRG:-$ROOT/run/gyruss/GYRUSS.PRG}
RUN=$(dirname "$PRG")
mkdir -p "$OUT"; rm -f "$RUN/CRASH.TXT" "$OUT/cmd.fifo"
cd "$RUN"
"$HATARI" --machine "${MACHINE:-ste}" --memsize 4 ${HATARI_ARGS:-} --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" "$(basename "$PRG")" > /dev/null 2>&1 &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for ITEM in "$@"; do
  WHAT=${ITEM%@*}; S=${ITEM##*@}
  sleep $((S - T)); T=$S
  kill -0 $HP 2>/dev/null || { echo "hatari exited"; break; }
  case $WHAT in
    shot)  printf 'hatari-debug screenshot %s\n' "$OUT/gyruss_$S.png" > "$OUT/cmd.fifo" ;;
    tap:*) printf 'hatari-event keydown %s\n' "${WHAT#tap:}" > "$OUT/cmd.fifo"; sleep 0.2
           printf 'hatari-event keyup %s\n' "${WHAT#tap:}" > "$OUT/cmd.fifo" ;;
    down:*) printf 'hatari-event keydown %s\n' "${WHAT#down:}" > "$OUT/cmd.fifo" ;;
    up:*)   printf 'hatari-event keyup %s\n' "${WHAT#up:}" > "$OUT/cmd.fifo" ;;
    wait)  ;;
    *) echo "bad item $ITEM"; break ;;
  esac
  sleep 1
done
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f "$RUN/CRASH.TXT" ] && { echo "--- CRASH.TXT"; head -10 "$RUN/CRASH.TXT"; }
ls "$OUT"/gyruss_* 2>/dev/null
