"""Mr. HELI no Daibouken (MAME `mrheli`, Irem M72 with the i8751 MCU, 1987; a clone of `bchopper`): the reference
board.  The video is engine/m72.py (shared with R-Type); the board logic comes here later.

Main CPU: NEC V30 (8 MHz), uPD71059C interrupts (IR0 VBLANK at line 256, IR2 the raster line), the same screen as
R-Type (384 x 256 visible, 55.017 Hz).  Sound: a Z80 with a YM2151 and a DAC fed by the i8751 MCU (samples ROM).

Memory map (main CPU; m72_protected_map = m72_map + the MCU's dual-port RAM):
    $00000-$7FFFF  ROM (c-l0/h0 at $00000, c-l1/h1 at $20000, c-l3/h3 at $60000 and again at $E0000)
    $A0000-$A3FFF  work RAM            $B0000-$B0FFF MB8421 dual-port RAM shared with the i8751 (writes delayed to a
                                                     scheduler sync)
    $C0000-$C03FF  sprite RAM          $C8000-$C8BFF palette 0 (sprites)   $CC000-$CCBFF palette 1 (tiles)
    $D0000-$D3FFF  FG video RAM        $D8000-$DBFFF BG video RAM           $E0000-$EFFFF sound CPU RAM window
Ports: as R-Type ($00-$07, $40-$43, $80-$87) plus $C0 the second sound latch (NMI to the Z80).

The status panel is at the top: the VBLANK handler sets FG scroll x $1C0, y $180 (the panel's map rows) and raster
line 31; at line 31 the raster interrupt loads the playfield's FG scroll, and on some stages (the cave) re-programs
the raster line for a second FG y split lower down (three bands, FG y + 128 at the second cut).  The BG scroll is the
same in all bands (the panel's tiles are opaque over it).

Horizontal layout (MAME snapshots): the panel (lines 0-31) uses the full width: row 1 "1P-" score ~x 8-90, "HI-"
~110-200, "2P-" ~210-290, "TIME" ~300-380; row 2 lives ~5-40, ENERGY ~45-200, MONEY ~220-360. The playfield is x
0-383 too. A 320-pixel STE window cuts the panel's edges: TIME or the 1P score.  The user's choice (2026-10-12): always
the centred window, x 32-351 (MAME bitmap x 96-415), as for R-Type: "1P-" and the lives icon are cut, TIME stays
readable (its last digit cut), MONEY whole; the panel is not rearranged.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from m72 import Video as M72Video, VideoState, pens, bands  # noqa: F401


class Video(M72Video):
    def __init__(self):
        super().__init__("mrheli")
