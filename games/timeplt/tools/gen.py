"""Time Pilot: the main Z80 program (24 KB, flat) translated to 68000 code.

    python gen.py   ->  build/timeplt/code_main.s (+ translation.json)

Roots: reset, the NMI, the idle hook $0B93, the coverage (build/timeplt/cover<seed>.pkl, ref/cover.py in the port's
schedule) and F030Arcade's executed pcs (docs/f030-roots.json: its reference and Go-Explore runs).  The runtime
(src/timeplt.s) delivers the NMI at the hook (machine.TimepltPort): z80_hook (d7 = the pc) returns to go on or jumps
to the NMI with TOKEN as its return address.
Memory-mapped I/O: the static reads $C000 (the beam: the runtime keeps 255 there), $C200 DSW1, $C300 IN0, $C320 IN1,
$C340 IN2, $C360 DSW0 read Z80 addresses $7F00-$7F05 (the empty diagnostics socket; IO_IN); stores to $C000-$C3FF are
plain stores into the block (the runtime reads the latch bytes $C300 (NMI enable) and $C308 (video enable)), and
`ld ($C304),a` (the sound CPU's trigger) calls tp_sound.  The stores to the video RAM ($A000-$A7FF, the coverage's
write sites) list the cell they hit (cell_dirty, cell_list) through tp_mark_* routines that keep the flags.  The 16 cloud
clears (machine.CLOUD_CLEAR) first call cloud_save_<slot> (the old content of a reused cloud for the picture).
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
from paths import build_dir, require_coverage, game_dir
from machine import TimepltPort, CLOUD_CLEAR, load

BUILD = build_dir('timeplt')
HOOKS = [TimepltPort.IDLE]
TOKEN = TimepltPort.TOKEN
SEEDS = [int(x) for x in os.environ.get('TP_SEEDS', '').split(',') if x] or range(1, 13)
ROM_END = 0x6000
IO_IN = {0xC000: 0x7F00, 0xC200: 0x7F01, 0xC300: 0x7F02, 0xC320: 0x7F03, 0xC340: 0x7F04, 0xC360: 0x7F05}
SOUND_TRIGGER = 0xC304
# the ROM checksum's `add a,c` ($0EE2): its P/V reaches only `ret po` at $2509, the data the failed check jumps into
# (an anti-tamper crash the unmodified ROM never takes)
NO_PV = {0x0EE2}
# hand-written 68000 routines (src/timeplt.s) that replace the code from these pcs on: the cloud routine $0F97-$1198
# with the beam at 255 (the waits end at once; machine.TimepltPort): A, C, the RAM, the captures and the flags as the
# Z80 leaves them (only C is read after its ret)
NATIVES = {0x0F97: 'nat_clouds',
           # ROM checksums folded into the random byte $A9AB (a = ([$A9AB] - the sum of 256 ROM bytes) ^ k): the sums
           # are constants (CK_*); the natives continue in the translation at the next instruction (CONTINUE: joins)
           0x5694: 'nat_ck5694', 0x16AF: 'nat_ck16af', 0x56BD: 'nat_ck56bd'}
CONTINUE = {0x56A6, 0x16C0, 0x0F1A}
CHECKSUMS = {'CK_5694': 0x0831, 'CK_16AF': 0x4D9F, 'CK_56BD': 0x12A7}
# calls of leaf functions of up to this many instructions are emitted in place, rst helpers and inner jumps too
INLINE = int(os.environ.get('TP_INLINE', '16'))


def image():
    rom = b''.join(load(n) for n in ('tm1', 'tm2', 'tm3'))
    return rom + bytes(0x10000 - len(rom))


def coverage():
    require_coverage('timeplt', ['cover%d.pkl' % s for s in SEEDS])
    pcs, jumps, writes, io = set(), set(), set(), set()
    for s in SEEDS:
        d = pickle.loads((BUILD / ('cover%d.pkl' % s)).read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        writes |= d['writes']
        io |= d['io']
    f030 = json.loads((game_dir('timeplt') / 'docs' / 'f030-roots.json').read_text())['roots']
    return pcs, set(f030), jumps, writes, io


class TEmitter(z80x.Emitter):
    def __init__(self, *a, tile_sites=None, **k):
        super().__init__(*a, **k)
        self.tile_sites = tile_sites or {}

    def x_in(self, ins):
        raise z80x.Unsupported('in ' + ins.text)

    def x_out(self, ins):
        raise z80x.Unsupported('out ' + ins.text)

    def x_ld(self, ins):
        if ins.pc in CLOUD_CLEAR:
            assert tuple(ins.ops) == (('ind16', 0xB401 + CLOUD_CLEAR[ins.pc]), ('r8', 'a')), ins
            self.e('bsr cloud_save_%02x' % CLOUD_CLEAR[ins.pc])
        super().x_ld(ins)

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        if pc in NO_PV:
            live_out_override = self.live_out[pc] & ~z80x.PV
        super().emit_ins(pc, live_out_override, with_label)
        mark = self.tile_sites.get(pc)
        if mark:
            self.e(mark)                      # (the marks keep the flags)


def tile_marks(code, writes):
    """pc -> the line that marks the video RAM row its store hit (a routine per address register; static stores mark
    their row directly; block moves mark every row)"""
    out = {}
    for pc in sorted({pc for pc, a in writes if 0xA000 <= a < 0xA800}):
        ins = code.get(pc)
        if ins is None:
            continue
        if ins.mn in ('ldir', 'lddr', 'ldi', 'ldd'):
            out[pc] = 'bsr tp_mark_all'
            continue
        dst = (ins.ops[-1] if ins.mn in ('set', 'res') else ins.ops[0]) if ins.ops else None
        if ins.mn in ('push', 'call', 'rst') or dst is None:
            raise RuntimeError('video RAM write by %04X %s' % (pc, ins.text))
        if dst[0] == 'ind16':
            out[pc] = 'pea %d.w\n\tbsr tp_mark_n\n\taddq.l #4,a7' % (dst[1] & 0x3ff)
            if ins.mn == 'ld' and ins.ops[1][0] == 'r16':          # (ld (nn),rr: two bytes)
                out[pc] += '\n\tpea %d.w\n\tbsr tp_mark_n\n\taddq.l #4,a7' % ((dst[1] + 1) & 0x3ff)
        elif dst[0] == 'ind' and dst[1] in ('hl', 'de', 'bc', 'ix', 'iy') and ins.mn in (
                'ld', 'inc', 'dec', 'set', 'res', 'rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'srl', 'sll', 'rld', 'rrd'):
            if dst[1] in ('ix', 'iy'):
                out[pc] = 'pea %d.w\n\tbsr tp_mark_%s\n\taddq.l #4,a7' % (dst[2], dst[1])
            else:
                out[pc] = 'bsr tp_mark_%s' % dst[1]
        else:
            raise RuntimeError('video RAM write by %04X %s (form)' % (pc, ins.text))
    return out


def check_io(code, io, writes):
    """the accesses the translation handles: static reads of the ports, `ld ($C304),a`, sprite RAM stores without the
    mirrors (the renderer reads $B000-$B0FF / $B400-$B4FF), nothing at the unmapped addresses"""
    for pc, a, rw in sorted(io):
        ins = code.get(pc)
        if ins is None:
            continue
        if (pc, a) in ((0x07B1, 0x6000), (0x07C4, SOUND_TRIGGER)):
            continue                          # (the reset's look for a diagnostics ROM: not $55 either way; the latch
                                              # cleared with ld (hl),0 at boot: no trigger)
        if not 0xC000 <= a < 0xD000:
            raise RuntimeError('unmapped %s of %04X by %04X %s' % (rw, a, pc, ins.text))
        if rw == 'r':
            if not (ins.mn == 'ld' and ins.ops[1] == ('ind16', a) and a in IO_IN):
                raise RuntimeError('I/O read of %04X by %04X %s' % (a, pc, ins.text))
        elif a == SOUND_TRIGGER and not (ins.mn == 'ld' and ins.ops == [('ind16', a), ('r8', 'a')]):
            raise RuntimeError('sound trigger by %04X %s' % (pc, ins.text))
    for pc, a in sorted(writes):
        if 0xB000 <= a < 0xC000 and a != 0xB000 | (a & 0x4FF):
            raise RuntimeError('sprite RAM store at the mirror %04X by %04X' % (a, pc))


def generate():
    rom = image()
    pcs, f030, jumps, writes, io = coverage()
    pcs = {p for p in pcs if p < ROM_END}
    known = pcs | {p for p in f030 if p < ROM_END}
    roots = {0, 0x66} | set(HOOKS) | {j for j in jumps if j < ROM_END}
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | known), known=known, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    check_io(code, io, writes)
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0x10000, iyaddr=0x7FF0, fshadow=0x7FF2,
                      io_read_redirect=IO_IN, write_hooks=[(SOUND_TRIGGER, SOUND_TRIGGER, 'tp_sound', None)],
                      nmi_token=TOKEN, token_sym='z80_nmi_ret', rst28_tables=False, hl_tables=True, bit_s=False,
                      inline_leaves=INLINE, inline_limit=ROM_END, inline_rst=True, inline_jumps=True, **z80x.FAST)
    joins = set(roots) | CONTINUE
    for nxt, targets in tables.values():
        joins |= set(targets)
    marks = tile_marks(code, writes)
    em = compile_code(code, joins, cfg, set(HOOKS), emitter=TEmitter, ijmp_flags=True, flags_at=set(HOOKS),
                      tile_sites=marks, natives=NATIVES)
    seen = [u for u in em.unsupported if u[0] in known]
    if seen:
        raise RuntimeError('observed instructions cannot be translated: %s' % seen)
    out = ['; generated: Time Pilot main Z80 -> 68000 (games/timeplt/tools/gen.py)', '\tsection text,code']
    out += ['%s = $%02X' % (k, sum(rom[a:a + 256]) & 255) for k, a in CHECKSUMS.items()]
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['Z%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp z80_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em)
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()},
              'tile_sites': len(marks), 'jumps': len(jumps), 'coverage': len(pcs),
              'f030_only': len(known - pcs), 'io': sorted(io)}
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
