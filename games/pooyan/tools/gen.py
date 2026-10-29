"""Pooyan: the main Z80 program (32 KB, flat) translated to 68000 code.

    python gen.py   ->  build/pooyan/code_main.s (+ translation.json)

Roots: reset, the NMI, the idle hook $021C and the coverage (build/pooyan/cover<seed>.pkl, ref/cover.py in the port's
schedule).  The runtime delivers the NMI at the hook (machine.PooyanPort): z80_hook (d7 = the pc) returns to go on or
jumps to the NMI with TOKEN as its return address.
Memory-mapped I/O: the static reads of DSW1, IN0-IN2 and DSW0 (at the addresses the coverage saw: IO_IN) read Z80
addresses $B100-$B104 (an unused image of the I/O block), since DSW1's $A000 is also the watchdog's write address;
stores to the I/O are plain stores into the block (the runtime reads the latch byte $A180, NMI enable), and the store
to latch Q1 ($A181, the sound CPU's trigger) calls py_sound.  The stores to the colour and video RAM ($8000-$87FF,
the coverage's write sites) list the cell they hit through py_mark_* routines that keep the flags.
"""
from pathlib import Path
import json
import os
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from paths import build_dir, require_coverage
from machine import PooyanPort, load, ROMS

BUILD = build_dir('pooyan')
HOOKS = [PooyanPort.IDLE]
TOKEN = PooyanPort.TOKEN
SEEDS = [int(x) for x in os.environ.get('PY_SEEDS', '').split(',') if x] or range(1, 13)
ROM_END = 0x8000
PORTS = {0xA000: 0, 0xA080: 1, 0xA0A0: 2, 0xA0C0: 3, 0xA0E0: 4}     # DSW1, IN0, IN1, IN2, DSW0 (without mirrors)
IN_BASE = 0xB100
SOUND_TRIGGER = 0xA181
NO_PV = set()
NATIVES = {}
CONTINUE = set()
INLINE = int(os.environ.get('PY_INLINE', '16'))


def port_of(a):
    """the input port an I/O read address selects (MAME's mirrors), or None"""
    if a < 0xA000:
        return None
    if a & 0xA180 == 0xA000:
        return 0
    if a & 0xA180 == 0xA080:
        return 1 + ((a >> 5) & 3)
    return None


def image():
    rom = b''.join(load(n) for n in ROMS)
    return rom + bytes(0x10000 - len(rom))


