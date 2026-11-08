#!/usr/bin/env python3
"""Pack a release: the registered ports in port.GAMES as self-contained TOS programs and a README.TXT.
The arcade's code and graphics are built into each .PRG; nothing is loaded at run time.
The ROM sets themselves are not part of it (nor of git).

    python tools/release.py <version> [--no-build]      -> release/STEArcade-<version>/ and release/STEArcade-<version>.zip

DISKS/ gets a bootable floppy image (.ST, 720 or 800 KB: tools/stdisk.py) for every port whose program, packed
with LZ4 into a self-unpacking program (tools/lz4prg.py), fits on one; it starts from the disk's AUTO folder.

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
sys.path.insert(0, str(ROOT / "tools"))
import lz4prg                                       # noqa: E402
import stdisk                                       # noqa: E402
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() else sys.executable

# game, program, title, state, buttons (keyboard Space/Control, Alternate; joystick fire; pad A, B, C)
GAMES = [
    ("dkong", "DKONG.PRG", "Donkey Kong (Nintendo 1981)",
     "full speed (50 frames a second), sound (the 8035 board as DMA sound, walk/jump/stomp on the YM)",
     "jump: Space, Control, Alternate, joystick fire, pad A/B/C.  One player at a time: both joysticks and both\n"
     "  pads move Mario.  One coin slot (5, Option)."),
    ("1942", "1942.PRG", "1942 (Capcom 1984)",
     "the arcade's speed (60 ticks a second), 34-43 frames a second; music and effects on the YM (three of the six channels)",
     "fire: Space, Control, joystick fire, pad A.  loop: Alternate, pad B."),
    ("xevious", "XEVIOUS.PRG", "Super Xevious (Namco 1984)",
     "logic exact against the reference (lock-step); the picture is drawn by the CPU, 5.4 pictures a second; sound: the WSG voices on the YM (no explosions); 16 colours fitted",
     "fire: Space, Control, joystick fire, pad A/C.  bomb: Alternate, pad B.  8 directions.  One coin key (5, Option)."),
    ("galaga", "GALAGA.PRG", "Galaga (Namco 1981)",
     "a game frame per VBL; the real 51XX MCU's program (translated), the 54XX's explosion simulated; 31 frames a second\n"
     "  drawn on average in the attract mode (Hatari); sound on the YM (square waves)",
     "fire: Space, Control, Alternate, joystick fire, pad A/B/C; left and right only.  Players take turns: both\n"
     "  joysticks and both pads move the fighter.  One coin key (5, Option)."),
    ("blktiger", "BLKTIGER.PRG", "Black Tiger (Capcom 1987)",
     "92% of the arcade's speed, 26 frames a second; music and effects on the YM",
     "fire: Space, Control, joystick fire, pad A.  jump: Alternate, pad B."),
    ("commando", "COMMANDO.PRG", "Commando (Capcom 1985)",
     "the arcade's full speed in play (60 ticks a second), 26.5 pictures a second on average in play (Hatari),\n"
     "  16 colours; the sound effects and the music on the YM",
     "fire: Space, Control, joystick fire, pad A.  grenade: Alternate, pad B."),
    ("gunsmoke", "GUNSMOKE.PRG", "Gun.Smoke (Capcom 1985)",
     "83% of the arcade's speed, 23 frames a second, 16 colours; music and effects on the YM",
     "shoot left / straight / right: Control / Space / Alternate, or Z / X / C; pad A / B / C.\n"
     "  The joystick's fire shoots straight."),
    ("gauntlet", "GAUNTLET.PRG", "Gauntlet (Atari Games 1985)",
     "the arcade's own 68010 program, natively, at the arcade's 60 frames a second (six for every five VBLs);\n"
     "  16 pictures a second in the attract mode, 33 in light play (Hatari); 320 of the 336 pixels (the side panel\n"
     "  moved left), 16 colours; music, effects and speech.\n"
     "  Needs the whole 4 MB: Esc resets the STE",
     "fire: Space, Control, Z, joystick fire, pad A.  magic (and the start): Alternate, X, pad B / C.  coins 1-4:\n"
     "  5-8 (players 1-4; pads: Option).  Joystick 1 / pad A player 1, joystick 0 / pad B player 2."),
    ("kungfum", "KUNGFUM.PRG", "Kung-Fu Master (Irem 1984)",
     "92% of the arcade's speed, 20-34 pictures a second in play (Hatari); exact logic, all 256 x 256 pixels;\n"
     "  the sound board's driver translated: music and effects on the YM (three of the six AY channels), the voices\n"
     "  on the DMA sound",
     "punch: Space, Control, Z, joystick fire, pad A.  kick: Alternate, X, pad B.  up jumps, down crouches."),
    ("trojan", "TROJAN.PRG", "Trojan (Capcom 1986)",
     "90% of the arcade's speed, 10-18 pictures a second (Hatari); exact logic, all 256 x 240 pixels; music and\n"
     "  effects on the YM, no ADPCM voices",
     "attack: Space, Control, joystick fire, pad A.  jump: Alternate, pad B."),
    ("gyruss", "GYRUSS.PRG", "Gyruss (Konami 1983)",
     "playable, but slower than the arcade: about half its speed and 7-12 pictures a second in play (Hatari);\n"
     "  exact logic of both CPUs, the turned 224 x 256 picture; music and effects on the YM (three of the fifteen\n"
     "  AY channels), the sampled effects on the DMA sound",
     "fire: Space, Control, Z, joystick fire, pad A.  The joystick moves the ship around the circle."),
    ("1943", "1943.PRG", "1943: The Battle of Midway (Capcom 1987)",
     "86% of the arcade's speed, 8 frames a second; music and effects on the YM",
     "fire: Space, Control, joystick fire, pad A.  button 2: Alternate, pad B."),
    ("bublbobl", "BUBBLE.PRG", "Bubble Bobble (Taito 1986)",
     "playable, but slow: about 45% of the arcade's speed and 12 pictures a second in play (Hatari\n"
     "  measurements); exact logic and picture; music and effects on the YM",
     "jump: Space, Control, joystick fire, pad A.  bubble: Alternate, joystick up, pad B, pad up."),
    ("ddragon", "DDRAGON.PRG", "Double Dragon (Technos 1987)",
     "playable, but slow: about 38% of the arcade's speed and 4 pictures a second in play (Hatari); exact logic,\n"
     "  all 256 x 240 pixels in 16 colours; music and effects on the YM, the voices and hits on the DMA sound",
     "punch: Space, Z, joystick fire, pad A.  kick: Alternate, X, pad B.  jump: Control, C, pad C."),
    ("timeplt", "TIMEPLT.PRG", "Time Pilot (Konami 1982)",
     "work in progress: the arcade's full speed, 24-33 pictures a second in play (Hatari); exact logic, the turned\n"
     "  224 x 256 picture in 16 fitted colours; no sound yet",
     "fire: Space, Control, Z, joystick fire, pad A.  The joystick turns the plane."),
    ("dkongjr", "DKONGJR.PRG", "Donkey Kong Junior (Nintendo 1982)",
     "full speed (50 frames a second), exact logic and picture; sound (the 8035 board as DMA sound, walk/jump/climb/\n"
     "  fall on the YM); 22 colours fitted into 16",
     "jump: Space, Control, Alternate, joystick fire, pad A/B/C.  One player at a time: both joysticks and both\n"
     "  pads move Junior.  One coin slot (5, Option)."),
    ("pacman", "PACMAN.PRG", "Pac-Man (Namco / Midway 1980)",
     "full speed (60 arcade frames and 50 pictures a second in play, Hatari); exact logic and picture, 274 of the\n"
     "  288 lines (the never or hardly drawn ones left out); the WSG's voices on the YM",
     "the arrows, the joystick or a pad move Pac-Man; no buttons.  One player at a time: both joysticks and both\n"
     "  pads move him."),
    ("trackfld", "TRACKFLD.PRG", "Track & Field (Konami 1983)",
     "work in progress: the arcade's full speed, 20-50 pictures a second (Hatari); exact logic, all 256 x 224\n"
     "  pixels in 16 fitted colours; the sound board's Z80 translated, its SN76489A on the YM, the speech and\n"
     "  the tunes on the DMA sound",
     "run: Left / Right, Z / C, joystick left / right, pad A / C (in turn: the faster, the better).  action\n"
     "  (jump, throw, the angle): Up, Space, Control, X, joystick up / fire, pad B."),
    ("rocnrope", "ROCNROPE.PRG", "Roc'n Rope (Konami 1983)",
     "work in progress: the arcade's logic exact, the 224 x 256 picture in 16 colours; no sound yet",
     "left / right / up / down: the arrows, joystick, pad.  Button 1 (Space, Z, fire, pad A / C), button 2\n"
     "  (Control, X, pad B).  1/2 start, 5/6 coins."),
    ("hyperspt", "HYPERSPT.PRG", "Hyper Sports (Konami 1984)",
     "work in progress: 83% of the arcade's speed, 5-50 pictures a second (Hatari); exact logic, all 256 x 224\n"
     "  pixels in 16 fitted colours; the sound board's Z80 translated, its SN76489A on the YM, the speech and\n"
     "  the tunes on the DMA sound",
     "run / left button: Left, Z, joystick left, pad A.  right button: Right, C, joystick right, pad C.  action:\n"
     "  Up, Space, Control, X, joystick up / fire, pad B."),
    ("pooyan", "POOYAN.PRG", "Pooyan (Konami 1982)",
     "the arcade's full speed, 40-50 pictures a second in play (Hatari); exact logic and picture, the turned\n"
     "  224 x 256 picture; the sound board's Z80 translated, its two AYs on the YM",
     "fire: Space, Control, Z, joystick fire, pad A/B/C.  Up / down move the basket.  coins: 5 / 6.\n"
     "  Joystick 1 / pad A player 1, joystick 0 / pad B player 2."),
    ("mrdo", "MRDO.PRG", "Mr. Do! (Universal 1982)",
     "the arcade's full speed in most of play, 44-50 pictures a second (Hatari); exact logic and picture, the\n"
     "  turned 192 x 240 picture in 15 fitted colours; the two SN76489s' tones on the YM",
     "fire (the power ball): Space, Control, Z, joystick fire, pad A/B/C.  The players take turns: both joysticks\n"
     "  and both pads move Mr. Do!.  coins: 5 / 6."),
    ("mpatrol", "MPATROL.PRG", "Moon Patrol (Irem 1982)",
     "about 95% of the arcade's speed, 14-30 pictures a second (Hatari); exact logic and picture (frames with more\n"
     "  than 16 colours on the playfield borrow the nearest colour); music and effects on the YM, the voices on the\n"
     "  DMA sound",
     "fire: Space, Control, Z, joystick fire, pad A.  jump: Up, Alternate, X, pad B.  Left / right: slower / faster.\n"
     "  coins: 5 / 6."),
    ("mario", "MARIO.PRG", "Mario Bros. (Nintendo 1983)",
     "work in progress: exact logic (lock-step) and picture (256 x 224 in 16 fitted colours), about 98% of the arcade's speed\n"
     "  and 30 pictures a second (Hatari); the music and effects as recordings of MAME on the DMA sound (not listened to)",
     "move: the arrows, joystick, pad D-pad.  jump: Space, Control, joystick fire, pad A / C.  coins: 5 / 6, start: 1 / 2."),
    ("mikie", "MIKIE.PRG", "Mikie (Konami 1984)",
     "work in progress: exact logic (lock-step) and picture (224 x 256, turned as the arcade's monitor), 16 fitted\n"
     "  colours; the two SN76489s' voices on the YM (three of the eight at a time); speed measured in Hatari (see the\n"
     "  game's README)",
     "move: the arrows, the joystick or a pad; kick / hit: Space, Control, Z, joystick fire, pad A / C;\n"
     "  second button: Alternate, X, pad B.  Coins 5 / 6, start 1 / 2."),
    ("yiear", "YIEAR.PRG", "Yie Ar Kung-Fu (Konami 1985)",
     "work in progress: exact logic and picture (256 x 224 in 16 fitted colours), 96% speed and 37 pictures a second (Hatari), with sound",
     "move: the arrows, joystick, pad A.  kick: Z, Space, Control, joystick fire, pad A.  punch: X, Alternate, pad B.\n"
     "  coins: 5 / 6, start 1 / 2."),
    ("sbasketb", "SBASKETB.PRG", "Super Basketball (Konami 1984)",
     "work in progress: about 83-90% of the arcade's speed, 19-31 pictures a second (Hatari); exact logic and picture,\n"
     "  the turned 224 x 256 picture in 16 fitted colours; the sound board's output recorded in MAME, on the DMA sound",
     "move: arrows, joystick, pad D-pad.  shoot (button 1): Space, Control, Z, joystick fire, pad A.  pass (button 2):\n"
     "  X, pad B.  button 3: C, pad C.  Joystick 1 / pad A player 1, joystick 0 / pad B player 2."),
    ("jailbrek", "JAILBREK.PRG", "Jail Break (Konami 1986)",
     "work in progress: exact logic, the 240 x 224 picture in 16 fitted colours, sound (see the game's README)",
     "move: the arrows, joystick, pad D-pad.  fire: Space, Control, joystick fire, pad A / C.  select weapon: X,\n"
     "  Alternate, pad B.  Player 2: joystick 0, pad B, W A S D Q E.  coins: 5 / 6, start: 1 / 2."),
    ("junofrst", "JUNOFRST.PRG", "Juno First (Konami 1983)",
     "experimental: about 56% of the arcade's speed, 9-10 pictures a second (Hatari); exact logic and picture (\n"
     "  224 x 256, the screen turned as the arcade's); sound (YM + DMA effects), not compared with the arcade's audio",
     "Left / Right / Up / Down, the joystick or a pad move the ship; Space, Control, Z or the stick's fire shoot\n"
     "  (X: the second button).  5 / 6 coin, 1 / 2 start."),
]
# registered ports left out of the release: R-Type needs more than 4 MB while it is developed (all eight stages'
# sprites pre-coloured); the user took it out on 2026-11-01 until it fits again
NOT_RELEASED = {"rtype", "digdug"}      # Dig Dug: loads 3.66 MB since 2026-11-08 (one dispatch table for the three CPUs), runs in Hatari with 4 MB; left out until the user decides (no natural playthrough, 18-33 pictures a second)
assert [g[0] for g in GAMES] == [g for g in port.GAMES if g not in NOT_RELEASED] and \
    all(g[1] == port.GAMES[g[0]] for g in GAMES), \
    "tools/release.py: GAMES must list port.GAMES but NOT_RELEASED (same order, same programs)"
# The memory a program asks TOS for (text + data + BSS + the 256-byte basepage) stays well under what a 4 MB machine
# has free: TOS 2.06 alone leaves 4,061,212 bytes (Hatari), a tester's Mega STE with a hard disk driver and
# accessories 3,831,554 ("not enough memory" from 1942, 1943, Black Tiger, Bubble Bobble and Commando at 3.93-4.05 MB).
MAX_LOAD = 3700000
OVER_LOAD = set()   # (programs packed with a warning although over MAX_LOAD; R-Type was one until 0.6)
DEBUG_NAMES = (b"COUNTERS.BIN", b"DEBUG.BIN", b"LATEPC.BIN", b"RATE.BIN", b"TIMES.BIN", b"DUMP.BIN")

README = """STE Arcade {version}
{underline}

