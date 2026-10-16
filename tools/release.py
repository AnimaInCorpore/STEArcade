#!/usr/bin/env python3
"""Pack a release: the eight ports as self-contained TOS programs (the arcade's code and graphics are built into each
.PRG, nothing is loaded at run time) and a README.TXT.  The ROM sets themselves are not part of it (nor of git).

    python tools/release.py <version> [--no-build]      -> release/STEArcade-<version>/ and release/STEArcade-<version>.zip

Each port is built with its default settings (no DEBUG, no AUTOPLAY, no SIM: python port.py build <game>).  A .PRG
must be a TOS program and must not carry a debug build's file names (COUNTERS.BIN, DEBUG.BIN, ...).
"""
import argparse
import hashlib
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import port                                         # noqa: E402  (port.GAMES: the ports and their programs)
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() else sys.executable

# game, program, title, state, buttons (keyboard Space/Control, Alternate; joystick fire; pad A, B, C)
GAMES = [
    ("dkong", "DKONG.PRG", "Donkey Kong (Nintendo 1981)",
     "full speed (50 frames a second), sound (the 8035 board as DMA sound, walk/jump/stomp on the YM)",
     "jump: Space, Control, Alternate, joystick fire, pad A/B/C.  One player at a time: both joysticks and both\n"
     "  pads move Mario.  One coin slot (5, Option)."),
    ("galaga", "GALAGA.PRG", "Galaga (Namco 1981)",
     "a game frame per VBL; 33 frames a second drawn on average, 17-21 with the full formation; sound on the YM (square waves)",
     "fire: Space, Control, Alternate, joystick fire, pad A/B/C; left and right only.  Players take turns: both\n"
     "  joysticks and both pads move the fighter.  One coin key (5, Option)."),
    ("bublbobl", "BUBBLE.PRG", "Bubble Bobble (Taito 1986)",
     "playable, but slow: about 45% of the arcade's speed and 12 pictures a second in play (Hatari\n"
     "  measurements); exact logic and picture; music and effects on the YM",
     "jump: Space, Control, joystick fire, pad A.  bubble: Alternate, joystick up, pad B, pad up."),
    ("1942", "1942.PRG", "1942 (Capcom 1984)",
     "the arcade's speed (60 ticks a second), 34-43 frames a second; music and effects on the YM (three of the six channels)",
     "fire: Space, Control, joystick fire, pad A.  loop: Alternate, pad B."),
    ("1943", "1943.PRG", "1943: The Battle of Midway (Capcom 1987)",
     "86% of the arcade's speed, 8 frames a second; music and effects on the YM",
     "fire: Space, Control, joystick fire, pad A.  button 2: Alternate, pad B."),
    ("blktiger", "BLKTIGER.PRG", "Black Tiger (Capcom 1987)",
     "92% of the arcade's speed, 26 frames a second; music and effects on the YM",
     "fire: Space, Control, joystick fire, pad A.  jump: Alternate, pad B."),
    ("commando", "COMMANDO.PRG", "Commando (Capcom 1985)",
     "playable, 55 ticks and 25-27 frames a second, 16 colours; the sound effects and the music on the YM",
     "fire: Space, Control, joystick fire, pad A.  grenade: Alternate, pad B."),
    ("gunsmoke", "GUNSMOKE.PRG", "Gun.Smoke (Capcom 1985)",
     "83% of the arcade's speed, 23 frames a second, 16 colours; music and effects on the YM",
     "shoot left / straight / right: Control / Space / Alternate, or Z / X / C; pad A / B / C.\n"
     "  The joystick's fire shoots straight."),
    ("rtype", "RTYPE.PRG", "R-Type (Irem 1987)",
     "playable, but slow: about 30% of the arcade's speed and 6 pictures a second in play (Hatari); exact logic,\n"
     "  the centred 320 of the 384 pixels; no sound yet",
     "fire (hold to charge): Space, Control, joystick fire, pad A.  the Force: Alternate, pad B."),
    ("kungfum", "KUNGFUM.PRG", "Kung-Fu Master (Irem 1984)",
     "92% of the arcade's speed, 20-34 pictures a second in play (Hatari); exact logic, all 256 x 256 pixels;\n"
     "  the sound board's driver translated: music and effects on the YM (three of the six AY channels), the voices\n"
     "  on the DMA sound",
     "punch: Space, Control, Z, joystick fire, pad A.  kick: Alternate, X, pad B.  up jumps, down crouches."),
    ("trojan", "TROJAN.PRG", "Trojan (Capcom 1986)",
     "90% of the arcade's speed, 10-18 pictures a second (Hatari); exact logic, all 256 x 240 pixels; music and\n"
     "  effects on the YM, no ADPCM voices",
     "attack: Space, Control, joystick fire, pad A.  jump: Alternate, pad B."),
    ("ddragon", "DDRAGON.PRG", "Double Dragon (Technos 1987)",
     "playable, but slow: about 35% of the arcade's speed and 4 pictures a second in play (Hatari); exact logic,\n"
     "  all 256 x 240 pixels in 16 colours; music and effects on the YM, the voices and hits on the DMA sound",
     "punch: Space, Z, joystick fire, pad A.  kick: Alternate, X, pad B.  jump: Control, C, pad C."),
]
assert [g[0] for g in GAMES] == list(port.GAMES) and all(g[1] == port.GAMES[g[0]] for g in GAMES), \
    "tools/release.py: GAMES must list port.GAMES (same order, same programs)"
