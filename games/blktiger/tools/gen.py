"""Bank-aware whole-program Black Tiger Z80 -> 68000 translation."""
from pathlib import Path
import os
import sys
import pickle
import json
import re
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x, z80dis, discover
from z80x import Emitter, compute_liveness, Unsupported, hx, swap16
from translate import compile_code
from machine import load
from paths import build_dir

WIN_LO, WIN_HI, VBASE = 0x8000, 0xc000, 0x10000
IDLE = 0x00d4
BUILD = build_dir('blktiger')


# The background RAM (c000-cfff, out $0d selects one of four 4 KB banks) is not in the Z80 image: every indirect
# access checks for it (win_check: with the window's check, at no cost to other addresses) and goes to the bank in
# g_bg, a write noting its map entry for the renderer (bg_note); a block instruction whose ranges meet it runs on a copy of the
# bank in the image (bt_bg_fwd / bt_bg_bwd, bt_bg_post).  A bank switch is a pointer (g_bgbase).
# The same for the palette RAM (d800-dfff, the fades): pal_dirty.
PAL_WRITERS = {0x1951, 0x1959, 0x1965, 0x196d, 0x19a5, 0x19bd, ('bank', 6, 0x809d), ('bank', 6, 0xb944),
               ('bank', 6, 0xb951), ('bank', 6, 0xbaa1), ('bank', 6, 0xbaac), ('bank', 6, 0xbab8),
               ('bank', 6, 0xbac3), ('bank', 6, 0xbacf), ('bank', 6, 0xbada),
               ('bank', 6, 0xba8a), ('bank', 6, 0xba95), ('bank', 6, 0xbae6), ('bank', 6, 0xbaf1),
               # (2026-10-12: the intro story's palette copies, and every other block copy to the palette)
               0x7bb5, 0x7bbd, 0x7bcb, 0x7bd3, 0x7be1, 0x7be9, 0x7bf7, 0x7bff, 0x7c0d, 0x7c15, 0x7c23, 0x7c2b}

# The instructions that write the text RAM (d000-d7ff), from the reference with cover.py's three input schedules
# (random play, --walk, --auto; 8000 frames each) and every stage with cheats (cover.py seeds 4-11): a store marks its text row in
# text_rows_dirty (rows 0-31 the codes, 32-63 the attributes), a block copy sets text_compare.  The renderer then
# rebuilds only those rows (and compares one row a frame in case a writer is missing here).
TEXT_WRITERS = {0x055e, 0x0561, 0x0568, 0x056c, 0x057c, 0x057f, 0x058c, 0x058f, 0x059c, 0x05a1, 0x08ee, 0x08f0,
                0x08fb, 0x08fd, 0x0b6e, 0x0b70, 0x0b7b, 0x0b7d, 0x0bd2, 0x0bd7, 0x0c5a, 0x0c5d, 0x1179, 0x117b,
                0x1186, 0x1188, 0x12ac, 0x12ae, 0x12d7, 0x12d9, 0x12e4, 0x12e6, 0x13ac, 0x1443, 0x1446, 0x1466,
                0x1475, 0x1477, 0x1482, 0x1484, 0x23a5, 0x23a8, 0x23b0, 0x2630, 0x2632, 0x263d, 0x263f, 0x2648,
                0x264b, 0x265d, 0x2b5b, 0x2b5e, 0x2b63, 0x2b67, 0x2b7a, 0x2b7d, 0x5020, 0x5023, 0x5033, 0x5036,
                0x503d, 0x5040, 0x504a, 0x504d, 0x5054, 0x5057, 0x6011, 0x6013, 0x601e, 0x6020, 0x60d3, 0x60d5,
                0x60e0, 0x60e2, 0x6406, 0x6408, 0x64c6, 0x64cb, 0x650a, 0x650c, 0x6517, 0x6519, 0x6524, 0x6526,
                0x6917, 0x691a, 0x6921, 0x6924, 0x6962, 0x6965, 0x6990, 0x6992, 0x699d, 0x699f, 0x69aa, 0x69ac,
                0x69b7, 0x69b9, 0x69d8, 0x69db, ('bank', 6, 0xb91f), ('bank', 6, 0xb921), ('bank', 6, 0xbaff), ('bank', 6, 0xbb02), ('bank', 6, 0xbb1d), ('bank', 6, 0xbb21), ('bank', 6, 0xba18), ('bank', 6, 0xba1b), ('bank', 7, 0x908c),
                ('bank', 7, 0x908f), ('bank', 7, 0x909d), ('bank', 7, 0x90a0)}


