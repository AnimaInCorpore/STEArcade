"""Kung-Fu Master (MAME `kungfum`, Irem M62, 1984): the reference board, from MAME irem/m62.cpp and m62_v.cpp.

Main CPU: Z80 at 18.432 MHz / 6 = 3.072 MHz (engine/z80mame.py: MAME's core, resumable mid-instruction, so the
interrupt is taken at the same instruction as in MAME).  Screen: 6.144 MHz pixel clock, 384 x 284 total, visible
x 128-383 and lines 0-255 (MAME's snapshot: 256 x 256), 56.34 Hz: 192 CPU cycles a line, 54528 a frame.  At time 0
the beam is at the start of the vertical blank (line 256); every VBLANK (a frame later each time) asserts IRQ 0 as a
HOLD_LINE (irq0_line_hold): the line drops when the CPU acknowledges it (vector $FF: RST 38 in IM 0).

Main CPU map: $0000-$7FFF ROM, $A000 w scroll x low, $B000 w scroll x high, $C000-$C0FF w sprite RAM (write only:
    reads 0), $D000-$D7FF tile codes, $D800-$DFFF tile attributes, $E000-$EFFF RAM; anything else reads 0.
I/O (A0-A7): reads 0 SYSTEM, 1 P1, 2 P2, 3 DSW1, 4 DSW2; writes 0 the sound command (irem_audio cmd_w: the latch, and
    the M6803's IRQ if bit 7 is 0), 1 flip screen (bit 0, XOR the DSW2 flip switch) + coin counters (bits 1, 2).
The sound board (M6803 + 2 AY-3-8910 + 2 MSM5205) only receives: it is not emulated; sound_log keeps (frame, value).

Video: a 64 x 32 tilemap of 8x8 3bpp tiles (1024: code = byte | attr bits 6-7 << 2; attr bits 0-4 colour, bit 5
flip x), opaque; rows 0-5 (the score panel) unscrolled, rows 6-31 scrolled x by the 16-bit scroll register.  Tiles
of rows 0-5, and tiles whose colour >> 1 is above 12, are drawn again over the sprites (category 1).  Sprites: 32
entries of 8 bytes at $C000, 16x16 3bpp (1024), drawn from the first to the last (the last on top):
    +0 colour (bits 0-4), +2/+3 y (9 bits), +4/+5 code (11 bits; +5 bit 6 flip x, bit 7 flip y), +6/+7 x (9 bits)
the height PROM (b-5f, by code >> 5) makes a sprite 1, 2 or 4 cells high.  Pen 0 is transparent.
Colours: two 256-pen palettes (tiles: g-1j/g-1f/g-1h, sprites: b-1m/b-1n/b-1l), 4 bits a gun through 2.2k/1k/470/220
ohm with a 470 ohm pulldown (compute_res_net, TTL outputs), then MAME's m62_amplify_contrast: both palettes scaled by
255000 / the brightest Y (299 R + 587 G + 114 B).  Pens here: 0-255 tiles, 256-511 sprites.

MAME draws the whole picture at the VBLANK (no partial updates in this driver): the state at run_frame's end is the
picture's state.
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
HTOTAL, VTOTAL = 384, 284
VBSTART = 256
SCAN_AS = HTOTAL * (AS // PIXEL_HZ)
FRAME_AS = VTOTAL * SCAN_AS
LINE = 192                                   # CPU cycles a line
VISIBLE = (128, 383, 0, 255)                 # MAME's visible area (min_x, max_x, min_y, max_y)

# MAME's defaults: DSW1 easy, slow energy loss, 3 lives, 1 coin 1 credit ($FF); DSW2 no flip, upright ($02 = 0),
# coin mode 1, no cheats, service off ($FD)
DSW1, DSW2 = 0xFF, 0xFD


def load(name):
    return (EXTRACTED / "kungfum" / name).read_bytes()


def res_net(inputs, rs=(2200, 1000, 470, 220), rgnd=470):
    """compute_res_net for RES_NET_VCC_5V | RES_NET_VIN_TTL_OUT, a channel RES_NET_AMP_NONE with a pulldown."""
    vol, voh, ttlh, vcc = 0.05, 4.0, 50, 5.0
    rtot = v = 0.0
    for i, r in enumerate(rs):
        if not (inputs >> i) & 1:
            rtot += 1.0 / r
            v += vol / r
    rtot += 1.0 / rgnd
    opencol = v / rtot > voh
    for i, r in enumerate(rs):
        if (inputs >> i) & 1 and not opencol:
            rtot += 1.0 / (r + ttlh)
            v += voh / (r + ttlh)
    rtot = 1.0 / rtot
    v *= rtot
    v = max(0.0, v)
    return int(v * 255 / vcc + 0.4)


def m62_pens(chr_prom, spr_prom):
    """([512, 3], [512, 3]): the tile palette's 256 pens, then the sprite palette's, as the PROMs give them (MAME's
    pen_color) and after m62_amplify_contrast (the screen's colours)."""
    raw = []
    for prom in (chr_prom, spr_prom):
        for i in range(256):
            raw.append([res_net(prom[i + o] & 15) for o in (0, 0x100, 0x200)])
    raw = np.array(raw, np.int64)
    ymax = max(1, int((299 * raw[:, 0] + 587 * raw[:, 1] + 114 * raw[:, 2]).max()))
    contrast = np.float32(255000.0 / ymax)              # (palette_t::set_contrast(float))
    adj = (raw.astype(np.float32) * contrast + np.float32(0.0)).astype(np.int64)    # adjust_palette_entry
    return raw.astype(np.uint8), np.clip(adj, 0, 255).astype(np.uint8)


class Video:
    def __init__(self):
        self.raw_pens, self.pens = m62_pens(load("g-1j-.bin") + load("g-1f-.bin") + load("g-1h-.bin"),
                             load("b-1m-.bin") + load("b-1n-.bin") + load("b-1l-.bin"))
        chars = load("g-4c-a.bin") + load("g-4d-a.bin") + load("g-4e-a.bin")
        third = G.rgn_frac(len(chars), 1, 3)
        self.tiles = G.decode_gfx(chars, 8, 8, len(chars) // 3 // 8, [2 * third, third, 0], list(range(8)),
                                  list(range(0, 64, 8)), 64)                    # gfx_8x8x3_planar
        spr = b"".join(load(n) for n in ("b-4k-.bin", "b-4f-.bin", "b-4l-.bin", "b-4h-.bin", "b-3n-.bin", "b-4n-.bin",
                                         "b-4m-.bin", "b-3m-.bin", "b-4c-.bin", "b-4e-.bin", "b-4d-.bin", "b-4a-.bin"))
        third = G.rgn_frac(len(spr), 1, 3)
        self.sprites = G.decode_gfx(spr, 16, 16, len(spr) // 3 // 32, [2 * third, third, 0],
                                    list(range(8)) + list(range(128, 136)), list(range(0, 128, 8)), 256)
        self.height = load("b-5f-.bin")

    def render_raw(self, mem, sprite_ram, scroll, flip=False):
        """The screen's pens [256 lines, 384] (x 128-383 visible; 0-255 tile pens, 256-511 sprite pens) from the tile
        RAM in mem ($D000-$DFFF of a 64 KB image), the 256 bytes of sprite RAM and the scroll register."""
        if flip:
            raise NotImplementedError("flip screen (cocktail)")
        code = np.frombuffer(bytes(mem[0xD000:0xD800]), np.uint8).reshape(32, 64).astype(np.int32)
        attr = np.frombuffer(bytes(mem[0xD800:0xE000]), np.uint8).reshape(32, 64)
        codes = code | ((attr & 0xC0).astype(np.int32) << 2)
        color = attr & 0x1F
        pix, _ = G.tile_pixmap(self.tiles, codes, color, attr & 0x20, np.zeros_like(attr), 32, 64, 0, 8)
        front = (color >> 1) > 0x0C
        front[:6] = True
        front = np.repeat(np.repeat(front, 8, 0), 8, 1)
        rows = [0] * 6 + [scroll & 0xFFFF] * 26
        tiles = G.scroll_rows(pix, rows, 256)[:, :HTOTAL].astype(np.int16)
        front = G.scroll_rows(front, rows, 256)[:, :HTOTAL]
        bm = tiles.copy()
        clip = VISIBLE
        sr = sprite_ram
        for offs in range(0, 0x100, 8):
            code = sr[offs + 4] + ((sr[offs + 5] & 7) << 8)
            col = sr[offs] & 0x1F
            sx = 256 * (sr[offs + 7] & 1) + sr[offs + 6]
            sy = 256 + 128 - 15 - (256 * (sr[offs + 3] & 1) + sr[offs + 2])
            flipx, flipy = sr[offs + 5] & 0x40, sr[offs + 5] & 0x80
            i = self.height[(code >> 5) & 0x1F]
            if i == 1:
                code &= ~1
                sy -= 16
            elif i == 2:
                i = 3
                code &= ~3
                sy -= 3 * 16
            incr = 1
            if flipy:
                incr = -1
                code += i
            while i >= 0:
                G.draw_gfx(bm, clip, self.sprites, code + i * incr, np.int16(256 + col * 8), flipx, flipy, sx, sy + 16 * i,
                           lambda s: s == 0)
                i -= 1
        bm[front] = tiles[front]
        return bm

    def render_rgb(self, mem, sprite_ram, scroll, flip=False):
        """The visible picture as MAME's snapshot shows it: [256, 256, 3]."""
        return self.pens[self.render_raw(mem, sprite_ram, scroll, flip)[:, VISIBLE[0]:VISIBLE[1] + 1]]


class KungFuMaster:
    def __init__(self, dsw1=DSW1, dsw2=DSW2):
        self.mem = bytearray(0x10000)
        self.mem[0:0x4000] = load("a-4e-c.bin")
        self.mem[0x4000:0x8000] = load("a-4d-c.bin")
        self.sprite_ram = bytearray(0x100)
        self.scroll = 0
        self.flip = 0
        self.system = self.p1 = self.p2 = 0xFF
        self.dsw1, self.dsw2 = dsw1, dsw2
        self.sound_log = []                    # (frame, command)
        self.video_log = []                    # this frame's (line, what, value): scroll and sprite RAM writes
        self.frame = 0
        self.cpu = Z80Mame(self.rd, self.wr, self.io_rd, self.io_wr, self.irq_ack)
        self.apc = AS // CPU_HZ                # HZ_TO_ATTOSECONDS(3072000): a cycle is a little longer than two pixels
        self.local = 0                         # the CPU's time (attoseconds) at its last run's end
        self.video = None

    # ---- buses ----
    def rd(self, a):
        if a < 0x8000 or 0xD000 <= a < 0xF000:
            return self.mem[a]
        return 0

    def wr(self, a, v):
        if 0xD000 <= a < 0xF000:
            self.mem[a] = v
        elif 0xC000 <= a < 0xC100:
            self.sprite_ram[a - 0xC000] = v
            self.video_log.append((self.line(), a, v))
        elif a == 0xA000:
            self.scroll = (self.scroll & 0xFF00) | v
            self.video_log.append((self.line(), a, v))
        elif a == 0xB000:
            self.scroll = (self.scroll & 0xFF) | (v << 8)
            self.video_log.append((self.line(), a, v))

    def io_rd(self, p):
        p &= 0xFF
        if p == 0: return self.system
        if p == 1: return self.p1
        if p == 2: return self.p2
        if p == 3: return self.dsw1
        if p == 4: return self.dsw2
        return 0

    def io_wr(self, p, v):
        p &= 0xFF
        if p == 0:
            self.sound_log.append((self.frame, v))
        elif p == 1:
            self.flip = (v ^ (~self.dsw2 & 1)) & 1

    def irq_ack(self):
        self.cpu.set_input("irq", 0)            # HOLD_LINE: cleared by the acknowledge
        return 0xFF

    def now(self):
        return self.local + self.cpu.executed() * self.apc

    def line(self):
        """the beam's line now (vpos: line 256 at time 0)"""
        return (self.now() % FRAME_AS // SCAN_AS + VBSTART) % VTOTAL

    # ---- schedule ----
    def run_frame(self):
        """Runs to the next VBLANK and asserts the IRQ: the state MAME's frame_done callback sees.
        Frame k ends at k * FRAME_AS, which is 54528 k - 1.0000002 k cycles: the CPU gets 54528 k - 1 cycles (it may
        finish its last M-cycle beyond), and takes the IRQ at its next instruction.  MAME's divu_64x32(delta >> 8,
        apc >> 8) would round one long slice up to 54528 k; MAME's own slices are short (the sound CPU's timeslices,
        the screen's timers), so the exact division is what MAME's trace shows."""
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
        return self.video.render_rgb(self.mem, self.sprite_ram, self.scroll, bool(self.flip))


if __name__ == "__main__":
    import time
    k = KungFuMaster()
    t = time.time()
    for _ in range(300):
        k.run_frame()
    print("300 frames in %.1f s, pc %04X, sound commands %d, scroll %04X" % (time.time() - t, k.cpu.PC,
                                                                            len(k.sound_log), k.scroll))


class KungFuPort(KungFuMaster):
    """The STE runtime's schedule (src/kungfum.s).  The game's foreground waits for the IRQ in spin loops, or (in play)
    runs a loop of HUD work over and over while the IRQ handler does the game: those pcs are the idle hooks (HOOKS:
    pc -> the condition under which the foreground waits there; the play loop's head always yields).  One call of
    run_frame_port = one arcade frame: the IRQ handler (RST 38) runs to its return (to TOKEN; the foreground goes on at
    the hook's pc), or to wherever it jumps instead (at 012A / 0396 it restarts the foreground at 0217 with a new
    stack); then the foreground runs at least one instruction and on until a hook says it waits.  `ld a,r` reads the
    port's z80_rnd (a 16-bit shift register) instead of the refresh register.  engine/z80.py runs the CPU."""
    HOOKS = {
        0x5714: lambda m: m.mem[0xE882] != 0,      # wait for $E882 frames (570D: ld (hl),a ... ld a,(hl); and a; jr nz)
        0x491B: lambda m: m.mem[0xE020] != 0x08,   # the intro: wait for the IRQ's sequence counter
        0x4925: lambda m: m.mem[0xE020] != 0x0B,
        0x4946: lambda m: m.mem[0xE000] != 0x0B,   # the title: "insert coin" until the IRQ saw a coin (state $0B)
        0x4997: lambda m: m.mem[0xE000] != 0x0B,   # the demo play's loop (0FB8, the HUD) until a coin
        0x51B8: lambda m: m.mem[0xE904] & 3 == 0,  # "push start" until a start button (the IRQ's input bits)
        0x0588: lambda m: m.mem[0xE882] != 0,      # wait for $E882 frames with the HUD work (0582)
        0x03D2: lambda m: m.mem[0xE906] & 0xA0 != 0,   # level selection: the buttons released
        0x03D9: lambda m: m.mem[0xE904] & 2 == 0 and m.mem[0xE906] & 0xA0 == 0,   # level selection: a button
        0x5061: lambda m: m.mem[0xE882] != 0,      # wait for $E882 frames, a text animated meanwhile (5038)
        0x542E: lambda m: m.mem[0xE882] != 0,      # wait for $E882 frames, a text drawn meanwhile (5416)
        0x7BE8: lambda m: m.mem[0xE904] & 2 == 0,  # wait for start 2
        0x7BEF: lambda m: m.mem[0xE904] & 2 != 0,  # and for its release
        0x029C: lambda m: True,                    # the play loop (HUD, time, score, extra lives): once a frame
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

    def line(self):
        return 0

    def rnd(self):
        """What the port's z80_rnd gives for `ld a,r`: a 16-bit shift register byte."""
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
                return
        raise RuntimeError('the foreground did not wait (pc %04X, frame %d)' % (c.pc, self.frame))

    def run_frame_port(self):
        c = self.cpu
        self.video_log = []
        if not self.booted:
            self.run_to_idle()
            self.booted = True
        c.iff1 = c.iff2 = 0
        c.halted = False
        c.push(self.TOKEN)
        c.pc = 0x38
        hooks = self.HOOKS
        for _ in range(3000000):
            c.step()
            if c.pc == self.TOKEN:
                c.pc = self.idle_pc
                self.run_to_idle()
                break
            h = hooks.get(c.pc)
            if h is not None and h(self):           # (the handler restarted the foreground, which waits now)
                self.idle_pc = c.pc
                break
        else:
            raise RuntimeError('the interrupt did not return (frame %d)' % self.frame)
        self.irq_count += 1
        self.frame += 1
