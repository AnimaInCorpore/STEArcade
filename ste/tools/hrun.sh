#!/bin/bash
# Run a port in the F030Arcade Hatari (the pinned, corrected build) and optionally grab screenshots.
#   hrun.sh galaga|dkong [seconds-before-shot ...]     no seconds: run interactively
# Screenshots land in $OUT (default /tmp/hrun) as <port>_<seconds>.png.
set -e
PORT=${1:-galaga}; shift || true
STE=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun}
case $PORT in
  galaga) RUN=$STE/run/galaga; PRG=GALAGA.PRG ;;
  dkong)  RUN=$STE/run; PRG=DKONG.PRG ;;
  *) echo "unknown port $PORT"; exit 1 ;;
esac
mkdir -p "$OUT"; rm -f "$RUN/CRASH.TXT" "$OUT/cmd.fifo"
pkill -x hatari 2>/dev/null || true
cd "$RUN"
"$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" "$PRG" &
HP=$!
if [ $# -eq 0 ]; then wait $HP; exit 0; fi
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for S in "$@"; do
  sleep $((S - T)); T=$S
  kill -0 $HP 2>/dev/null || { echo "hatari exited"; break; }
  printf 'hatari-debug screenshot %s\n' "$OUT/${PORT}_$S.png" > "$OUT/cmd.fifo"
  sleep 1
done
kill $HP 2>/dev/null || true
[ -f "$RUN/CRASH.TXT" ] && { echo "--- CRASH.TXT"; cat "$RUN/CRASH.TXT"; }
ls "$OUT"/*.png
