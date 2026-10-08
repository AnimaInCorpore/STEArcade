#!/bin/bash
# Run Bubble Bobble in the F030Arcade Hatari, press keys at given times and grab screenshots.
#   hplay.sh <name> key:seconds ... shot:seconds ...     e.g. hplay.sh t 5:20 1:25 shot:60
# keys are Hatari key names (5 = coin 1, 1 = start 1, Left, Right, space); screenshots /tmp/hrun/<name>_<s>.png
set -e
NAME=$1; shift
STE=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun}
mkdir -p "$OUT"; rm -f "$OUT/cmd.fifo"
pkill -x hatari 2>/dev/null || true
cd "$STE/run/bublbobl"; rm -f CRASH.TXT
"$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" BUBBLE.PRG &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for A in "$@"; do
  K=${A%%:*}; S=${A##*:}
  sleep $((S - T)); T=$S
  if [ "$K" = shot ]; then printf 'hatari-debug screenshot %s/%s_%s.png\n' "$OUT" "$NAME" "$S" > "$OUT/cmd.fifo"
  else printf 'hatari-event keypress %s\n' "$K" > "$OUT/cmd.fifo"; fi
  sleep 0.5
done
kill $HP 2>/dev/null || true
[ -f CRASH.TXT ] && head -3 CRASH.TXT
ls "$OUT"/${NAME}_*.png