def virt(pc, bank):
    return VBASE + bank*0x4000 + pc-WIN_LO


SCRIPT_ENTRIES = {0x3006, 0x32e6, 0x366b, 0x3dab, virt(0xa1d1, 7)}   # (the animation script interpreters)


def real(pc):
    return WIN_LO + ((pc-VBASE) & 0x3fff) if pc >= VBASE else pc


def _pcs(writers):
    return {virt(w[2], w[1]) if isinstance(w, tuple) else w for w in writers}


TEXT_PCS = _pcs(TEXT_WRITERS)
DIRTY_FLAGS = {pc: 'pal_dirty' for pc in _pcs(PAL_WRITERS)}
RMW = {'inc', 'dec', 'set', 'res', 'rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'srl', 'sll', 'rld', 'rrd'}


def image():
    fixed = load('bdu-01a.5e')
    banks = b''.join(load(n) for n in ('bdu-02a.6e','bdu-03a.8e','bd-04.9e','bd-05.10e'))
    return fixed + bytes([0x76])*0x8000 + banks


def decode(rom, pc):
    ins = z80dis.decode(rom, pc)
    if pc < VBASE:
        return ins
    base = (pc-VBASE)//0x4000
    def fix(o):
        if o[0] != 'addr':
            return o
        if ins.mn in ('jr','djnz'):
            # Relative targets wrap at the Z80's 64 KB boundary, not the virtual bank boundary.
            delta = ((o[1] - ((pc+ins.length) & 0xffff) + 0x8000) & 0xffff) - 0x8000
            target = (real(pc)+ins.length+delta) & 0xffff
        else:
            target = o[1]
        return ('addr', virt(target, base) if WIN_LO <= target < WIN_HI else target)
    ops = [fix(o) for o in ins.ops]
    target = next((o[1] for o in ops if o[0]=='addr'), ins.target)
    return ins._replace(ops=ops, target=target)


class BTEmitter(Emitter):
    """The main CPU: banked window, stubs, window reads.

    The translator keeps A' BC' DE' HL' in a3 a0 a1 a2, so no address register is free for the
    window: accesses to it use the marker register `aW` in the lines of an instruction, and
    emit_ins turns that into  pea (a0) / move.l g_winbase,a0 ... move.l (sp)+,a0  around the
    instruction (flag neutral: pea and movea leave the CCR alone).  g_winbase = the current
    bank's copy + $8000 (the Z80 address - $10000 is the offset)."""

    def __init__(self, *a, window_sites=(), **k):
        super().__init__(*a, **k)
        self.window_sites = set(window_sites)
        self.stubs = set()

    def x_ld_i_a(self, ins):                  # the interrupt vector page (the program checks it)
        self.e("move.b d0,g_ireg")

    def x_ld_a_i(self, ins):
        self.e("move.b g_ireg,d0")
        self.e("tst.b d0")
        self.flags(z80x.S | z80x.Z, const_clear=z80x.H | z80x.N)

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:             # a window address from fixed code: the bank decides
            self.stubs.add(pc)
            return "BK%04X" % pc
        return super().label_of(pc)

    def ret_value(self, pc):                  # (a call pushes the real address)
        return real(pc)

    def direct_ok(self, rp):                  # (a return point in the window: which bank it is in, the ret cannot tell)
        return rp in self.code and real(rp) == rp

    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xFFFF
        if WIN_LO <= a < WIN_HI:
            return "%d(aW)" % (a - 0x10000)
        return super().mem(addr, off, io_read)

    win_src = None

    def ind(self, reg, disp=0):
        if self.win_src == reg:              # a block instruction reading the window
            return "%d(aW,%s.w)" % (disp, reg) if disp else "(aW,%s.w)" % reg
        return super().ind(reg, disp)

    def win_check(self, reg, disp=0, store=False, window=True):
        """lines: aW = the base for the Z80 address reg + disp: a6, the window's (8000-BFFF) or the background bank's
        (C000-CFFF; a write there is noted for the renderer: bg_note).  Signed words: 8000-BFFF is below -$4000, C000-CFFF below -$3000;
        the displacement goes into the constants (the 68000 adds it to the sign-extended register).  A store to the
        window (ROM) goes to a6's unused copy of it, as the Z80's goes nowhere.  window=False: the old check of
        a block instruction's source (the background is in the image then)."""
        l = self.new_label()
        if not window:
            return ["lea (a6),aW", "cmp.w #$C000,%s" % reg, "bge.s %s" % l, "move.l g_winbase,aW", l + ":"]
        k = lambda v: "#$%04X" % ((v - disp) & 0xFFFF)
        lines = ["lea (a6),aW", "cmp.w %s,%s" % (k(0xD000 - 0x10000), reg), "bge.s %s" % l]
        if not store:
            lines.append("move.l g_winbase,aW")
        lines += ["cmp.w %s,%s" % (k(0xC000 - 0x10000), reg), "blt.s %s" % l, "move.l g_bgbase,aW"]
        if store or self.cur.mn in RMW:        # (the map entry written, for the renderer)
            lines += ["lea %d(aW,%s.w),a1" % (disp, reg), "jsr bg_note"]
        return lines + [l + ":"]

    def block_win(self, fn, ins, backward=False):
        """a block instruction: the background bank into the image while it runs, if its ranges meet C000-CFFF;
        at a site that read the window, aW = the base of the source (hl)"""
        if ins.mn in ('ldi', 'ldd', 'cpi'):
            self.e('moveq #0,d5')               # (the count - 1)
        else:
            self.e('move.w d1,d5')
            self.e('ror.w #8,d5')
            self.e('subq.w #1,d5')              # (BC = 0: 65536)
        self.e('jsr bt_bg_bwd' if backward else 'jsr bt_bg_fwd')
        if ins.pc in self.window_sites:
            for line in self.win_check("d3", window=False):
                self.lines.append(line) if line.endswith(":") else self.e(line)
            self.win_src = "d3"
        try:
            fn(ins)
        finally:
            self.win_src = None
        self.e('jsr bt_bg_post')                # (keeps the CCR)

    def x_ldir(self, ins): self.block_win(super().x_ldir, ins)     # (z80x: on address registers, by longs where it can)
    def x_ldi(self, ins): self.block_win(super().x_ldi, ins)
    def x_ldd(self, ins): self.block_win(super().x_ldd, ins, True)
    def x_lddr(self, ins): self.block_win(super().x_lddr, ins, True)
    def x_cpi(self, ins): self.block_win(super().x_cpi, ins)
    def x_cpir(self, ins): self.block_win(super().x_cpir, ins)

    storing = False

    def write8(self, op, src_ea):             # (z80x's write8 takes its address from read8: a store is not guarded)
        self.storing = True
        try:
            return super().write8(op, src_ea)
        finally:
            self.storing = False

    def read8(self, op, io_read=True):
        pre, ea = Emitter.read8(self, op, io_read)
        if op[0] == 'ind' and self.cur is not None and self.cur.pc in self.window_sites:
            match = re.fullmatch(r'(-?\d+)?\(a6,(d\d|a2)\.w\)', ea)
            if not match:
                raise Unsupported('indirect access %s' % ea)
            reg = match[2]
            if reg == 'a2':                 # (IY with z80x.FAST: the low word of a2, whose upper word is not 0)
                pre += ['move.w a2,d5']
                reg = 'd5'
            pre += self.win_check(reg, int(match[1] or 0), store=self.storing)
            ea = f'{match[1] or ""}(aW,{reg}.w)'
        return pre, ea

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        n0 = len(self.lines)
        super().emit_ins(pc, live_out_override, with_label)
        if pc in DIRTY_FLAGS and self.code[pc].mn == 'ldir':
            # (a block copy to the palette: pal_note takes its range from DE and BC before it runs, after the labels)
            i = n0
            while i < len(self.lines) and re.match(r'^[A-Za-z]+[0-9A-F]{4,5}(_r)?:', self.lines[i]):
                i += 1
            self.lines.insert(i, '\tjsr pal_note')
        self.window_wrap(n0)                  # (z80x: a0 = the window, saved only where it holds BC')
        if pc in DIRTY_FLAGS and self.code[pc].mn != 'ldir':
            self.e('st %s' % DIRTY_FLAGS[pc])  # (Scc leaves the flags alone)
        if pc in TEXT_PCS:
            self.text_mark(self.code[pc])

    def text_mark(self, ins):
        """after a text RAM store: its row marked (the CCR kept: the flag analysis may leave flags live in it)"""
        if ins.mn in ('ldir', 'lddr', 'ldi', 'ldd'):
            self.e('st text_compare')
            return
        dst = ins.ops[0]
        if dst[0] != 'ind' or dst[1] not in ('hl', 'ix'):
            raise Unsupported('text writer %r' % (dst,))
        assert 'a0' in self.free_aregs()
        self.e('move sr,d5')
        self.e('move.w %s,d7' % ('d3' if dst[1] == 'hl' else 'd4'))
        if dst[2]:
            self.e('add.w #%d,d7' % dst[2])
        self.e('lsr.w #5,d7')
        self.e('and.w #63,d7')                 # (d000 >> 5 = $680: the row of the codes / attributes)
        self.e('lea text_rows_dirty,a0')
        self.e('st (a0,d7.w)')
        self.e('move d5,ccr')


    def mem(self, addr, off=0, io_read=False):
        if addr >= 0x10000:
            return 'g_iy' if addr == 0x10000 and off == 0 else 'g_fshadow'
        a = (addr + off) & 0xffff
        if WIN_LO <= a < WIN_HI:
            return f'{a-0x10000}(aW)'
        if 0xc000 <= a < 0xd000:              # (the program has none: the banked background would need g_bgbase)
            raise Unsupported(f'static background address {a:04x}')
        return Emitter.mem(self, addr, off, io_read)

    def dispatch_d7(self):
        self.e('ror.w #8,d7')
        self.e('jmp bt_dispatch')

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:
            self.stubs.add(pc)
            return f'BK{pc:04X}'
        return Emitter.label_of(self, pc)

    def x_in(self, ins):
        dst, port = ins.ops
        if dst != ('r8','a') or port[0] != 'port':
            raise Unsupported('non-immediate input port')
        p = port[1] & 255
        if p < 6:
            self.e(f'move.b bt_inputs+{p},d0')
        elif p == 7:
            self.e('move.b g_mcu_response,d0')
        else:
            self.e('move.b #$ff,d0')

    def x_out(self, ins):
        port, src = ins.ops
        if port[0] != 'port' or src != ('r8','a'):
            raise Unsupported('non-immediate output port')
        self.e(f'jsr bt_out_{port[1]&255:02x}')
        if port[1] == 1 and ins.pc >= VBASE:
            self.e(f'move.w #${real(ins.pc+ins.length):04x},d7')
            self.e('jmp bt_dispatch')


def generate(extra_roots=()):
    rom = image()
    pcs = {virt(pc, bank) if bank >= 0 else pc for bank,pc in json.loads((Path(__file__).resolve().parents[1]/"docs"/"translation-roots.json").read_text())}
    wread, bg_sites = set(), False      # (bg_sites: coverage files that record the background bank's sites too)
    covers = list(BUILD.glob('cover*.pkl'))
    for path in covers:
        with path.open('rb') as f:
            d = pickle.load(f)
        for bank, pc in d['pcs']:
            pcs.add(virt(pc, bank) if bank >= 0 else pc)
        for bank, pc in set(d.get('wread', ())) | set(d.get('wwrite', ())):
            wread.add(virt(pc, bank) if bank >= 0 else pc)
        bg_sites |= d.get('bg_sites', False)
    roots = {0, 0x38, 0x66, IDLE, *extra_roots}
    saved = discover.decode
    discover.decode = decode
    skip_cache = {}
    try:
        while True:
            code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False)
            # Object allocators return normally on failure, but use $03c5 to
            # skip the caller's three-byte JP on success. Discover both paths.
            continuations = {pc+6 for pc,ins in code.items()
                             if ins.mn == 'call' and ins.target is not None
                             and 0x412 <= ins.target < 0x550
                             and rom[pc+3] == 0xc3}
            # $0408 dispatches A through a little-endian HL table. Tables
            # end at the earliest following handler, or the first pointer
            # outside their fixed/banked code region.
            for pc,ins in code.items():
                if ins.mn != 'ld' or ins.ops[0] != ('r16','hl') or ins.ops[1][0] != 'imm':
                    continue
                nxt = code.get(pc+ins.length)
                if not nxt or nxt.mn not in ('jp','call') or nxt.target != 0x408:
                    continue
                table = ins.ops[1][1]
                bank = (pc-VBASE)//0x4000 if pc >= VBASE else -1
                window = WIN_LO <= table < WIN_HI
                if window and bank < 0:
                    raise RuntimeError('Fixed dispatcher needs explicit bank roots')
                address = virt(table,bank) if window else table
                boundary = table+256
                for offset in range(0,256,2):
                    if table+offset >= boundary:
                        break
                    target = int.from_bytes(rom[address+offset:address+offset+2],'little')
                    if not (WIN_LO <= target < WIN_HI if window else 0x100 <= target < WIN_LO):
                        break
                    if target > table:
                        boundary = min(boundary,target)
                    continuations.add(virt(target,bank) if window else target)
            # Animation scripts contain five-byte frames, $00 + code pointer,
            # and $ff + script pointer. A code record can resume at its
            # following record, so discover the complete chain.  Scripts go
            # to one of the interpreters (the same code at each of
            # SCRIPT_ENTRIES: ld (ix+30),l / ld (ix+31),h / ld a,(hl) ...),
            # or HL is stored to ix+30/31 for later.
            def script(cursor, bank):
                visited=set()
                for _ in range(256):
                    if cursor in visited or not WIN_LO <= cursor < WIN_HI or bank < 0:
                        break
                    visited.add(cursor)
                    addr=virt(cursor,bank)
                    tag=rom[addr]
                    if tag == 0xfe:
                        break
                    if tag in (0,0xff):
                        target=int.from_bytes(rom[addr+1:addr+3],'little')
                        if not WIN_LO <= target < WIN_HI:
                            break
                        if tag == 0xff:
                            cursor=target
                            continue
                        continuations.add(virt(target,bank))
                        cursor+=3
                    elif tag < 128:
                        cursor+=5
                    else:
                        break
            for pc,ins in code.items():
                if ins.mn != 'ld' or ins.ops[0] != ('r16','hl') or ins.ops[1][0] != 'imm':
                    continue
                nxt=code.get(pc+ins.length)
                bank=(pc-VBASE)//0x4000 if pc >= VBASE else -1
                if nxt and (nxt.mn in ('jp','call') and nxt.target in SCRIPT_ENTRIES
                            or nxt.mn == 'ld' and list(nxt.ops) == [('ind','ix',30),('r8','l')]):
                    script(ins.ops[1][1], bank)
            # Functions that return past the caller's next bytes (pop hl; inc hl ...; jp (hl)): the compares of
            # 8 / 4 bytes at 03B2 return to the call + 2 / + 4 (a jr each) when equal / greater (2026-10-10: 15 of
            # these continuations were untranslated).
            continuations |= discover.skip_returns(rom, code, lambda pc: pc < 0x8000 or pc >= VBASE, skip_cache)
            missing = continuations - set(code)
            if not missing:
                break
            roots.update(missing)
    finally:
        discover.decode = saved
    code = {pc: ins for pc, ins in code.items() if pc < 0x8000 or pc >= VBASE}
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0xc000,
                      iyaddr=0x10000, fshadow=0x10002, io_read_redirect={}, write_hooks=[],
                      rst28_tables=False, bit_s=True, **z80x.FAST)
    # The indirect accesses guarded (the window, the background bank): with the coverage's access sites (cover.py:
    # the instructions seen reading 8000-CFFF or writing C000-CFFF, all stages with cheats), those and the known
    # writers only, the rest are plain reads of the image; without them (or with old coverage files) every one.
    # logic_test.py --audit finds sites the coverage missed on Musashi runs (bt_wsites_audit_*.pkl).
    # The sites are kept in docs/window-sites.json (a fresh build needs no coverage files); coverage files that have
    # them (and audit files) write it again.
    indirect = {pc for pc, ins in code.items() if any(o[0]=='ind' for o in ins.ops) or ins.mn in ('ldir','lddr','ldi','ldd','cpi','cpir')}
    sites_file = Path(__file__).resolve().parents[1] / 'docs' / 'window-sites.json'
    if os.environ.get('BT_GUARD_ALL'):
        sites = indirect
    elif covers and bg_sites:
        sites = indirect & wread
        for f in BUILD.glob('bt_wsites_audit_*.pkl'):
            with f.open('rb') as h:
                sites |= indirect & set(pickle.load(h))
        sites_file.write_text(json.dumps(sorted(sites)) + '\n')
    elif sites_file.exists():
        sites = indirect & set(json.loads(sites_file.read_text()))
    else:
        sites = indirect
    joins = set(roots)                        # (compile_code adds the return points and the code addresses held as numbers)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, {IDLE}, emitter=BTEmitter, ijmp_flags=True, flags_at={IDLE}, window_sites=sites)
    out = ['; Generated Black Tiger main Z80, fixed and sixteen ROM banks', '\tsection text,code', *em.lines]
    for pc in sorted(em.refs-set(code)):
        out += [f'Z{pc:04X}:', f'\tmove.w #${real(pc):04x},d7', '\tjmp z80_badpc']
    for pc in sorted(em.stubs):
        # (a jump into the window from fixed code: the bank's table directly, g_wdispatch is its middle)
        out += [f'BK{pc:04X}:', f'\tmove.w #${pc:04x},d7', '\tmove.w d7,g_dispatch_pc', '\tmove.l g_wdispatch,a0',
                f'\tmove.l {(pc - 0x8000) * 4 - 0x8000}(a0),a0', '\tjmp (a0)']
    # The entries are read once (init_dispatch): a macro the runtime puts last in the data section, where the ring
    # buffers begin (src/blktiger.s: their memory is the rings' afterwards).
    out += ['bt_entries_data macro', 'bt_entries_fixed:']
    for pc in sorted(code):
        if pc < WIN_LO and pc not in em.no_entry:   # (merged: z80_badpc)
            out += [f'\tdc.w ${pc:04x}', f'\tdc.l Z{pc:04X}']
    out += ['\tdc.w $ffff']
    for bank in range(16):
        out += [f'bt_entries_bank{bank}:']
        for pc in sorted(code):
            if VBASE+bank*0x4000 <= pc < VBASE+(bank+1)*0x4000 and pc not in em.no_entry:
                out += [f'\tdc.w ${real(pc)-WIN_LO:04x}', f'\tdc.l Z{pc:04X}']
        out += ['\tdc.w $ffff']
    out += ['\tendm', '\tsection data,data', '\teven',
            'bt_entry_banks:', '\tdc.l '+','.join(f'bt_entries_bank{b}' for b in range(16))]
    report = {'instructions':len(code), 'unsupported':em.unsupported, 'window_sites':len(sites), 'indirect':len(indirect),
              'banks': sorted({(pc-VBASE)//0x4000 for pc in code if pc>=VBASE})}
    banks = report['banks']
    out += ['bt_dispatch_targets:', '\tdc.l '+','.join(f'bt_window_dispatch{b}+$8000' if b in banks else 'bt_invalid_dispatch+$8000' for b in range(16)),
            f'BT_WINDOW_TABLES = {len(banks)+1}', '\tsection bss,bss', 'bt_invalid_dispatch: ds.l 16384']
    for bank in banks:
        out += [f'bt_window_dispatch{bank}: ds.l 16384']
    out += ['\tsection text,code']
    return '\n'.join(out)+'\n', report, code


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_blktiger.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report)