# The memory a program asks TOS for (text + data + BSS + the 256-byte basepage) stays well under what a 4 MB machine
# has free: TOS 2.06 alone leaves 4,061,212 bytes (Hatari), a tester's Mega STE with a hard disk driver and
# accessories 3,831,554 ("not enough memory" from 1942, 1943, Black Tiger, Bubble Bobble and Commando at 3.93-4.05 MB).
MAX_LOAD = 3700000
OVER_LOAD = {"RTYPE.PRG"}   # (packed with a warning: R-Type's shrinking was deferred on 2026-10-15; it needs 3,846,514)
DEBUG_NAMES = (b"COUNTERS.BIN", b"DEBUG.BIN", b"LATEPC.BIN", b"RATE.BIN", b"TIMES.BIN", b"DUMP.BIN")

README = """STE Arcade {version}
{underline}

Z80 arcade games on the Atari STE: each arcade program is statically translated to 68000 code (and checked against
a reference emulator in lock-step), the picture is drawn with the Blitter.  Source and documentation:
https://github.com/AnimaInCorpore/STEArcade  (commit {commit})

Requirements: an Atari STE (or Mega STE) with 4 MB of RAM, a colour monitor or TV (50 Hz).  Start the programs from
the desktop (a hard disk or a GEMDOS drive: they are 1-3 MB each).  Every program is self-contained: the arcade's
code and graphics are part of it, nothing else is needed.  Each needs at most 3.7 MB of free memory (R-Type 3.85 MB);
if TOS says there is not enough, start without accessories and AUTO folder programs.

Controls (all games)
--------------------

Keyboard:  cursor keys  move           1 / 2  start 1 / 2 players     5 / 6  coin 1 / 2      Esc  quit to the desktop
           Space, Control, Alternate: the buttons (see the games)
Joysticks: port 1 (joystick port) player 1, port 0 (mouse port) player 2; fire = button 1
Pads:      Jaguar pads / PowerPads in the STE's enhanced joystick ports: pad A player 1, pad B player 2
           D-pad move, A / B / C the buttons (see the games), Option coin (pad A coin 1, pad B coin 2),
           Pause start (pad A start 1, pad B start 2), keypad 1 / 2 start, 5 / 6 coin, * and # together quit

Tap the coin key: like the arcade's coin mechanism, a game may ignore a coin that is held down (1942 does after
about half a second).

Games
-----
{games}
Notes
-----

The arcade's DIP switches are fixed in each program (upright cabinet).  The programs are built from the original
ROM sets; no separate ROM files are needed.

Files (SHA-256)
---------------
{sums}"""


def game_text():
    out = []
    for game, prg, title, state, buttons in GAMES:
        out.append("%s   %s\n  %s.\n  %s\n" % (prg, title, state[0].upper() + state[1:], buttons))
    return "\n".join(out)


def check(prg):
    data = prg.read_bytes()
    if data[:2] != b"\x60\x1a":
        sys.exit("%s: not a TOS program" % prg)
    found = [n.decode() for n in DEBUG_NAMES if n in data]
    if found:
        sys.exit("%s: a debug build (%s)" % (prg, ", ".join(found)))
    text, dat, bss = struct.unpack(">III", data[2:14])
    if text + dat + bss + 256 > MAX_LOAD:
        if prg.name not in OVER_LOAD:
            sys.exit("%s: needs %d bytes, more than %d (MAX_LOAD)" % (prg, text + dat + bss + 256, MAX_LOAD))
        print("warning: %s needs %d bytes, more than %d (MAX_LOAD; OVER_LOAD lets it pass)"
              % (prg, text + dat + bss + 256, MAX_LOAD))
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--no-build", action="store_true", help="pack the programs in run/ as they are")
    a = ap.parse_args()

    name = "STEArcade-" + a.version
    out = ROOT / "release" / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                           text=True).stdout.strip()
    if dirty:
        commit += " + local changes"

    sums = []
    for game, prg, *_ in GAMES:
        if not a.no_build:
            r = subprocess.run([PY, str(ROOT / "port.py"), "build", game], cwd=ROOT, capture_output=True, text=True)
            if r.returncode:
                sys.stdout.write(r.stdout + r.stderr)
                sys.exit("build of %s failed" % game)
        data = check(ROOT / "run" / game / prg)
        (out / prg).write_bytes(data)
        sums.append("%s  %s" % (hashlib.sha256(data).hexdigest(), prg))
        print("%-13s %8d bytes" % (prg, len(data)))

    text = README.format(version=a.version, underline="=" * (len("STE Arcade ") + len(a.version)), commit=commit,
                         games=game_text(), sums="\n".join(sums) + "\n")
    (out / "README.TXT").write_bytes(text.replace("\n", "\r\n").encode("ascii"))

    # The files in the archive carry the commit's date (reproducible, and the date the programs were built from)
    stamp = int(subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip() or "0")
    date_time = time.localtime(stamp)[:6] if stamp else (2026, 1, 1, 0, 0, 0)
    archive = ROOT / "release" / (name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in ["README.TXT"] + [g[1] for g in GAMES]:
            info = zipfile.ZipInfo("%s/%s" % (name, f), date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (out / f).read_bytes(), compresslevel=9)
    print("%s: %d bytes (%s)" % (archive.relative_to(ROOT), archive.stat().st_size, commit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
