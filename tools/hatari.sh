#!/bin/bash
# Run a port in the F030Arcade Hatari (the pinned, corrected build); optionally press keys, grab screenshots and
# dump memory at given times.
#   tools/hatari.sh <game> [item@seconds ...]          game: one of port.py list (it knows the program's name)
#   items (in time order):  shot@60                    screenshot  -> $OUT/<game>_60.png
#                           key:5@20                   key press (Hatari key name: 5 = coin 1, 1 = start 1, Left, space ...)
#                           hold:5@20                  key held for 0.7 s (down:KEY / up:KEY: held until up)   wait@90: just keep running
#                           tap:5@20                   key held for 0.2 s (coins: 1942 ignores a coin held for 40 ticks)
#                           dbg:COMMAND@50             a debugger command (dbg:profile on, dbg:profile save /tmp/p.txt ...)
#                           dump:0xADDR:0xSIZE@50      memory dump (debugger savebin) -> $OUT/<game>_<s>_<ADDR>.bin
#   MACHINE=megaste (default ste), HATARI_ARGS='--cpuclock 16': other Hatari options.
#   MEMSIZE: Hatari's ST RAM in MB (4; R-Type alone 14: its stage-renderer test builds are larger than a 4 MB STE until
#   the per-stage data loads from disk - the user, 2026-10-30).
#   no items: run interactively.   A CRASH.TXT written by the program is printed.
# The program is started from run/<game>/ (its GEMDOS drive: CRASH.TXT and dumps go there).  $OUT defaults to /tmp/hrun.
set -e
GAME=${1:-galaga}; shift || true
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${OUT:-/tmp/hrun}
PY=$ROOT/venv/bin/python; [ -x "$PY" ] || PY=python3
PRG=${PRG:-$("$PY" "$ROOT/port.py" prg "$GAME")} || { echo "unknown game $GAME:"; "$PY" "$ROOT/port.py" list; exit 1; }
RUN=${RUN:-$ROOT/run/$GAME}
if [ "$GAME" = rtype ]; then MEMSIZE=${MEMSIZE:-14}; fi
mkdir -p "$OUT"; rm -f "$RUN/CRASH.TXT" "$OUT/cmd.fifo"
pkill -x hatari 2>/dev/null || true
cd "$RUN"
"$HATARI" --machine "${MACHINE:-ste}" --memsize ${MEMSIZE:-4} ${HATARI_ARGS:-} --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
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
    hold:*) printf 'hatari-event keydown %s\n' "${WHAT#hold:}" > "$OUT/cmd.fifo"; sleep 0.7   # (games that poll the keys once a tick)
            printf 'hatari-event keyup %s\n' "${WHAT#hold:}" > "$OUT/cmd.fifo" ;;
    tap:*) printf 'hatari-event keydown %s\n' "${WHAT#tap:}" > "$OUT/cmd.fifo"; sleep 0.2
           printf 'hatari-event keyup %s\n' "${WHAT#tap:}" > "$OUT/cmd.fifo" ;;
    down:*) printf 'hatari-event keydown %s\n' "${WHAT#down:}" > "$OUT/cmd.fifo" ;;
    up:*)   printf 'hatari-event keyup %s\n' "${WHAT#up:}" > "$OUT/cmd.fifo" ;;
    wait)  ;;
    dbg:*) printf 'hatari-debug %s\n' "${WHAT#dbg:}" > "$OUT/cmd.fifo" ;;
    dump:*) R=${WHAT#dump:}; A=${R%%:*}; Z=${R##*:}
            printf 'hatari-debug savebin %s/%s_%s_%s.bin %s %s\n' "$OUT" "$GAME" "$S" "$A" "$A" "$Z" > "$OUT/cmd.fifo" ;;
    *) echo "bad item $ITEM"; break ;;
  esac
  sleep 1
done
kill $HP 2>/dev/null || true
[ -f "$RUN/CRASH.TXT" ] && { echo "--- CRASH.TXT"; head -40 "$RUN/CRASH.TXT"; }
ls "$OUT"/${GAME}_* 2>/dev/null || true
