"""Moon Patrol (MAME `mpatrol`, Irem M52, 1982): the reference board, from MAME irem/m52.cpp.

Main CPU: Z80 at 18.432 MHz / 6 = 3.072 MHz (engine/z80mame.py: MAME's core).  Screen: 6.144 MHz pixel clock,
384 x 282 total, visible x 136-375 and lines 22-273 (MAME's snapshot: 240 x 252), 56.74 Hz: 192 CPU cycles a line,
54144 a frame.  At time 0 the beam is at the start of the vertical blank (line 274); every VBLANK (a frame later each
time) asserts IRQ 0 as a HOLD_LINE (irq0_line_hold): the line drops when the CPU acknowledges it (vector $FF).

Main CPU map: $0000-$3FFF ROM, $8000-$83FF tile codes, $8400-$87FF tile colours, $8800-$8FFF r protection,
    $C800-$CBFF w sprite RAM (mirrored at $CC00; write only: reads 0), $D000-$D7FF: writes a & 3 = 0 the sound
    command, 1 flip screen + coin counters; reads a & 7 = 0 IN0, 1 IN1, 2 IN2, 3 DSW1, 4 DSW2; $E000-$E7FF RAM;
    anything else reads 0.
I/O writes (port & $E0): $00 text scroll, $40 background 1 x (hills / city), $60 its y, $80 background 2 x (mountains),
    $A0 its y, $C0 background control.  The protection read gives popcount(bg1 x & $7F) ^ (bg1 x >> 7).
The sound board (M6803 + 2 AY-3-8910 + MSM5205) only receives: it is not emulated; sound_log keeps (frame, value).

Video, drawn back to front (MAME draws the whole picture at the VBLANK: no partial updates in this driver):
  * the sprite palette's pen 0 everywhere;
  * unless control bit 5: the mountains (bit 4 off), then the hills (bit 1 off) or else the city (bit 2 off): 256 x 64
    2bpp images (rows 64-127 of the 128-row element are the ROM region's $FF fill: pen 3), pen 0 transparent, at
    x = xpos + 124 and xpos - 132, y = ypos + 16, with pen 3 filled over the 128 lines below the element;
  * the text layer: 32 x 32 tiles of 8 x 8 2bpp (512: code = byte | colour bit 7 << 8; colour bits 0-6), rows 0-6
    opaque, the rest with pen 0 transparent; tilemap lines 0-191 scrolled x by 255, lines 192-255 by -(data + 1)
    (scrolldx 127, scrolldy 16);
  * sprites: 64 entries of 4 bytes (y, attributes: colour 0-5 / flip x 6 / flip y 7, code, x), 16 x 16 3bpp (the third
    plane is zero), at x = sx + 129, y = 257 - sy; drawn per 16-entry group from the group's last to its first, the
    groups in order (later on top); a pixel is transparent when its pen's lookup gives colour 0 (transmask).
Colours: three palettes (MAME's resistor weights).  Pens here: 0-511 text, 512-767 sprites, 768-779 backgrounds.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from z80mame import Z80Mame
import mamegfx as G

AS = 10 ** 18
CPU_HZ = 3072000
PIXEL_HZ = 6144000
HTOTAL, VTOTAL = 384, 282
VBSTART = 274
SCAN_AS = HTOTAL * (AS // PIXEL_HZ)
FRAME_AS = VTOTAL * SCAN_AS
LINE = 192                                   # CPU cycles a line
VISIBLE = (136, 375, 22, 273)                # MAME's visible area (min_x, max_x, min_y, max_y)
TX_PENS, SP_PENS, BG_PENS = 0, 512, 768

# MAME's defaults: DSW1 3 lives, bonus 10000 30000 50000, 1 coin 1 credit ($FE); DSW2 no flip, upright, coin mode 1,
# no cheats, service off ($FD)
DSW1, DSW2 = 0xFE, 0xFD


def load(name):
    return (EXTRACTED / "mpatrol" / name).read_bytes()


def bit(v, n):
    return (v >> n) & 1


def m52_pens():
    """[780, 3]: the text palette's 512 pens, the sprite palette's 256 (through the lookup PROM), the backgrounds' 12."""
    r3, r2 = [1000, 470, 220], [470, 220]
    wr, wg, wb = G.resistor_weights(0, 255, -1.0, (r3, 0, 0), (r3, 0, 0), (r2, 0, 0))
    scale = 255.0 / max(sum(w) for w in G.resistor_weights(0, 255, 1.0, (r3, 0, 0), (r3, 0, 0), (r2, 0, 0)))

    def rgb332(p, wr, wg, wb):
        return [G.combine(wr, bit(p, 0), bit(p, 1), bit(p, 2)), G.combine(wg, bit(p, 3), bit(p, 4), bit(p, 5)),
                G.combine(wb, bit(p, 6), bit(p, 7))]

    pens = [rgb332(p, wr, wg, wb) for p in load("mpc-4.2a")]
    sr, sg, sb = G.resistor_weights(0, 255, scale, (r2, 470, 0), (r3, 470, 0), (r3, 470, 0))
    spr = [[G.combine(sr, bit(p, 6), bit(p, 7)), G.combine(sg, bit(p, 3), bit(p, 4), bit(p, 5)),
            G.combine(sb, bit(p, 0), bit(p, 1), bit(p, 2))] for p in load("mpc-1.1f")]
    pens += [spr[c & 31] for c in load("mpc-2.2h")]
    bg = [rgb332(p, wr, wg, wb) for p in load("mpc-3.1m")]
    pens += [bg[i] for i in (0, 4, 8, 12, 0, 1, 2, 3, 0, 17, 18, 19)]
    return np.array(pens, np.uint8)


