"""Gyruss: the sound board's Z80 driver (16 KB) translated to 68000 code (engine/z80x.py).

    from sndgen import generate; text, report = generate()   -> build/gyruss/snd_code.s

Labels X<pc>, the dispatch table snd_dispatch_sw, the register map of the main program's translation (z80x.FAST: d0
A, d1 BC (byte-swapped), d2 DE, d3 HL, d4 IX, a2 IY, d6 the flags, a5 SP, a6 the sound CPU's 64 KB block, a4 the
table); src/sound.s saves the main program's registers around it.  The I/O: `out (n),a` / `out (c),r` call snd_out
(d7 = the port, d5 = the value: the AYs' address and data writes, the i8039's latch and IRQ), `in a,(n)` calls snd_in
(d7 = the port; the byte back in d7: an AY register; the third AY's port A, the timer, reads 0: the schedule leaves out
the waits), the read of $8000 is the command latch (snd_latch).  The runtime enters at $0038 (a command, TOKEN as the
return address) and at $010C (a tick) and comes back at the loop's head $00FD (the hook snd_hook) or TOKEN.
"""
from pathlib import Path
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from machine import load
from sound import LOOP, TICK, TOKEN
from paths import build_dir, require_coverage

ROM_END = 0x4000


def image():
    rom = load('gyrussk.1a') + load('gyrussk.2a')
    return rom + bytes(0x10000 - len(rom))


class SEmitter(z80x.Emitter):
    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xFFFF
        if io_read and a == 0x8000:
            return 'snd_latch'
        return z80x.Emitter.mem(self, addr, off, io_read)

    def byte_to(self, src, dst):
        """dst = the Z80 register src's value"""
        if src == 'a':
            self.e('move.b d0,%s' % dst)
            return
        reg, hi = self.half(src)
        if hi:
            self.e('move.w %s,%s' % (reg, dst))
            self.e('lsr.w #8,%s' % dst)
        else:
            self.e('move.b %s,%s' % (reg, dst))

    def x_out(self, ins):
        """`out (n),r` inline (the AYs' address and data writes into snd_addr / snd_ay: their address & 15, the data
        marks the YM dirty and the envelope's shape written; the i8039's latch, its IRQ: snd_effect); `out (c),r`
        through snd_out"""
        dst, src = ins.ops
        if src[0] != 'r8':
            raise z80x.Unsupported('out ' + ins.text)
        if dst[0] == 'port':
            n = dst[1] & 0xFF
            k = n >> 2
            val = 'd0' if src[1] == 'a' else 'd5'
            if val == 'd5':
                self.byte_to(src[1], 'd5')
            if n <= 0x12 and n & 3 == 0:
                self.e('moveq #15,d7')
                self.e('and.b %s,d7' % val)
                self.e('move.b d7,snd_addr+%d' % k)
            elif n <= 0x12 and n & 3 == 2:
                skip = self.new_label()
                self.e('moveq #0,d7')
                self.e('move.b snd_addr+%d,d7' % k)
                self.e('lea snd_ay+%d,a0' % (16 * k))
                self.e('move.b %s,(a0,d7.w)' % val)
                self.e('st snd_dirty')
                self.e('cmp.b #13,d7')
                self.e('bne.s %s' % skip)
                self.e('st snd_env+%d' % k)
                self.lines.append(skip + ':')
            elif n == 0x18:
                self.e('move.b %s,snd_latch2' % val)
            elif n == 0x14:
                self.e('addq.w #1,snd_effects')
                self.e('bsr snd_effect')
            else:
                raise z80x.Unsupported('out ' + ins.text)
            return
        if dst != ('ind', 'bc', 0):
            raise z80x.Unsupported('out ' + ins.text)
        self.byte_to('c', 'd7')
        self.byte_to(src[1], 'd5')
        self.e('bsr snd_out')

    def x_call(self, ins):
        """The nine music channels' `call $0281` (0164-01A0, IX static): the callee's head `dec (ix+1); ret nz` in
        place; the flags are dead at every return point (the next `ld ix` / `jp $00FD`, then `and` at 0101), the return
        address only written when the call goes on to $0285"""
        if ins.ops[0] == ('addr', 0x0281) and 0x0164 <= ins.pc <= 0x01A0:
            nxt = ins.pc + ins.length
            self.e('subq.b #1,1(a6,d4.w)')
            self.e('bne X%04X' % nxt)
            self.push_ret(nxt)
            self.jmp_to(0x0285)
            return
        z80x.Emitter.x_call(self, ins)

    JT_SITES = {0x01C2: 0x0BB8, 0x01D6: 0x0C00, 0x00C4: 0x0BB8}   # rst $28 / jp $0028 after `ld hl,nn`: nn

    def table_jump(self, base):
        """The rst $28 table (Pooyan's sndgen): HL = the word at base + 2 (A & $7F), A its low byte, the flags clear
        (the adc a,0 of a table below $7F00), a jump there through snd_jt<base>"""
        self.e('moveq #$7F,d7')
        self.e('and.b d0,d7')
        self.e('lsl.w #3,d7')
        self.e('lea snd_jt%04X,a0' % base)
        self.e('move.w 4(a0,d7.w),d3')
        self.e('move.b d3,d0')
        self.e('clr.b d6')
        self.e('move.l (a0,d7.w),a0')
        self.e('jmp (a0)')

    def x_jp(self, ins):
        if ins.pc in self.JT_SITES and ins.ops[0] == ('addr', 0x0028):
            self.table_jump(self.JT_SITES[ins.pc])
            return
        z80x.Emitter.x_jp(self, ins)

    def x_rst(self, ins):
        """`rst $28` at JT_SITES as a direct table; `rst $08` / `$10` / `$18` / `$20` (the I/O helpers, 3-4
        instructions) emitted in place (inline_leaves)"""
        if ins.pc in self.JT_SITES and ins.ops[0][1] == 0x28:
            self.push_ret(ins.pc + ins.length)
            self.table_jump(self.JT_SITES[ins.pc])
            return
        t = ins.ops[0][1]
        body = self.inline_body(t) if self.transfer is None else None
        if body:
            self.emit_inline(body, ins.pc + ins.length)
            return
        z80x.Emitter.x_rst(self, ins)

    def x_in(self, ins):
        dst, src = ins.ops
        if dst != ('r8', 'a') or src[0] != 'port':
            raise z80x.Unsupported('in ' + ins.text)
        self.e('moveq #%d,d7' % (src[1] & 0xFF))
        self.e('bsr snd_in')
        self.e('move.b d7,d0')                # (in a,(n): no flags)


