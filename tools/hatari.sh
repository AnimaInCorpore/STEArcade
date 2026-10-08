#!/bin/bash
# Run a port in the F030Arcade Hatari (the pinned, corrected build); optionally press keys, grab screenshots and
# dump memory at given times.
#   tools/hatari.sh <game> [item@seconds ...]          game: dkong | galaga | bublbobl | 1942
#   items (in time order):  shot@60                    screenshot  -> $OUT/<game>_60.png
#                           key:5@20                   key press (Hatari key name: 5 = coin 1, 1 = start 1, Left, space ...)
#                           dump:0xADDR:0xSIZE@50      memory dump (debugger savebin) -> $OUT/<game>_<s>_<ADDR>.bin
#   no items: run interactively.   A CRASH.TXT written by the program is printed.
# The program is started from run/<game>/ (it loads its ROM files from there).  $OUT defaults to /tmp/hrun.
set -e
GAME=${1:-galaga}; shift || true
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun}
case $GAME in
  galaga)   PRG=${PRG:-GALAGA.PRG} ;;
  dkong)    PRG=${PRG:-DKONG.PRG} ;;
  bublbobl) PRG=${PRG:-BUBBLE.PRG} ;;
  *) echo "unknown game $GAME (dkong | galaga | bublbobl | 1942)"; exit 1 ;;
esac
RUN=${RUN:-$ROOT/run/$GAME}
mkdir -p "$OUT"; rm -f "$RUN/CRASH.TXT" "$OUT/cmd.fifo"
pkill -x hatari 2>/dev/null || true
cd "$RUN"
"$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --cmd-fifo "$OUT/cmd.fifo" --log-file "$OUT/hatari.log" "$PRG" &
HP=$!
if [ $# -eq 0 ]; then wait $HP; exit 0; fi
for i in $(seq 50); do [ -p "$OUT/cmd.fifo" ] && break; sleep 0.2; done
T=0
for ITEM in "$@"; do
  WHAT=${ITEM%@*}; S=${ITEM##*@}
  sleep $((S - T)); T=$S
  kill -0 $HP 2>/dev/null || { echo "hatari exited"; break; }
  case $WHAT in
    shot)  printf 'hatari-debug screenshot %s\n' "$OUT/${GAME}_$S.png" > "$OUT/cmd.fifo" ;;
    key:*) printf 'hatari-event keypress %s\n' "${WHAT#key:}" > "$OUT/cmd.fifo" ;;
    dump:*) R=${WHAT#dump:}; A=${R%%:*}; Z=${R##*:}
            printf 'hatari-debug savebin %s/%s_%s_%s.bin %s %s\n' "$OUT" "$GAME" "$S" "$A" "$A" "$Z" > "$OUT/cmd.fifo" ;;
    *) echo "bad item $ITEM"; break ;;
  esac
  sleep 1
done
kill $HP 2>/dev/null || true
[ -f "$RUN/CRASH.TXT" ] && { echo "--- CRASH.TXT"; head -40 "$RUN/CRASH.TXT"; }
ls "$OUT"/${GAME}_* 2>/dev/null || true
