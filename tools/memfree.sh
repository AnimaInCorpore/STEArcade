#!/bin/bash
# How much memory a program gets on a 4 MB STE in Hatari: tools/memfree.s started from the desktop and from an AUTO
# folder.  A port starts if text + data + BSS (its linker map) + 256 fit.  TOS=<image> for another TOS (default 2.06).
#   tools/memfree.sh
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
PY=$ROOT/venv/bin/python; [ -x "$PY" ] || PY=python3
VASM=$("$PY" -c "import sys; sys.path.insert(0, '$ROOT/engine'); import paths; print(paths.VASM)")
W=$(mktemp -d)
mkdir -p "$W/desk" "$W/auto/AUTO"
"$VASM" -Ftos -quiet -o "$W/desk/MEMFREE.PRG" "$ROOT/tools/memfree.s"
cp "$W/desk/MEMFREE.PRG" "$W/auto/AUTO/"
run() {   # dir, extra hatari arguments...
  (cd "$1" && shift && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --sound off --confirm-quit off \
     --log-file "$W/hatari.log" "$@" & P=$!; for i in $(seq 60); do sleep 1; ls "$W"/*/MEMFREE.TXT "$W"/*/*/MEMFREE.TXT >/dev/null 2>&1 && break; done
   sleep 1; kill $P 2>/dev/null; wait $P 2>/dev/null) || true
}
run "$W/desk" MEMFREE.PRG
echo "from the desktop:     $(cat "$W/desk/MEMFREE.TXT" 2>/dev/null || echo '(no result)')"
run "$W/auto" --harddrive "$W/auto"
R=$(cat "$W/auto/MEMFREE.TXT" "$W/auto/AUTO/MEMFREE.TXT" 2>/dev/null || true)
echo "from the AUTO folder: ${R:-(no result)}"
rm -rf "$W"
