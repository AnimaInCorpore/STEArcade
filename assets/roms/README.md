# assets/roms

The ROM archives (MAME sets, `*.zip`, as shipped, never modified) and the files the tools read.  **None of them is in
the repository** (`.gitignore`): supply the archives below yourself; `port.py prepare <game>` verifies one against
`games/<game>/docs/rom_manifest.json` and unpacks it.

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
| `splatter.zip` | Splatterhouse (Namco System 1) | `extracted/splatter/` | standalone Splatterhouse tools |
| `galaga88.zip` | Galaga '88 (Namco System 1) | `extracted/galaga88/` | standalone Galaga '88 tools |
| `pacmania.zip` | Pac-Mania (Namco System 1) | `extracted/pacmania/` | reference tools |
| `dspirit.zip` | Dragon Spirit (Namco System 1) | `extracted/dspirit/` | reference tools |
| `trackfld.zip` | Track & Field | `extracted/trackfld/` | reference tools |
| `hyperspt.zip` | Hyper Sports | `extracted/hyperspt/` | reference tools |
| `gyruss.zip` | Gyruss | `extracted/gyruss/` | reference tools |
| `rtype.zip` | R-Type (World, MAME `rtype`; without the M72 boards' PROMs and PALs, which the driver never reads) | `extracted/rtype/` (20 verified files); `build/rtype/mame_roms/` for MAME 0.289 (its names, zero-filled stand-ins) | `games/rtype` |
| `mrheli.zip` + `mh_c-pr-.ic1` | Mr. HELI no Daibouken (Japan, MAME `mrheli`; an older set: the i8751 program `mh_c-pr-.ic1`, crc32 897dc4ee, is a separate file) | `extracted/mrheli/` (19 verified files + the MCU program); `build/mrheli/mame_roms/` as for R-Type | `games/mrheli` |
| `kungfum.zip` | Kung-Fu Master (World, MAME `kungfum`; MAME's file names) | `extracted/kungfum/` (28 verified files) | `games/kungfum` |
| `trojanr.zip` | Trojan (Romstar, set 1, MAME `trojanr`; old file names `tb01.bin`-`tb25.bin`, `mb7114e.1e` = `tbb-1.1e`, `tbp24s10.7j` = `tbb-2.7j`) | `extracted/trojan/` (27 verified files); `build/trojan/mame_roms/` with MAME's names | `games/trojan` |
| `ddragon.zip` | Double Dragon (Japan set 1, MAME `ddragonj`; MAME's file names) | `extracted/ddragon/` (23 verified files); MAME runs `ddragonj` from `assets/roms` | `games/ddragon` |
| `gauntlet.zip` | Gauntlet (rev 14, MAME `gauntlet`; MAME's file names; `136037-104.6p` is the 8 KB half of the chip) | `extracted/gauntlet/` (20 verified files); `build/gauntlet/mame_roms/` with the alphanumerics padded to MAME's 16 KB | `games/gauntlet` |

Only the games in `port.py list` are registered with the common front end. For the other sets above, run
`venv/bin/python games/<game>/tools/prepare.py`; each uses its local manifest. Their renderer/reference scripts
are run directly rather than through `port.py`.

`extracted/` is not in git: `python port.py prepare <game>` (each game's `tools/prepare.py`) verifies the archive
against `games/<game>/docs/rom_manifest.json` and unpacks it; `port.py build`, `cover`, `test` and `mame` do that first
when the folder is missing.

Tools locate files through `engine/paths.py` (`EXTRACTED / "<game>" / name`); one folder per game.
