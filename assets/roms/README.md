# assets/roms

ROM archives (`*.zip`, as shipped, never modified) and the files the tools read.

| archive | set | extracted to | used by |
|---|---|---|---|
| `dkong.zip` | Donkey Kong (TKG-04) | `extracted/dkong/` (the 15 ROM files plus `cpu.rom`, the four CPU ROMs concatenated) | `games/dkong` |
| `galaga.zip` | Galaga | `extracted/galaga/` | `games/galaga` |
| `bublbobl.zip` | Bubble Bobble, Japan (MAME `bublbobl`) | `extracted/bublbobl/` | `games/bublbobl` |
| `bublboblr.zip` | Bubble Bobble, US / Romstar (MAME `bublboblr`) | not extracted: differs from `bublbobl` only in the two main-CPU ROMs; verified by `games/bublbobl/ref/rom_manifest.py` | cross-check, MAME captures |
| `1942.zip` | 1942 (Revision B, MAME `1942`) | `extracted/1942/` (the 27 files of the set) | `games/1942` |
| `1943.zip` + `bm.7k` | 1943: The Battle of Midway (Euro; MAME marks main ROM BAD_DUMP) | `extracted/1943/` (38 verified ROMs; swapped audio/character names resolved by checksum) | `games/1943` |
| `blktiger.zip` | Black Tiger (MAME `blktiger`) | `extracted/blktiger/` (20 verified files; `port.py prepare blktiger`) | `games/blktiger` |
| `commando.zip` | Commando (World, MAME `commando`) | `extracted/commando/` (22 verified files; `port.py prepare commando`) | `games/commando` |
| `gunsmoke.zip` | Gun.Smoke (MAME `gunsmoke`) | `extracted/gunsmoke/` (32 verified files; `port.py prepare gunsmoke`) | `games/gunsmoke` |
| `galaga88.zip` | other set | not extracted yet | — |

`extracted/` is not in git: `python port.py prepare <game>` (each game's `tools/prepare.py`) verifies the archive
against `games/<game>/docs/rom_manifest.json` and unpacks it; `port.py build`, `cover`, `test` and `mame` do that first
when the folder is missing.

Tools locate files through `engine/paths.py` (`EXTRACTED / "<game>" / name`); one folder per game.