def coverage():
    require_coverage('pooyan', ['cover%d.pkl' % s for s in SEEDS])
    pcs, jumps, writes, io = set(), set(), set(), set()
    for s in SEEDS:
        d = pickle.loads((BUILD / ('cover%d.pkl' % s)).read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        writes |= d['writes']
        io |= d['io']
    return pcs, jumps, writes, io


class PEmitter(z80x.Emitter):
    def __init__(self, *a, tile_sites=None, **k):
        super().__init__(*a, **k)
        self.tile_sites = tile_sites or {}

    def x_in(self, ins):
        raise z80x.Unsupported('in ' + ins.text)

    def x_out(self, ins):
        raise z80x.Unsupported('out ' + ins.text)

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        if pc in NO_PV:
            live_out_override = self.live_out[pc] & ~z80x.PV
        super().emit_ins(pc, live_out_override, with_label)
        mark = self.tile_sites.get(pc)
        if mark:
            self.e(mark)                      # (the marks keep the flags)


def tile_marks(code, writes):
    """pc -> the line that marks the cell its store hit (a routine per address register; static stores mark their cell
    directly; block moves mark everything)"""
    out = {}
    for pc in sorted({pc for pc, a in writes if 0x8000 <= a < 0x8800}):
        ins = code.get(pc)
        if ins is None:
            continue
        if ins.mn in ('ldir', 'lddr', 'ldi', 'ldd'):
            out[pc] = 'bsr py_mark_all'
            continue
        dst = (ins.ops[-1] if ins.mn in ('set', 'res') else ins.ops[0]) if ins.ops else None
        if ins.mn in ('push', 'call', 'rst') or dst is None:
            raise RuntimeError('video RAM write by %04X %s' % (pc, ins.text))
        if dst[0] == 'ind16':
            out[pc] = 'pea %d.w\n\tbsr py_mark_n\n\taddq.l #4,a7' % (dst[1] & 0x3ff)
            if ins.mn == 'ld' and ins.ops[1][0] == 'r16':          # (ld (nn),rr: two bytes)
                out[pc] += '\n\tpea %d.w\n\tbsr py_mark_n\n\taddq.l #4,a7' % ((dst[1] + 1) & 0x3ff)
        elif dst[0] == 'ind' and dst[1] in ('hl', 'de', 'bc', 'ix', 'iy') and ins.mn in (
                'ld', 'inc', 'dec', 'set', 'res', 'rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'srl', 'sll', 'rld', 'rrd'):
            if dst[1] in ('ix', 'iy'):
                out[pc] = 'pea %d.w\n\tbsr py_mark_%s\n\taddq.l #4,a7' % (dst[2], dst[1])
            else:
                out[pc] = 'bsr py_mark_%s' % dst[1]
        else:
            raise RuntimeError('video RAM write by %04X %s (form)' % (pc, ins.text))
    return out


def check_io(code, io, writes):
    """the accesses the translation handles; returns IO_IN (each static input read address -> its byte at IN_BASE)"""
    io_in = {}
    for pc, a, rw in sorted(io):
        ins = code.get(pc)
        if ins is None:
            continue
        if rw == 'w' and a < 0x8000:
            raise RuntimeError('store into the ROM at %04X by %04X %s' % (a, pc, ins.text))
        if rw == 'r':
            p = port_of(a)
            if p is None:
                raise RuntimeError('unmapped read of %04X by %04X %s' % (a, pc, ins.text))
            if not (ins.mn == 'ld' and ins.ops[1] == ('ind16', a)):
                raise RuntimeError('I/O read of %04X by %04X %s (not a static load)' % (a, pc, ins.text))
            io_in[a] = IN_BASE + p
        elif a == SOUND_TRIGGER and not (ins.mn == 'ld' and ins.ops == [('ind16', a), ('r8', 'a')]):
            raise RuntimeError('sound trigger by %04X %s' % (pc, ins.text))
        elif a != SOUND_TRIGGER and a & 0xA180 == 0xA180 and a & 0xFFF8 != 0xA180:
            raise RuntimeError('latch store at the mirror %04X by %04X %s' % (a, pc, ins.text))
    for pc, a in sorted(writes):
        if 0x9000 <= a < 0xA000 and a != 0x9000 | (a & 0x4FF):
            raise RuntimeError('sprite RAM store at the mirror %04X by %04X' % (a, pc))
    return io_in


def generate():
    rom = image()
    pcs, jumps, writes, io = coverage()
    pcs = {p for p in pcs if p < ROM_END}
    known = set(pcs)
    roots = {0, 0x66} | set(HOOKS) | {j for j in jumps if j < ROM_END}
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | known), known=known, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    io_in = check_io(code, io, writes)
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0x10000, iyaddr=0xB1F0, fshadow=0xB1F2, iaddr=0xB1F4,
                      io_read_redirect=io_in, write_hooks=[(SOUND_TRIGGER, SOUND_TRIGGER, 'py_sound', None)],
                      nmi_token=TOKEN, token_sym='z80_nmi_ret', rst28_tables=False, hl_tables=True, bit_s=False,
                      inline_leaves=INLINE, inline_limit=ROM_END, inline_rst=True, inline_jumps=True, **z80x.FAST)
    joins = set(roots) | CONTINUE
    for nxt, targets in tables.values():
        joins |= set(targets)
    marks = tile_marks(code, writes)
    em = compile_code(code, joins, cfg, set(HOOKS), emitter=PEmitter, ijmp_flags=True, flags_at=set(HOOKS),
                      tile_sites=marks, natives=NATIVES)
    seen = [u for u in em.unsupported if u[0] in known]
    if seen:
        raise RuntimeError('observed instructions cannot be translated: %s' % seen)
    out = ['; generated: Pooyan main Z80 -> 68000 (games/pooyan/tools/gen.py)', '\tsection text,code']
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['Z%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp z80_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em)
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()},
              'tile_sites': len(marks), 'jumps': len(jumps), 'coverage': len(pcs),
              'io_in': {'%04X' % k: '%04X' % v for k, v in sorted(io_in.items())}, 'io': sorted(io)}
    return '\n'.join(out) + '\n', report, code


def dispatch_table(code, em):
    """a long per Z80 address in byte-swapped order (the word a ret reads from the Z80 stack): the translated label,
    z80_nmi_ret for TOKEN, else z80_badpc (Gyruss's layout)"""
    labels = {p: 'Z%04X' % p for p in code if p not in em.no_entry}
    labels[TOKEN] = 'z80_nmi_ret'
    rows, run = ['\tcnop 0,4', 'z80_dispatch_sw:'], 0
    for swapped in range(65536):
        label = labels.get(((swapped & 255) << 8) | (swapped >> 8))
        if label is None:
            run += 1
            continue
        if run:
            rows.append('\tdcb.l %d,z80_badpc' % run)
            run = 0
        rows.append('\tdc.l %s' % label)
    if run:
        rows.append('\tdcb.l %d,z80_badpc' % run)
    return rows


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_main.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print({k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')}, len(report['unsupported']),
          'unsupported')
