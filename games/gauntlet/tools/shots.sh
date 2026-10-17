#!/bin/bash
# Gauntlet in its own Hatari (the F030Arcade build; not tools/hatari.sh, which stops every running hatari):
# scripted keys, screenshots and memory dumps (dump:0xADDR:0xSIZE), as tools/hatari.sh's items.  A key is a single
# letter or digit (mapped through TOS's layout: German TOS swaps y / z) or an ST scancode (0x4d right, 0x4b left, 0x48 up,
# 0x50 down, 0x39 space = fire, 0x2d x = magic / start, 0x06 5 = coin 1); Hatari takes no other key names:
#   games/gauntlet/tools/shots.sh shot@20 down:Right@30 up:Right@36 shot@40 ...
# PRG=... another build (default run/gauntlet/GAUNTLET.PRG); OUT=dir (default /tmp/gshots).  Kills only its own Hatari.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/gshots}
PRG=${PRG:-$ROOT/run/gauntlet/GAUNTLET.PRG}
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
    shot)  printf 'hatari-debug screenshot %s\n' "$OUT/gauntlet_$S.png" > "$OUT/cmd.fifo" ;;
    tap:*) printf 'hatari-event keydown %s\n' "${WHAT#tap:}" > "$OUT/cmd.fifo"; sleep 0.2
           printf 'hatari-event keyup %s\n' "${WHAT#tap:}" > "$OUT/cmd.fifo" ;;
    down:*) printf 'hatari-event keydown %s\n' "${WHAT#down:}" > "$OUT/cmd.fifo" ;;
    up:*)   printf 'hatari-event keyup %s\n' "${WHAT#up:}" > "$OUT/cmd.fifo" ;;
    wait)  ;;
    dump:*) R=${WHAT#dump:}; A=${R%%:*}; Z=${R##*:}
            printf 'hatari-debug savebin %s/gauntlet_%s_%s.bin %s %s\n' "$OUT" "$S" "$A" "$A" "$Z" > "$OUT/cmd.fifo" ;;
    *) echo "bad item $ITEM"; break ;;
  esac
  sleep 1
done
kill $HP 2>/dev/null; wait $HP 2>/dev/null
# (no CRASH.TXT: the program keeps no TOS; a crash turns the screen red and leaves its record at $3C1000)
ls "$OUT"/gauntlet_* 2>/dev/null