class Video:
    def __init__(self):
        self.pens = m52_pens()
        self.sp_lookup = np.frombuffer(load("mpc-2.2h"), np.uint8)
        tx = load("mpe-4.3f") + load("mpe-5.3e")
        half = G.rgn_frac(len(tx), 1, 2)
        self.tiles = G.decode_gfx(tx, 8, 8, len(tx) // 2 // 8, [half, 0], list(range(8)), list(range(0, 64, 8)), 64)
        sp = load("mpb-2.3m") + load("mpb-1.3n") + bytes(0x1000)
        third = G.rgn_frac(len(sp), 1, 3)
        self.sprites = G.decode_gfx(sp, 16, 16, len(sp) // 3 // 32, [2 * third, 0, third],
                                    list(range(8)) + list(range(128, 136)), list(range(0, 128, 8)), 256)
        xo = [g * 8 + i for g in range(64) for i in range(4)]
        yo = [b + 0x200 * r for b in (0, 0x4000, 0x8000, 0xC000) for r in range(32)]
        self.bgs = [G.decode_gfx(load(n) + b"\xff" * 0x1000, 256, 128, 1, [4, 0], xo, yo, 0x8000)[0]
                    for n in ("mpe-1.3l", "mpe-2.3k", "mpe-3.3h")]

    def text_layer(self, vram, cram, scroll):
        """(pens, opaque) [282, 384] of the text tilemap as tilemap_t::draw puts it on the screen bitmap."""
        codes = np.frombuffer(bytes(vram), np.uint8).astype(np.int32).reshape(32, 32)
        col = np.frombuffer(bytes(cram), np.uint8).reshape(32, 32)
        codes = codes | ((col & 0x80).astype(np.int32) << 1)
        zero = np.zeros_like(col)
        pix, raw = G.tile_pixmap(self.tiles, codes, col & 0x7F, zero, zero, 32, 32, TX_PENS, 4)
        opaque = raw != 0
        opaque[:7 * 8] = True                                           # TILE_FORCE_LAYER0: rows 0-6
        values = [(127 - 255) % 256] * 3 + [(127 + scroll + 1) % 256]   # effective_rowscroll per 64-line block
        ys = (np.arange(VTOTAL) - 16) % 256                             # scrolldy 16 (the wrap draws every line)
        xs = np.arange(HTOTAL)
        tx = (xs[None, :] - np.array(values)[ys // 64][:, None]) % 256
        return pix[ys[:, None], tx], opaque[ys[:, None], tx]

    def draw_background(self, bm, xpos, ypos, image):
        img = self.bgs[image]
        xpos += 124
        ypos += 16
        x0, x1, y0, y1 = VISIBLE
        for sx in (xpos, xpos - 256):
            G.draw_gfx(bm, VISIBLE, img[None], 0, np.int16(BG_PENS + 4 * image), False, False, sx, ypos,
                       lambda s: s == 0)
        top, bot = max(ypos + 128, y0), min(ypos + 255, y1)
        if top <= bot:
            bm[top:bot + 1, x0:x1 + 1] = BG_PENS + 4 * image + 3

    def render_raw(self, vram, cram, sprite_ram, regs, flip=False, layers=("bg", "tx", "sp")):
        """The screen's pens [282, 384] (MAME's bitmap; VISIBLE is the snapshot) from the text RAMs, the 256 bytes of
        sprite RAM and regs = (scroll, bg1 x, bg1 y, bg2 x, bg2 y, control).  layers: which of the backgrounds, the
        text (but the opaque rows 0-6, always) and the sprites to draw (the STE renderer's tests, layer by layer)."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        scroll, x1, y1, x2, y2, ctl = regs
        bm = np.full((VTOTAL, HTOTAL), SP_PENS, np.int16)
        if not ctl & 0x20 and "bg" in layers:
            if not ctl & 0x10:
                self.draw_background(bm, x2, y2, 0)                     # distant mountains
            if not ctl & 0x02:
                self.draw_background(bm, x1, y1, 1)                     # hills
            elif not ctl & 0x04:
                self.draw_background(bm, x1, y1, 2)                     # city
        pix, opaque = self.text_layer(vram, cram, scroll)
        if "tx" not in layers:
            opaque[(np.arange(VTOTAL) - 16) % 256 >= 7 * 8] = False
        bm[opaque] = pix[opaque]
        sr = sprite_ram
        for group in (range(0x3C, 0x100, 0x40) if "sp" in layers else ()):
            for offs in range(group, (group & 0xC0) - 1, -4):
                sy = 257 - sr[offs]
                color = sr[offs + 1] & 0x0F                              # (& $3F, modulo the 16 colours)
                flipx, flipy = sr[offs + 1] & 0x40, sr[offs + 1] & 0x80
                code, sx = sr[offs + 2], sr[offs + 3] + 129
                lut = self.sp_lookup[color * 8:color * 8 + 8]
                G.draw_gfx(bm, VISIBLE, self.sprites, code, np.int16(SP_PENS + color * 8), flipx, flipy, sx, sy,
                           lambda s, lut=lut: lut[s] == 0)
        return bm

    def render_rgb(self, vram, cram, sprite_ram, regs, flip=False):
        """The visible picture as MAME's snapshot shows it: [252, 240, 3]."""
        x0, x1, y0, y1 = VISIBLE
        return self.pens[self.render_raw(vram, cram, sprite_ram, regs, flip)[y0:y1 + 1, x0:x1 + 1]]


class MoonPatrol:
    def __init__(self, dsw1=DSW1, dsw2=DSW2):
        self.mem = bytearray(0x10000)
        self.mem[0:0x4000] = b"".join(load(n) for n in ("mpa-1.3m", "mpa-2.3l", "mpa-3.3k", "mpa-4.3j"))
        self.sprite_ram = bytearray(0x400)
        self.regs = [0] * 6                    # scroll, bg1 x, bg1 y, bg2 x, bg2 y, control
        self.flip = 0
        self.in0 = self.in1 = self.in2 = 0xFF
        self.dsw1, self.dsw2 = dsw1, dsw2
        self.sound_log = []                    # (frame, command)
        self.video_log = []                    # this frame's (line, what, value)
        self.frame = 0
        self.cpu = Z80Mame(self.rd, self.wr, self.io_rd, self.io_wr, self.irq_ack)
        self.apc = AS // CPU_HZ
        self.local = 0
        self.video = None

    # ---- buses ----
    def rd(self, a):
        if a < 0x4000 or 0x8000 <= a < 0x8800 or 0xE000 <= a < 0xE800:
            return self.mem[a]
        if 0x8800 <= a < 0x9000:
            x = self.regs[1]
            return (bin(x & 0x7F).count("1") ^ (x >> 7)) & 0xFF
        if 0xD000 <= a < 0xD800:
            return (self.in0, self.in1, self.in2, self.dsw1, self.dsw2, 0, 0, 0)[a & 7]
        return 0

    def wr(self, a, v):
        if 0x8000 <= a < 0x8800 or 0xE000 <= a < 0xE800:
            self.mem[a] = v
        elif 0xC800 <= a < 0xD000:
            self.sprite_ram[a & 0x3FF] = v
        elif 0xD000 <= a < 0xD800:
            if a & 3 == 0:
                self.sound_log.append((self.frame, v))
            elif a & 3 == 1:
                self.flip = (v ^ (~self.dsw2 & 1)) & 1

    def io_rd(self, p):
        return 0

    def io_wr(self, p, v):
        p &= 0xE0
        i = (0, None, 1, 2, 3, 4, 5, None)[p >> 5]
        if i is not None:
            self.regs[i] = v
            self.video_log.append((self.line(), p, v))

    def irq_ack(self):
        self.cpu.set_input("irq", 0)            # HOLD_LINE: cleared by the acknowledge
        return 0xFF

    def now(self):
        return self.local + self.cpu.executed() * self.apc

    def line(self):
        """the beam's line now (vpos: line 274 at time 0)"""
        return (self.now() % FRAME_AS // SCAN_AS + VBSTART) % VTOTAL

    # ---- schedule ----
    def run_frame(self):
        """Runs to the next VBLANK and asserts the IRQ: the state MAME's frame_done callback sees (as Kung-Fu
        Master's reference, games/kungfum/tools/machine.py)."""
        self.video_log = []
        target = (self.frame + 1) * FRAME_AS
        while True:
            delta = target - self.local
            if delta < self.apc:
                break
            ran = self.cpu.run(delta // self.apc)
            self.local += ran * self.apc
        self.frame += 1
        self.cpu.set_input("irq", 1)

    def render_rgb(self):
        if self.video is None:
            self.video = Video()
        return self.video.render_rgb(self.mem[0x8000:0x8400], self.mem[0x8400:0x8800], self.sprite_ram[:0x100],
                                     self.regs, bool(self.flip))



class MoonPatrolPort(MoonPatrol):
    """The STE runtime's schedule.  The IRQ handler ($0038) does the game: it copies the sprite list ($E100) to the
    sprite RAM, writes the scroll registers ($056D), counts the frame ($E04E) and the timers ($E050, $E051), and runs
    the game's step ($040E, $047A, $01EC, ...); at $0104 it restarts the foreground with a new stack.  The foreground
    waits for the IRQ in spin loops on $E050 / $E047, or (attract and play) runs a work loop at $026E: five helpers,
    then the task queue the IRQ fills ($E600, indices $E1CF / $E1D0), back to $026E when it is empty.  Those pcs are
    the idle hooks (HOOKS: pc -> the condition under which the foreground waits there; the work loop's head always
    yields, so its helpers run once a frame instead of as often as the arcade's spare time allows).  IRQ_WAITS are
    waits inside the handler (the stop mode): the frame ends there and the next one goes on there, without an IRQ.  One call of
    run_frame_port = one arcade frame: the IRQ handler runs to its return (to TOKEN; the foreground goes on at the
    hook's pc) or to a hook it reached instead (the restart), then the foreground runs at least one instruction and on
    until a hook says it waits.  `ld a,r` reads the port's z80_rnd (a 16-bit shift register) instead of the refresh
    register.  engine/z80.py runs the CPU."""
    HOOKS = {
        0x026E: lambda m: True,                    # the work loop (helpers, the IRQ's task queue): once a frame
        0x0315: lambda m: m.mem[0xE050] != 0,      # wait for $E050 frames (0312: ld ($E050),a ... jr nz)
        0x0359: lambda m: m.mem[0xE050] != 0,
        0x05ED: lambda m: m.mem[0xE050] != 0,
        0x078E: lambda m: m.mem[0xE047] != 0,      # wait until the IRQ clears $E047
        0x010D: lambda m: not m.starts(),          # "push start" (0533: the text, blinking) until a game starts
        0x01A7: lambda m: m.mem[0xE050] != 0 and (m.mem[0xE048] == 0 or not m.starts()),
                                                   # the continue's countdown ($E054 each $40 frames), a start
        0x0B59: lambda m: m.mem[0xE051] > 1,       # sector selection: no new start 1 press, until $E051 runs out
    }
    IRQ_WAITS = {                              # waits inside the IRQ handler: the next frame goes on there, no new IRQ
        0x00AF: lambda m: m.in0 & 1 != 0,          # stop mode (DSW2 bit 4): stopped by start 2 until start 1
    }
    TOKEN = 0xF7FE

    def __init__(self, dsw1=DSW1, dsw2=DSW2):
        super().__init__(dsw1, dsw2)
        from z80 import Z80
        self.cpu = Z80(self.rd, self.wr, self.io_rd, self.io_wr)
        self.cpu.r_hook = self.rnd
        self.rnd_state = 0xACE1
        self.booted = False
        self.irq_count = 0
        self.idle_pc = None
        self.idle = {}                         # hook pc -> times the foreground waited there
        self.irq_wait_pc = None                # the IRQ_WAITS pc the handler waits at, or None

    def line(self):
        return 0

    def starts(self):
        """whether 0533's check of the start buttons ($E053, the IRQ's copy of IN0) starts a game: start 1, or start 2
        with more than one credit ($E048, BCD; 0559: sub 1, daa, ret z)"""
        b = self.mem[0xE053]
        return bool(b & 1) or bool(b & 2) and self.mem[0xE048] != 1

    def rnd(self):
        """What the port's z80_rnd gives for `ld a,r`: a 16-bit shift register byte (as Kung-Fu Master's)."""
        s = self.rnd_state
        s = (s >> 1) ^ (0xB400 if s & 1 else 0)
        self.rnd_state = s
        return s & 0xFF

    def run_to_idle(self, limit=3000000):
        """runs the foreground (at least one instruction) until it waits at a hook"""
        c = self.cpu
        hooks = self.HOOKS
        for _ in range(limit):
            c.step()
            h = hooks.get(c.pc)
            if h is not None and h(self):
                self.idle_pc = c.pc
                self.idle[c.pc] = self.idle.get(c.pc, 0) + 1
                return
        raise RuntimeError("the foreground did not wait (pc %04X, frame %d)" % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        self.video_log = []
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        c.halted = False
        if self.irq_wait_pc is not None:       # (the handler waited inside: it goes on there, no new IRQ)
            c.pc, self.irq_wait_pc = self.irq_wait_pc, None
        else:
            c.iff1 = c.iff2 = 0
            c.push(self.TOKEN)
            c.pc = 0x38
        hooks = self.HOOKS
        waits = self.IRQ_WAITS
        for _ in range(3000000):
            w = waits.get(c.pc)
            if w is not None and w(self):
                self.irq_wait_pc = c.pc
                break
            c.step()
            if c.pc == self.TOKEN:
                c.pc = self.idle_pc
                self.run_to_idle()
                break
            h = hooks.get(c.pc)
            if h is not None and h(self):           # (the handler restarted the foreground, which waits now)
                self.idle_pc = c.pc
                self.idle[c.pc] = self.idle.get(c.pc, 0) + 1
                break
        else:
            raise RuntimeError("the interrupt did not return (frame %d)" % self.frame)
        self.irq_count += 1
        self.frame += 1

if __name__ == "__main__":
    import time
    from PIL import Image
    m = MoonPatrol()
    out = Path(__file__).resolve().parents[3] / "build" / "mpatrol"
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    shots = [int(a) for a in sys.argv[1:]] or [300, 600, 1200, 2400]
    while m.frame < max(shots):
        m.run_frame()
        if m.frame in shots:
            Image.fromarray(m.render_rgb()).save(out / ("ref%d.png" % m.frame))
    print("%d frames in %.1f s, pc %04X, sound commands %d, regs %s" % (m.frame, time.time() - t, m.cpu.PC,
                                                                      len(m.sound_log), m.regs))