def coverage():
    """the pcs and computed jumps of ref/cover_sound.py's runs"""
    require_coverage('gyruss', ['cover_sound0.pkl'])
    pcs, jumps = set(), set()
    for f in sorted(build_dir('gyruss').glob('cover_sound*.pkl')):
        d = pickle.loads(f.read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
    return {p for p in pcs if p < ROM_END}, {j for j in jumps if j < ROM_END}


def generate():
    rom = image()
    pcs, jumps = coverage()
    roots = {0, 0x38, LOOP, TICK} | jumps
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    cfg = z80x.Config(prefix='X', table='snd_dispatch', token_sym='snd_token_ret', mode='signed', block=0x10000,
                      iyaddr=0x63F0, fshadow=0x63F2, io_read_redirect={}, write_hooks=[], nmi_token=TOKEN,
                      table_entries=0x10000, rst28_tables=False, bit_s=True, inline_leaves=16,
                      inline_limit=ROM_END, inline_rst=True, inline_jumps=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, {LOOP}, emitter=SEmitter, ijmp_flags=True, flags_at={LOOP})
    out = ['; generated: Gyruss sound Z80 -> 68000 (games/gyruss/tools/sndgen.py)', '\tsection text,code']
    out += [l.replace('z80_hook', 'snd_hook').replace('z80_badpc', 'snd_badpc').replace('z80_rnd', 'snd_badpc')
            for l in em.lines]
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['X%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp snd_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em)
    for site, base in SEmitter.JT_SITES.items():
        prev = [i for i in code.values() if i.pc + i.length == site]
        assert prev and prev[0].text == 'ld hl,$%04X' % base, (hex(site), prev and prev[0].text)
    assert code[0x28].text == 'add a,a'
    labels = {p: 'X%04X' % p for p in code if p not in em.no_entry}
    out.append('\tcnop 0,4')
    for base in sorted(set(SEmitter.JT_SITES.values())):      # snd_jt<base>: 128 entries (A & $7F): label, HL
        out.append('snd_jt%04X:' % base)
        for i in range(128):
            t = rom[base + 2 * i] | rom[base + 2 * i + 1] << 8
            out.append('\tdc.l %s\n\tdc.w $%04X,0' % (labels.get(t, 'snd_badpc'), t))
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed sound instructions cannot be translated: %s' % seen)
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()}}
    return '\n'.join(out) + '\n', report


def dispatch_table(code, em):
    labels = {p: 'X%04X' % p for p in code if p not in em.no_entry}
    labels[TOKEN] = 'snd_token_ret'
    rows, run = ['\tcnop 0,4', 'snd_dispatch_sw:'], 0
    for swapped in range(65536):
        label = labels.get(((swapped & 255) << 8) | (swapped >> 8))
        if label is None:
            run += 1
            continue
        if run:
            rows.append('\tdcb.l %d,snd_badpc' % run)
            run = 0
        rows.append('\tdc.l %s' % label)
    if run:
        rows.append('\tdcb.l %d,snd_badpc' % run)
    return rows


if __name__ == '__main__':
    text, rep = generate()
    print({k: v for k, v in rep.items() if k != 'tables'})
