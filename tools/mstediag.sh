#!/bin/bash
# MSTEDIAG.PRG (tools/mstediag.s) in Hatari: built, started from the desktop on an STE and on a Mega STE (TOS 2.06,
# 4 MB), and the MSTEDIAG.TXT of each run printed.  The program stays in its live view; the run ends when the file
# is there.  OUT=<dir>: the built MSTEDIAG.PRG is copied there (for a tester).  TOS=<image> for another TOS.
#   tools/mstediag.sh
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
PY=$ROOT/venv/bin/python; [ -x "$PY" ] || PY=python3
VASM=$("$PY" -c "import sys; sys.path.insert(0, '$ROOT/engine'); import paths; print(paths.VASM)")
W=$(mktemp -d)
"$VASM" -Ftos -quiet -nowarn=2047 -I "$ROOT/engine/rt" -o "$W/MSTEDIAG.PRG" "$ROOT/tools/mstediag.s"
[ -n "$OUT" ] && mkdir -p "$OUT" && cp "$W/MSTEDIAG.PRG" "$OUT/"
run() {   # machine
  mkdir -p "$W/$1" && cp "$W/MSTEDIAG.PRG" "$W/$1/"
  (cd "$W/$1" && exec "$HATARI" --machine "$1" --memsize 4 --tos "$TOS" --fast-boot true --sound off --confirm-quit off \
     --log-file "$W/hatari_$1.log" MSTEDIAG.PRG & P=$!
   for i in $(seq 60); do sleep 1; [ -s "$W/$1/MSTEDIAG.TXT" ] && break; done
   sleep 1; kill $P 2>/dev/null; wait $P 2>/dev/null) || true
  echo "--- $1"
  tr -d '\r' < "$W/$1/MSTEDIAG.TXT" 2>/dev/null | sed 's/\x1bK//g' || echo "(no result)"
}
run ste
run megaste
rm -rf "$W"