Arcade games on the Atari STE (Z80, 6809-family and NEC V30): each arcade program is statically translated to
68000 code (and checked against a reference emulator in lock-step), the picture is drawn with the Blitter.
Source and documentation:
https://github.com/AnimaInCorpore/STEArcade  (commit {commit})

Requirements: an Atari STE (or Mega STE) with 4 MB of RAM, a colour monitor or TV (50 Hz).  Start the programs from
the desktop from a hard disk or a GEMDOS drive. Every program is self-contained: the arcade's
code and graphics are part of it, nothing else is needed.  Each needs at most 3.7 MB of free memory;
if TOS says there is not enough, start without accessories and AUTO folder programs.

Floppy disks: DISKS holds a bootable disk image (.ST) for each game that fits on a floppy: write it to a disk or
put it on a floppy emulator (Gotek, GoEX, HxC ...) and boot the STE from it with no hard disk.  The game starts
from the disk's AUTO folder, unpacks itself (a bar shows the progress: 4-13 seconds) and runs.  720 KB images are
80 tracks, 9 sectors; 800 KB images 80 tracks, 10 sectors.  Too large for a disk: {nodisk}.

Verification status
-------------------

No port is certified Complete by this release.  1942 and Donkey Kong passed assisted ending/loop replay
regressions in native Hatari; natural complete playability, ordinary controls and sound remain unverified
by those tests.  1942: 51,176 inputs / 426 RAM checkpoints; Donkey Kong: 38,200 / 318.
Galaga runs the real 51XX MCU program since 2026-10-21 (the 54XX's explosions are still
simulated); its full-game verification is pending.  Time Pilot has no sound yet.  Donkey Kong Junior, Pac-Man,
Pooyan, Mr. Do!, Moon Patrol, Track & Field and Hyper Sports are new: their logic and picture are checked against
the reference, their full-game verification is pending.  R-Type is not part of this release: while it is developed it needs more than 4 MB of
RAM.  See the source README for the five-color status
legend and each port's limitations.  The performance descriptions below are prior per-port measurements,
not measurements of this release or proof of a full natural playthrough.

