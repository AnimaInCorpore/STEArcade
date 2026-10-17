#!/bin/bash
# engine/rt/hdd.s on an emulated hard disk: builds tools/hddtest.s, a 32 MB disk image (an MBR, one FAT16
# partition) holding HDDTEST.DAT (640 KB, sector i = the longs i << 8 | j) in two pieces (the first 64 KB in a gap
# left by a deleted file), and runs HDDTEST.PRG in Hatari with EmuTOS (its own ACSI / IDE drivers) once with the
# image on ACSI 0 and once as the IDE master (the image is C:, the program on Hatari's GEMDOS drive D:); then on
# ACSI again with 2 KB logical sectors (a big TOS partition's).  Prints the HDDTEST.TXT the program wrote next to the
# data file, and "hddtest: ok" when every run opened the file as two extents and read every request without a bad
# sector.
#   tools/hddtest.sh            TOS=<image> for another TOS (it needs a hard disk driver; default EmuTOS)
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/etos512de.img}
PY=$ROOT/venv/bin/python; [ -x "$PY" ] || PY=python3
VASM=$("$PY" -c "import sys; sys.path.insert(0, '$ROOT/engine'); import paths; print(paths.VASM)")
W=$(mktemp -d)      # (KEEP=1: kept, with Hatari's logs)
"$VASM" -Ftos -quiet -nowarn=2047 -I "$ROOT/engine/rt" -o "$W/HDDTEST.PRG" "$ROOT/tools/hddtest.s"

IMG=$W/disk.img
"$PY" - "$IMG" "$W" <<'EOF'
import struct, sys
img, w = sys.argv[1], sys.argv[2]
sectors, start = 32 * 2048, 2048
mbr = bytearray(512)
mbr[446:462] = struct.pack("<B3sB3sII", 0, b"\0\0\0", 0x06, b"\0\0\0", start, sectors - start)
mbr[510:512] = b"\x55\xaa"
with open(img, "wb") as f:
    f.write(mbr)
    f.truncate(sectors * 512)
with open(w + "/HDDTEST.DAT", "wb") as f:
    for i in range(1280):
        f.write(b"".join(struct.pack(">I", i << 8 | j) for j in range(128)))
open(w + "/GAP.DAT", "wb").write(bytes(64 * 1024))
open(w + "/KEEP.DAT", "wb").write(bytes(32 * 1024))
EOF
P="$IMG@@1M"
mkdir -p "$W/prg" && mv "$W/HDDTEST.PRG" "$W/prg/"
cp "$IMG" "$W/empty.img"

format() {   # logical sector size code (mformat -S: 2 = 512 bytes, 4 = 2 KB): FAT16, the file in two pieces
  cp "$W/empty.img" "$IMG"
  local SIZE=$((128 << $1))
  mformat -i "$P" -S "$1" -c $((2048 / SIZE > 1 ? 1 : 2)) -T $((31 * 1024 * 1024 / SIZE)) -h 16 -s 63 -H 2048 ::
  mcopy -i "$P" "$W/GAP.DAT" ::GAP.DAT
  mcopy -i "$P" "$W/KEEP.DAT" ::KEEP.DAT
  mdel -i "$P" ::GAP.DAT
  mcopy -i "$P" "$W/HDDTEST.DAT" ::HDDTEST.DAT
  cp "$IMG" "$W/clean.img"
}

run() {   # name, hatari disk arguments...
  local NAME=$1; shift
  cp "$W/clean.img" "$IMG"
  "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --sound off --confirm-quit off \
    --harddrive "$W/prg" --gemdos-drive D --auto 'D:\HDDTEST.PRG' --log-file "$W/hatari_$NAME.log" "$@" & H=$!
  for i in $(seq 90); do sleep 1; mtype -i "$P" ::HDDTEST.TXT 2>/dev/null | grep -q done && break; done
  kill $H 2>/dev/null || true; wait $H 2>/dev/null || true
  echo "--- $NAME"
  mtype -i "$P" ::HDDTEST.TXT 2>/dev/null | tr -d '\r' > "$W/$NAME.txt" || true
  cat "$W/$NAME.txt"
  grep -q "^open 00000000 .* extents 00000002 sectors 00000500" "$W/$NAME.txt" &&
    [ "$(grep -c ": 00000000 bad 00000000 " "$W/$NAME.txt")" = 10 ] && grep -q "^done" "$W/$NAME.txt" ||
    FAIL="$FAIL $NAME"
}
FAIL=
format 2
run acsi --acsi 0="$IMG"
run ide --ide-master "$IMG"
format 4
run acsi-2k --acsi 0="$IMG"
[ -n "$KEEP" ] && echo "kept: $W" || rm -rf "$W"
[ -z "$FAIL" ] && echo "hddtest: ok" || { echo "hddtest: FAIL ($FAIL )"; exit 1; }
