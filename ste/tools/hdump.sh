#!/bin/bash
# Run a port in the F030Arcade Hatari, wait, grab a screenshot and dump memory ranges (debugger savebin).
#   hdump.sh <port> <seconds> <outprefix> <addr:size> ...   (addresses = map address + text base 0x188E4 are computed by the caller)
set -e
PORT=$1; SECS=$2; PFX=$3; shift 3
STE=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun}
case $PORT in
  bubble) RUN=$STE/run/bublbobl; PRG=BUBBLE.PRG ;;
  *) echo "port?"; exit 1 ;;
esac
mkdir -p "$OUT"; rm -f "$OUT/cmd.fifo"
pkill -x hatari 2>/dev/null || true
cd "$RUN"
"$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" "$PRG" &
HP=$!
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
sleep "$SECS"
printf 'hatari-debug screenshot %s\n' "$OUT/${PFX}.png" > "$OUT/cmd.fifo"
sleep 1
for R in "$@"; do
  A=${R%%:*}; S=${R##*:}
  printf 'hatari-debug savebin %s/%s_%s.bin %s %s\n' "$OUT" "$PFX" "$A" "$A" "$S" > "$OUT/cmd.fifo"
  sleep 1
done
kill $HP 2>/dev/null || true
ls "$OUT"/${PFX}*