Controls (all games)
-------------------

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

    # The files in the archive carry the commit's date (reproducible, and the date the programs were built from)
    stamp = int(subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip() or "0")
    date_time = time.localtime(stamp)[:6] if stamp else (2026, 1, 1, 0, 0, 0)

    (out / "DISKS").mkdir()
    sums, disks, nodisk = [], [], []
    for game, prg, *_ in GAMES:
        if not a.no_build:
            r = subprocess.run([PY, str(ROOT / "port.py"), "build", game], cwd=ROOT, capture_output=True, text=True)
            if r.returncode:
                sys.stdout.write(r.stdout + r.stderr)
                sys.exit("build of %s failed" % game)
        data = check(ROOT / "run" / game / prg)
        (out / prg).write_bytes(data)
        sums.append("%s  %s" % (hashlib.sha256(data).hexdigest(), prg))
        packed, info = lz4prg.pack(data)
        img = stdisk.disk(prg, packed, date_time)
        if img is None:
            nodisk.append(prg)
            note = "packed %d: no disk" % len(packed)
        else:
            st = "DISKS/" + prg.replace(".PRG", ".ST")
            (out / st).write_bytes(img)
            disks.append(st)
            sums.append("%s  %s" % (hashlib.sha256(img).hexdigest(), st))
            note = "packed %d: %s (%d KB)" % (len(packed), st, len(img) // 1024)
        print("%-13s %8d bytes  %s" % (prg, len(data), note))

    text = README.format(version=a.version, underline="=" * (len("STE Arcade ") + len(a.version)), commit=commit,
                         games=game_text(), sums="\n".join(sums) + "\n",
                         nodisk=", ".join(p[:-4] for p in nodisk) or "none")
    (out / "README.TXT").write_bytes(text.replace("\n", "\r\n").encode("ascii"))

    archive = ROOT / "release" / (name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in ["README.TXT"] + [g[1] for g in GAMES] + disks:
            info = zipfile.ZipInfo("%s/%s" % (name, f), date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (out / f).read_bytes(), compresslevel=9)
    print("%s: %d bytes (%s)" % (archive.relative_to(ROOT), archive.stat().st_size, commit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
