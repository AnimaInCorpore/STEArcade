"""R-Type (MAME `rtype`, Irem M72, 1987): the reference board.  The video is engine/m72.py (shared with Mr. HELI);
the board logic (an `RType` machine on engine/v30.py) comes here.

Main CPU: NEC V30 (MAME: 32 MHz / 2 / 2 = 8 MHz), uPD71059C interrupt controller (vector base $20: IR0 VBLANK at
line 256, IR2 the raster line).  Sound: a Z80 (3.579545 MHz) with a YM2151 behind the sound latch (port $00); R-Type
has no samples DAC.  Screen: 512 x 284 at 8 MHz, 384 x 256 visible (x 64-447, y 0-255), 55.017 Hz.

Memory map (main CPU, 20-bit addresses; rtype_map in m72.cpp):
    $00000-$3FFFF  ROM (rt_r-l0/h0 at $00000, rt_r-l1/h1 at $20000 and again at $E0000-$FFFFF: the reset vector)
    $40000-$43FFF  work RAM
    $C0000-$C03FF  sprite RAM          $C8000-$C8BFF palette 0 (sprites)   $CC000-$CCBFF palette 1 (tiles)
    $D0000-$D3FFF  FG video RAM        $D8000-$DBFFF BG video RAM           $E0000-$EFFFF sound CPU RAM window
    $FFFF0-$FFFFF  ROM
Ports (byte/word): in $00/$01 IN0, $02/$03 IN1, $04/$05 DSW; out $00 sound latch, $02 coin counters / flip / display
off / sound reset, $04 sprite DMA, $06 raster line, $40-$43 the uPD71059C, $80 $82 $84 $86 FG y, FG x, BG y, BG x.

What the game does each frame (MAME 0.289, attract mode): in the VBLANK interrupt (line ~256.3) the sprite DMA, then
FG scroll, BG scroll, raster line $16F (-> line 239); at the raster interrupt (line 239) FG scroll y $90, x 0: lines
0-239 are the playfield, lines 240-255 the status bar (FG map rows 0-1: "1P-", BEAM gauge, HI-) over the BG.

Horizontal layout (MAME snapshots, x 0-383 of the picture): the playfield and the ship use the whole width (tiles and
sprites x 0-383).  The status bar (lines 240-255) spans x 28-263: "1P-" ~28-54, the score ~80-112, "BEAM" ~82-125
above the gauge ~128-263, "HI-" ~146-175, the high score ~185-232; right of x 264 it is black.  The title screen's logo
and texts span x 20-367 (the copyright line at the bottom right ends at 367), the high score table x 56-129.  A
320-pixel STE window (the port shows less width, it does not scale).  The user's choice (2026-10-12): always the
centred window, x 32-351 (MAME bitmap x 96-415), in play and on the title alike; it cuts the "1" of "1P-", the left
part of the title's "R" and the last letters of the title's right-aligned texts (no fixed window holds the title).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from m72 import Video as M72Video, VideoState, pens, bands  # noqa: F401


class Video(M72Video):
    def __init__(self):
        super().__init__("rtype")
