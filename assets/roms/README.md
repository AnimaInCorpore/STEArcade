# assets/roms

ROM archives (`*.zip`, as shipped, never modified) and the files the tools read.

| archive | set | extracted to | used by |
|---|---|---|---|
| `dkong.zip` | Donkey Kong (TKG-04) | `extracted/dkong/` (the 15 ROM files plus `cpu.rom`, the four CPU ROMs concatenated) | `games/dkong` |
| `galaga.zip` | Galaga | `extracted/galaga/` | `games/galaga` |
| `bublbobl.zip` | Bubble Bobble, Japan (MAME `bublbobl`) | `extracted/bublbobl/` | `games/bublbobl` |
| `bublboblr.zip` | Bubble Bobble, US / Romstar (MAME `bublboblr`) | not extracted: differs from `bublbobl` only in the two main-CPU ROMs; verified by `games/bublbobl/ref/rom_manifest.py` | cross-check, MAME captures |
| `1942.zip` | 1942 (Revision B, MAME `1942`) | `extracted/1942/` (the 27 files of the set) | `games/1942` |
| `galaga88.zip` | other set | not extracted yet | — |

Tools locate files through `engine/paths.py` (`EXTRACTED / "<game>" / name`); one folder per game.
