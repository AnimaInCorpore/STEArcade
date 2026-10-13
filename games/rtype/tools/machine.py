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


# ---- the port's schedule (the translation's lock-step reference: tools/logic_test.py) ----
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from m72board import M72  # noqa: E402

START = 400                       # the port starts from the board's state at this frame (the boot is not translated)
IDLE = (0x0040, 0x00D0)           # the main loop's head: mov bp,3060h; call [bp]; the queue [2ED8] / [2EDA]
VBL_VECTOR, RASTER_VECTOR = 0x20, 0x22
IDLE_TASK = 0x55E8                # [3060] while nothing runs in the foreground (a plain ret)


class RType(M72):
    """The board (MAME's schedule) to START; then the port's schedule: no sound CPU, no PIC, no time.  A port frame:
    the VBL interrupt (vector $20) taken at the idle point, the handler (the game's logic) and the foreground until the
    idle point again; then the raster interrupt (vector $22, the status bar's scroll) the same.  The idle point: the main
    loop's head with the foreground queue empty and no foreground task.  Writes to the ports go to `port_writes`
    ((port, value, width) this frame); the scroll, raster line and sprite DMA act as on the board."""

    def __init__(self, **kw):
        super().__init__("rtype", **kw)
        self.port_frames = 0
        self.port_writes = []
        self.irq_psw_addr = None

    def word(self, o):
        return self.ram[o] | (self.ram[o + 1] << 8)

    def idle(self):
        c = self.main.core.cpu
        return ((c.cs, c.ip) == IDLE and self.word(0x2ED8) == self.word(0x2EDA) and self.word(0x3060) == IDLE_TASK
                and c.ds == 0x4000 and c.ss == 0x4000)

    def boot(self, frames=START):
        while self.frame < frames:
            self.run_frame()
        c = self.main.core.cpu
        for _ in range(200):
            if self.idle():
                break
            c.step()
        if not self.idle():
            raise RuntimeError("main CPU not idle at frame %d (%04X:%04X)" % (self.frame, c.cs, c.ip))
        c.rd_op = c.rd
        c.io_wr = self.port_wr
        c.io_wr16 = self.port_wr16
        c.icount = 1 << 40                               # (steps without a slice)

    def port_wr(self, p, v):
        self.port_writes.append((p & 0xFF, v, 1))
        if p & 0xFF not in (0x00, 0x01, 0x02, 0x03, 0xC0, 0xC1):
            self.io_wr(p, v)

    def port_wr16(self, p, v):
        self.port_writes.append((p & 0xFF, v, 2))
        if p & 0xFE not in (0x00, 0x02, 0xC0):
            self.io_wr16(p, v)

    def run_irq(self, vector, limit=5000000):
        """the interrupt at the idle point, then until the idle point again"""
        c = self.main.core.cpu
        self.irq_psw_addr = (c.ss << 4) + ((c.sp - 2) & 0xFFFF)
        c.interrupt(vector)
        for _ in range(limit):
            c.step()
            if self.idle():
                return
        raise RuntimeError("the main CPU did not come back to its idle point (%04X:%04X)" % (c.cs, c.ip))

    def run_frame_port(self):
        self.port_writes = []
        self.run_irq(VBL_VECTOR)
        self.run_irq(RASTER_VECTOR)
        self.port_frames += 1
