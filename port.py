#!/usr/bin/env python3
"""One entry point for the ports.

    port.py list                           the games and their programs
    port.py prepare <game>                 verify the ROM archive, unpack it to assets/roms/extracted/<game>/ (build, cover,
                                           test and mame do it first when that folder is missing)
    port.py cover  <game> [seeds ...]        coverage runs the translator is seeded from (parallel; ~15 min for dkong)
    port.py build  <game> [build.py args]    translate + assemble + link -> run/<game>/   (--sim: the simulator build)
    port.py test   <game> [frames]           the tests that compare the build with the reference machine
    port.py test   engine                    the engine's own tests (Blitter sprite code, the pad reader, the IKBD stream, the 6809)
    port.py run    <game> [item@s ...]       Hatari (tools/hatari.sh): screenshots, key presses, memory dumps
    port.py mame   <game> [frames ...]       reference renderer against MAME's own picture (needs `mame`)
    port.py ppo <game|all> <train|record|verify|test> [args]  PPO exploration (optional build/ppo-venv)
    port.py release <version> [--no-build]  every port built and packed: release/STEArcade-<version>.zip (tools/release.py)

The python is the repository's venv (venv/bin/python) when it exists.  Everything it starts is a plain script in
games/<game>/tools or ref (see games/<game>/README.md); this file only knows the order and the arguments.  GAMES is
the one list of the ports (tools/hatari.sh and tools/release.py read it); every game has tools/build.py,
tools/prepare.py and ref/mame_cmp_<game>.py.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() else sys.executable

# the registered ports, in README order (other entries are work in progress), and their programs (run/<game>/<program>)
GAMES = {"dkong": "DKONG.PRG", "1942": "1942.PRG", "galaga": "GALAGA.PRG", "blktiger": "BLKTIGER.PRG",
         "commando": "COMMANDO.PRG", "gunsmoke": "GUNSMOKE.PRG", "gauntlet": "GAUNTLET.PRG", "kungfum": "KUNGFUM.PRG",
         "trojan": "TROJAN.PRG", "gyruss": "GYRUSS.PRG", "1943": "1943.PRG", "bublbobl": "BUBBLE.PRG",
         "rtype": "RTYPE.PRG", "ddragon": "DDRAGON.PRG", "timeplt": "TIMEPLT.PRG",
         "dkongjr": "DKONGJR.PRG", "pacman": "PACMAN.PRG", "trackfld": "TRACKFLD.PRG",
         "hyperspt": "HYPERSPT.PRG", "pooyan": "POOYAN.PRG", "mrdo": "MRDO.PRG",
         "mpatrol": "MPATROL.PRG", "mario": "MARIO.PRG", "sbasketb": "SBASKETB.PRG"}
EXTRACTED = ROOT / "assets" / "roms" / "extracted"

# coverage: (script, seeds, frames) groups; the pickles land in build/<game>/
COVER = {
    "mario": [("ref/cover.py", list(range(1, 13)), 20000)],       # 1-3 play, 4-6 + 11-12 free play and lives, 7 two players, 8-9 DIPs, 10 service mode
    "mpatrol": [("ref/cover.py", list(range(1, 10)), 20000)],    # 1-2 play (2: two players), 3-6 courses by cheats,
                                                                # 7 sector selection, 8 stop mode, 9 DIPs
    "pooyan": [("ref/cover.py", list(range(1, 14)), 20000),       # 1-3 play, 4-8 lives, 9 high score, 10-11 two players,
                                                                # 12 DIPs, 13 no coin: the attract cycle
               ("ref/cover_sound.py", [0, 1, 2, 3], 20000)],     # the sound Z80: 0 the game's commands, 1-3 random
    "mrdo": [("ref/cover.py", list(range(1, 13)), 20000),        # 1-3 play, 4-6 lives (6 fire held), 7 two players,
                                                                # 8-9 DIPs, 10 rack test, 11-12 later scenes
             ("ref/pens.py", [7, 10, 11, 12], 8000)],            # the pens' counts for the palette fit (tools/assets.py)
    "pacman": [("ref/cover.py", list(range(1, 13)), 20000)],    # 1-3 play, 4-6 lives + levels, 7 two players, 8-9 DIPs,
                                                                # 10 rack test, 11-12 levels 20+ / 250+ (split screen)
    "dkongjr": [("ref/cover.py", [1, 2, 3, 11, 12, 13, 14, 15, 16, 21, 22, 23], 40000),   # play, stages by $6227, name entry
                ("ref/cover.py", [4, 5], 30000)],                  # no coin: the whole attract sequence (the title)
    "hyperspt": [("ref/cover.py", list(range(1, 13)), 20000)],    # 1-3 play, 4-10 start event + first try, 11 two players, 12 DIPs
    "trackfld": [("ref/cover.py", list(range(1, 13)), 20000)],    # 1-3 play, 4-9 start event + qualify + lives, 10-11 two players, 12 DIPs
    "sbasketb": [("ref/cover.py", list(range(1, 22)), 20000)],   # 1-3 play, 4-5 two players, 6-9 DIPs, 10-11 fast input, 12 the service mode, 13-14 late or no coin, 15-20 patterns, 21 the AUTOPLAY script
    "timeplt": [("ref/cover.py", list(range(1, 14)), 20000)],     # 1-3 play, 4-8 lives + start stage, 9 invincible, 10-11 two players, 12 DIPs, 13 10+ lives
    "gyruss": [("ref/cover.py", list(range(1, 13)), 20000),        # 1-3 play, 4-9 infinite lives, 10-11 two players, 12 DIPs
               ("ref/cover_sound.py", [0], 20000),                 # the sound Z80: the game's commands (seed 1's play)
               ("ref/cover_sound.py", [1, 2, 3], 30000)],          # random commands
    "gauntlet": [("ref/cover.py", [-1], 420),                   # the BIOS's boot on the reference board (as MAME)
                 ("ref/cover.py", [0, 1, 2, 3, 4, 11, 12, 13, 14, 15], 15000)],   # attract; random play, 1-4 players
    "1943": [("ref/cover.py", list(range(1, 21)), 20000),      # 4-5: attract, the test inputs; 6-20: cheats, one stage each
             ("ref/cover.py", list(range(21, 41)), 60000)],    # 21-40: random play that dies, every start stage
    "commando": [("ref/cover.py", [1, 2, 3], 12000)],
    "gunsmoke": [("ref/cover.py", list(range(1, 15)), 20000)],    # 4-14: cheats, one round each
    "rtype": [("ref/cover.py", [1], 6000), ("ref/cover.py", [4, 5, 6], 12000),   # 1: attract; 4-6: play
              ("ref/cover.py", [8], 20000), ("ref/cover.py", [9], 40000),        # 8-12: Invulnerability
              ("ref/cover.py", [10, 11, 12], 86000),                             # 10-12: all 8 stages (2026-10-31)
              ("ref/cover.py", [10], 52000, [46000]), ("ref/cover.py", [10], 62000, [56000]),   # the Invulnerability
              ("ref/cover.py", [10], 70500, [64500]), ("ref/cover.py", [10], 80000, [74000]),   # switch off from the
              ("ref/cover.py", [11], 70500, [64000]), ("ref/cover.py", [12], 62000, [56000])], # 3rd value: late-stage
                                                                                 # deaths, game over, ranking (2026-11-01)
    "dkong": [("ref/cover.py", [11, 12, 13, 14], 60000), ("ref/cover_stages.py", [21, 22, 23, 24], 40000),
              ("ref/cover_pens.py", [31, 32, 33], 30000)],       # the last one finds the palette pens
    "galaga": [("ref/cover.py", [1, 2, 3], 20000), ("ref/cover.py", [4, 5, 6], 30000),   # 4-6: high scores, the name entry
               ("ref/cover.py", [7], 20000)],                                          # 7: the real 51XX
    "bublbobl": [("ref/cover.py", [1, 2, 3, 4, 5, 6], 20000)],
    "1942": [("ref/cover.py", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], 60000)],   # 5-8: cheats (later stages), 9-12: two players, 13-16: lives only
    "blktiger": [("ref/cover.py", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], 20000)],   # 4-11: cheats, one stage each
    "kungfum": [("ref/cover.py", list(range(1, 14)), 20000)],     # floors and bosses by MAME's cheat, high score, ending, DIPs
    "trojan": [("ref/cover.py", list(range(0, 52)), 20000)],      # 0 AUTOPLAY, coins/play, levels 1-6 by DIP + cheats
    "ddragon": [("ref/cover.py", [0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 20, 21], 20000),   # attract, play, lives, 2 players
                ("ref/cover.py", [-1, -3], 40000), ("ref/cover.py", [-2], 90000)],     # the recorded plays (missions 2-4)
}
# tests: command lines (relative to games/<game>), {n} = the frames argument
TESTS = {
    "mario": [("tools/prepare.py", [], None),
              ("tools/build.py", ["--sim"], None),
              ("tools/logic_test.py", ["{n}"], 3000),
              ("tools/logic_test.py", ["8000", "--seed", "3", "--quiet"], None),
              ("tools/render_test.py", ["3000", "--seed", "1", "--start", "100", "--every", "3"], None),
              ("tools/render_test.py", ["3000", "--seed", "5", "--start", "100", "--every", "3"], None),   # (5: two players)
              ("tools/sound_test.py", ["3000"], None)],              # the DMA sound driver against the game's commands
    "mpatrol": [("tools/prepare.py", [], None),
                ("tools/build.py", ["--sim"], None),
                ("tools/logic_test.py", ["{n}"], 3000),
                ("tools/logic_test.py", ["6000", "--seed", "3", "--quiet"], None),   # the Beginner course to its end
                ("tools/render_test.py", ["600", "--seed", "1"], None),              # the attract mode
                ("tools/render_test.py", ["4000", "--seed", "3", "--vbl", "0.8"], None),   # play, pictures dropped as the VBL does
                ("tools/sprite_test.py", [], None),          # every x (edges, 16 shifts), flips, holes, guards, 64 KB
                ("tools/sound_test.py", ["3000"], None)],    # the M6803 driver, AYs, YM and DMA voices against sound.py
    "pooyan": [("tools/prepare.py", [], None),
               ("tools/build.py", ["--sim"], None),
               ("tools/logic_test.py", ["{n}"], 3000),
               ("tools/logic_test.py", ["6000", "--seed", "5", "--quiet"], None),    # rounds 2-4
               ("tools/render_test.py", ["3000", "--start", "1000", "--every", "3"], None),
               ("tools/render_test.py", ["3000", "--seed", "10", "--start", "1000", "--every", "5"], None),   # two players
               ("tools/sprite_test.py", [], None),                # edges, 16 shifts, flips, holes, 64 KB crossings
               ("tools/sound_test.py", ["3000", "--tag", "pooyan_sim"], None)],   # the sound driver against sound.py
    "mrdo": [("tools/prepare.py", [], None),
             ("tools/build.py", ["--sim"], None),
             ("tools/logic_test.py", ["{n}"], 3000),
             ("tools/logic_test.py", ["6000", "--seed", "7", "--quiet"], None),    # two players (the maze copies)
             ("tools/render_test.py", ["3000", "--seed", "10", "--every", "4"], None),
             ("tools/render_test.py", ["3000", "--seed", "4", "--start", "1600", "--every", "3"], None),   # play
             ("tools/sprite_test.py", [], None),                  # edges, 16 shifts, flips, holes, 64 KB crossings
             ("tools/sound_test.py", ["3000"], None)],            # the SN76489s' registers and the YM against sound.py
    "pacman": [("tools/prepare.py", [], None),
               ("tools/build.py", ["--sim"], None),
               ("tools/logic_test.py", ["{n}"], 3000),
               ("tools/logic_test.py", ["6000", "--seed", "6", "--quiet"], None),   # levels and intermissions
               ("tools/render_test.py", ["3000", "--seed", "2", "--start", "300", "--every", "3"], None),
               ("tools/render_test.py", ["3000", "--seed", "12", "--start", "300", "--every", "5"], None),   # level 250+
               ("tools/sprite_test.py", [], None),                # edges, 16 shifts, holes, bands, wrap, 64 KB
               ("tools/sound_test.py", ["3000"], None)],          # snd_update against tools/sound.py
    "hyperspt": [("tools/prepare.py", [], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 3000),
                 ("tools/logic_test.py", ["20000", "--seed", "5"], None),   # skeet shooting by MAME's cheats
                 ("tools/logic_test.py", ["8000", "--seed", "9"], None),    # weightlifting
                 ("tools/render_test.py", ["3000", "--seed", "5", "--start", "500", "--every", "3"], None),
                 ("tools/sprite_test.py", [], None),              # edges, 16 shifts, holes, guards, 64 KB crossings
                 ("tools/native_test.py", ["2000"], None)],       # src/natives.s against the 6809 (edge cases too)
    "trackfld": [("tools/prepare.py", [], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 3000),
                 ("tools/logic_test.py", ["20000", "--seed", "6"], None),   # every event by MAME's cheats
                 ("tools/logic_test.py", ["8000", "--seed", "10"], None),   # two players
                 ("tools/render_test.py", ["3000", "--seed", "6", "--start", "1000", "--every", "3"], None),
                 ("tools/sprite_test.py", [], None)],             # edges, 16 shifts, holes, guards, 64 KB crossings
    "sbasketb": [("tools/prepare.py", [], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 3000),
                 ("tools/logic_test.py", ["8000", "--seed", "4"], None),    # two players
                 ("tools/logic_test.py", ["8000", "--seed", "6"], None),    # a 30 s game: game over, the name entry
                 ("tools/render_test.py", ["3000", "--seed", "1", "--start", "300", "--every", "5"], None),
                 ("tools/sprite_test.py", [], None),              # edges, 16 shifts, holes, banks, guards, 64 KB crossings
                 ("tools/logic_test.py", ["16000", "--autoplay", "--quiet"], None),   # the runtime's AUTOPLAY script
                 ("tools/sound_test.py", ["3000"], None)],        # the DMA clips against the game's sound commands
    "timeplt": [("tools/prepare.py", [], None),
                ("tools/build.py", ["--sim"], None),
                ("tools/logic_test.py", ["{n}"], 3000),
                ("tools/logic_test.py", ["8000", "--seed", "4"], None),    # play, infinite lives, every era
                ("tools/logic_test.py", ["6000", "--seed", "9"], None),    # invincible: many stages
                ("tools/render_test.py", ["3000", "--start", "1000", "--every", "3"], None),
                ("tools/render_test.py", ["4000", "--seed", "8", "--start", "1000", "--every", "5"], None),
                ("tools/sprite_test.py", [], None)],               # edges, 16 shifts, holes, bands, 64 KB crossings
    "gyruss": [("tools/prepare.py", [], None),
               ("tools/build.py", ["--sim"], None),
               ("tools/logic_test.py", ["{n}"], 3000),
               ("tools/logic_test.py", ["6000", "--seed", "5"], None),     # play, infinite lives
               ("tools/render_test.py", ["3000", "--start", "1000", "--every", "3"], None),
               ("tools/sprite_test.py", [], None),                 # edges, 16 shifts, holes, bands, 64 KB crossings
               ("tools/sound_test.py", ["4000"], None)],           # the translated driver and the YM
    "gauntlet": [("tools/prepare.py", [], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 3000),           # the patched program against the original (attract)
                 ("tools/logic_test.py", ["8000", "--seed", "1"], None),     # play, one player
                 ("tools/logic_test.py", ["8000", "--seed", "12"], None),    # play, two to four players
                 ("tools/render_test.py", ["--seed", "1", "--frames", "1500", "--first", "600", "--every", "5"], None),
                 ("tools/render_test.py", ["--seed", "11", "--level", "7", "--frames", "1200", "--first", "500", "--every", "4", "--nobuild"], None),
                 ("tools/sprite_test.py", ["--nobuild"], None),      # edges, 16 shifts, holes, shadows, 64 KB crossings
                 ("tools/sound_test.py", ["player"], None)],         # the STE's sound player against its model
    "ddragon": [("tools/prepare.py", [], None),
                ("tools/build.py", ["--sim"], None),
                ("tools/palette_test.py", [], None),             # flat text colours and bounded solid fills
                ("tools/logic_test.py", ["{n}"], 3000),
                ("tools/logic_test.py", ["6000", "--seed", "-1"], None),    # the recorded play
                ("tools/render_test.py", ["4000", "--seed", "-1", "--first", "1000", "--every", "10"], None),
                ("tools/sprite_test.py", [], None),                # edges, 16 shifts, holes, a 64 KB crossing
                ("tools/mcu_test.py", [], None),                   # the native MCU job against the HD63701Y0
                ("tools/sound_test.py", [], None)],                # the ADPCM and YM players
    "trojan": [("tools/prepare.py", [], None),
               ("tools/build.py", ["--sim"], None),
               ("tools/logic_test.py", ["{n}"], 3000),
               ("tools/logic_test.py", ["6000", "--seed", "5"], None),     # level 2 by DIP + cheats
               ("tools/render_test.py", ["3000", "--seed", "7", "--first", "1000", "--every", "5"], None),
               ("tools/sprite_test.py", [], None),                # edges, 16 shifts, holes, a 64 KB crossing
               ("tools/native_test.py", [], None)],               # the rst helpers in place, the natives
    "kungfum": [("tools/prepare.py", [], None),
                ("tools/build.py", ["--sim"], None),
                ("tools/logic_test.py", ["{n}"], 3000),
                ("tools/logic_test.py", ["6000", "--seed", "7"], None),     # play
                ("tools/render_test.py", ["6000", "--seed", "9"], None),
                ("tools/sprite_test.py", [], None),                 # edges, 16 shifts, holes, 64 KB crossings
                ("tools/sound_test.py", ["6000", "--random"], None)],   # the translated driver, YM, voices
    "rtype": [("tools/prepare.py", [], None),
              ("tools/palette_test.py", [], None),              # default stage colours, source phase, native cache fallback
              ("tools/build.py", ["--sim"], None),
              ("tools/dma_test.py", [], None),                         # production DMA with deadline/cadence schedulers
              ("tools/logic_test.py", ["{n}"], 3000),                    # attract
              ("tools/logic_test.py", ["8000", "--seed", "4"], None),     # play
              ("tools/logic_test.py", ["6000", "--seed", "8"], None),     # play, Invulnerability
              ("tools/render_test.py", ["--quiet"], None),
              ("tools/sprite_test.py", [], None)],
    "1943": [("tools/prepare.py", [], None), ("tools/video_test.py", [], None),
             ("tools/reference_test.py", ["700"], None),
             ("tools/build.py", ["--sim"], None),
             ("tools/sprite_test.py", [], None),                  # sprites at the window's edges: clipped, 16 shifts, 64 KB
             ("tools/front_test.py", [], None),                   # front tiles at the window's edges, the same
             ("tools/mcu_native_test.py", [], None),              # src/mcu.s's native INT1 against the translated firmware
             ("tools/logic_test.py", ["{n}"], 3000),
             ("tools/logic_test.py", ["3000", "--render", "--every", "3"], None),
             ("tools/logic_test.py", ["4000", "--render", "--every", "4", "--cheat", "13"], None),   # front layer scrolls sideways
             ("tools/logic_test.py", ["4000", "--render", "--every", "8", "--seed", "1"], None),
             ("tools/sound_test.py", ["20000"], None)],          # the STE's sound player against the model
    "gunsmoke": [("tools/reference_test.py", ["700"], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 3000),
                 ("tools/logic_test.py", ["4000", "--seed", "9"], None),     # MAME's cheats: round 6
                 ("tools/render_test.py", ["40", "seq", "--first", "1500"], None),
                 ("tools/render_test.py", ["20", "scroll"], None),
                 ("tools/render_test.py", ["4", "edges"], None),
                 ("tools/sprite_test.py", [], None),                # left/right edge clipping, 16 shifts, 64 KB
                 ("tools/sound_test.py", ["20000"], None)],        # the STE's sound player against the model
    "commando": [("tools/reference_test.py", [], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/dispatch_test.py", [], None),
                 ("tools/bake_test.py", [], None),
                 ("tools/logic_test.py", ["{n}"], 3000),
                 ("tools/render_test.py", ["20", "scroll"], None),
                 ("tools/render_test.py", ["4", "edges"], None),
                 ("tools/sprite_test.py", [], None),                # left/right edge clipping, 16 shifts, 64 KB
                 ("tools/sfx_test.py", ["{n}"], 1000),
                 ("tools/music_test.py", ["20000"], None)],
    "blktiger": [("tools/build.py", ["--sim"], None), ("tools/reference_test.py", ["700"], None),
                 ("tools/logic_test.py", ["{n}"], 1600),
                 ("tools/logic_test.py", ["4000", "--walk"], None),
                 ("tools/logic_test.py", ["2600", "--idle", "2400"], None),   # no button after the start: the intro story
                 ("tools/render_test.py", ["--frames", "3", "--step", "375", "--scroll-sweep", "--flip-layout-sweep", "--sprite-edges"], None),
                 ("tools/sprite_test.py", [], None),                # edge clipping, black band words, a random walk
                 ("tools/sound_test.py", ["6000"], None)],          # the STE's sound player against the model
    "dkongjr": [("tools/logic_test.py", ["{n}"], 3000),
                ("tools/logic_test.py", ["3000", "--nocoin"], None),     # the attract sequence: the title in tile bank 1
                ("tools/build.py", [], None),
                ("tools/sprite_test.py", [], None),                     # Donkey Kong's edge test on Junior's program
                ("tools/sound_test.py", [], None),                      # the sound driver's rules (run/dkongjr)
                ("tools/render_test.py", ["1700", "1300:4", "200:0:1"], None)],   # play, the hideout, the title
    "dkong": [("tools/logic_test.py", ["{n}"], 3000),
              ("tools/build.py", [], None),
              ("tools/sprite_test.py", [], None)],               # left/right edge clipping, 16 shifts, 64 KB (run/dkong)
    "galaga": [("tools/schedule_test.py", ["{n}"], 3000),
               ("tools/build.py", ["--sim"], None),
               ("tools/sprite_test.py", [], None),               # left/right edge clipping, sizes, flips, 16 shifts, 64 KB
               ("tools/sound_test.py", ["{n}"], 3000),          # the sound CPU against the reference, the YM mapping
               ("tools/render_test.py", [], None),                # the picture at frozen moments of the attract mode
               ("ref/mcu_events_test.py", ["{n}"], 3000),        # the event-driven 51XX against the cycle-exact one
               ("../../engine/mb88x_test.py", ["{n}"], 3000),    # the translated 51XX against the event-driven one
               ("tools/n51_test.py", ["{n}"], 3000)],            # the build's 51XX traffic against the reference
    "bublbobl": [("tools/mcu_test.py", ["{n}"], 2600),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 2000),          # (into the play: src/natives.s runs there)
                 ("tools/native_test.py", [], None),               # src/natives.s against the translations they replace
                 ("tools/render_test.py", ["seq", "1500", "20"], None),
                 ("tools/sprite_test.py", [], None),
                 ("tools/align_test.py", ["{n}"], 900),
                 ("tools/sound_test.py", ["6000"], None)],          # the STE's sound player against the model
    "1942": [("tools/build.py", ["--sim"], None),
             ("tools/logic_test.py", ["{n}"], 6000),
             ("tools/logic_test.py", ["9000", "--cheat"], None),      # MAME's cheats: the later stages
             ("tools/logic_test.py", ["6000", "--two"], None),        # a two-player game
             ("tools/sprite_test.py", [], None),
             ("tools/sound_test.py", ["3000"], None),
             ("tools/render_test.py", ["seq", "200", "1", "1200"], None)],
}
ENGINE_TESTS = ["engine/palette_quantize_test.py", "engine/ppo_test.py", "engine/borders_blit_test.py", "engine/m72_bitmap_test.py",
                "engine/sprite_blit_test.py", "engine/jagpad_test.py", "engine/ikbd_test.py", "engine/lz.py",
                "engine/hdd_test.py",                              # (tools/hddtest.sh: the same on Hatari's disks)
                "engine/m6809_test.py", "engine/hd63701_test.py",   # (MAME traces: build/m6809/, build/hd63701/)
                "engine/m6809x_test.py", "engine/konami1_test.py",
                "engine/v30_test.py",                              # (MAME traces: build/v30/)
                "engine/v30x_test.py",
                "engine/i8051_test.py",                            # (MAME traces: build/i8051/)
                "engine/z80m72_test.py",                           # (MAME trace: build/z80m72/)
                "engine/m6502mame_test.py"]                        # (MAME logs: build/m6502mame/)
assert set(COVER) == set(TESTS) == set(GAMES)


def game_script(game, rel):
    return str(ROOT / "games" / game / rel)


def call(cmd, cwd=None):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd).returncode


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = a[0]
    if cmd == "list":
        for g, prg in GAMES.items():
            print("%-10s %s" % (g, prg))
        return 0
    if cmd == "prg" and len(a) == 2 and a[1] in GAMES:       # (tools/hatari.sh)
        print(GAMES[a[1]])
        return 0
    if cmd == "test" and a[1:2] == ["engine"]:
        for t in ENGINE_TESTS:
            rc = call([PY, str(ROOT / t)])
            if rc:
                return rc
        return 0
    if cmd == "release":
        return call([PY, str(ROOT / "tools" / "release.py")] + a[1:])
    if cmd == "ppo":
        if len(a)<3 or a[1] not in (*GAMES, "all"):
            print("usage: port.py ppo <game|all> <train|record|verify|test> [--steps N --frames N]")
            return 2
        worker=os.environ.get("PPO_PYTHON",str(ROOT/"build/ppo-venv/bin/python"))
        if not Path(worker).exists():
            print("Create build/ppo-venv and install engine/ppo-requirements.txt")
            return 2
        games=list(GAMES) if a[1]=="all" else [a[1]]
        results=[]
        for g in games:
            if g in ("galaga", "pacman"):
                print("%s: no PPO profile yet (engine/ppo_profiles.py)" % g)
                results.append(dict(game=g,status="deferred"))
                if a[1]!="all":return 2
                continue
            options=list(a[2:])
            if a[1]=="all":
                for i,option in enumerate(options):
                    if option=="--out" and i+1<len(options):options[i+1]=str(Path(options[i+1])/g)
                    elif option.startswith("--out="):options[i]="--out="+str(Path(option.split("=",1)[1])/g)
            rc=call([worker,str(ROOT/"engine/ppo.py"),g,*options],cwd=ROOT)
            results.append(dict(game=g,status="passed" if rc==0 else "failed",returncode=rc))
            if a[1]!="all" and rc:return rc
        import json
        directory=ROOT/"build/ppo";directory.mkdir(exist_ok=True)
        (directory/"campaign.json").write_text(json.dumps(results,indent=2)+"\n")
        return int(any(r.get("returncode",0) for r in results))
    if len(a) < 2 or a[1] not in GAMES:
        print("usage: port.py %s <%s> ..." % (cmd, "|".join(GAMES)))
        return 2
    game, rest = a[1], a[2:]
    prepare = [PY, game_script(game, "tools/prepare.py")]
    if cmd == "prepare":
        return call(prepare + rest)
    if cmd in ("build", "cover", "test", "mame") and not (EXTRACTED / game).is_dir():
        rc = call(prepare)                  # (the extracted ROMs are not in git)
        if rc:
            return rc
    if cmd == "build":
        return call([PY, game_script(game, "tools/build.py")] + rest)
    if cmd == "cover":
        jobs = []
        wanted = [int(x) for x in rest]
        for script, seeds, frames, *extra in COVER[game]:     # (extra: the script's further arguments)
            for s in [x for x in wanted if x in seeds] if wanted else seeds:   # (a seed given: its group's frames)
                jobs.append([PY, game_script(game, script), str(s), str(frames)] + [str(x) for x in (extra[0] if extra else [])])
        if wanted and len(jobs) < len(wanted):
            sys.exit("port.py cover %s: not every seed is in COVER[%r]" % (game, game))
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
            codes = list(ex.map(lambda j: call(j, cwd=ROOT), jobs))
        return max(codes)
    if cmd == "test":
        for script, args, default in TESTS[game]:
            n = rest[0] if rest and default is not None else str(default)
            args = [x.format(n=n) for x in args]
            rc = call([PY, game_script(game, script)] + args)
            if rc:
                return rc
        return 0
    if cmd == "run":
        return call([str(ROOT / "tools" / "hatari.sh"), game] + rest)
    if cmd == "mame":
        return call([PY, game_script(game, "ref/mame_cmp_%s.py" % game)] + rest)
    print("unknown command", cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
