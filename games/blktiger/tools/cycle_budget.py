"""The Z80 cycle budget of the Black Tiger translation (build.py --cycles: BT_CYCLES=1, -D CYCLES=1).

From F030Arcade (games/blktiger/scripts/cycle_budget.py, 2026-10-22), where a MARP game replays frame-exact with it;
the runtime side is cyc_poll / cyc_ei in src/blktiger.s.

The board's main Z80 runs at 6 MHz and takes the frame interrupt (IM 1, `irq0_line_hold`) every
1/60 s: 100,000 cycles a frame. Without a budget the port delivers the arcade tick only when the
game's task kernel idles (blktiger.s z80_hook), so a task's work never spans a frame. On the board it
does (the boot's video RAM clears take five frames), and the task that steps the random generator
then runs a different number of times: a MAME recording's inputs replayed on the port leave the
recorded game (F030Arcade PROGRESS.md, 2026-10-21).

This emitter charges the original cycles (MAME's tables, z80_cycles.py) to the long `z80_cyc`:

- at every block start (an entry, a jump/call target, a return point, the instruction after a
  transfer), the base cycles of the instructions up to the block's transfer or the next start,
  then a poll: a negative counter calls the runtime (cyc_poll), which runs the game's interrupt
  handler there, mid-task, as the board would, when interrupts are enabled;
- on the taken path of jr cc / djnz / call cc / ret cc, their extra cycles;
- before an ldir, 21 * BC - 5 (its 16-cycle last pass included).

The Z80 flags live in d6 between instructions; where the analysis says the CCR holds some at a
block start or a branch target, the charge keeps the CCR (move sr / move ccr).
"""
from z80_cycles import cycles as z80_cycles

COUNTER = 'z80_cyc'
REPEATS = {'ldir', 'lddr', 'cpir', 'cpdr', 'inir', 'indr', 'otir', 'otdr'}


def emitter(gen, rom):
    """A subclass of STEArcade's gen.BTEmitter with the budget; rom: gen.image() (virtual pcs)."""
    Base = gen.BTEmitter

    class CycleEmitter(Base):
        def _starts(self):
            s = self.__dict__.get('_cyc_starts')
            if s is not None:
                return s
            code = self.code
            s = set(self.joins) | set(self.hooks)
            for pc, ins in code.items():
                if ins.mn in REPEATS and ins.mn != 'ldir':
                    raise RuntimeError(f'cycle budget: {ins.mn} at {pc:#x} has no dynamic charge')
                if ins.target is not None and ins.target in code and ins.flow in ('jmp', 'jcc', 'call', 'ccall', 'rst'):
                    s.add(ins.target)
                if ins.flow != 'seq':
                    s.add(pc + ins.length)
                if pc not in self.ends:
                    s.add(pc)
            self._cyc_starts = s
            return s

        def _cost(self, start):
            code, starts, total, pc = self.code, self._starts(), 0, start
            while True:
                ins = code[pc]
                base, _ = z80_cycles(rom[pc:pc + ins.length])
                if ins.mn != 'ldir':
                    total += base
                if ins.flow != 'seq':
                    return total
                pc += ins.length
                if pc not in code or pc in starts:
                    return total

        def _charge(self, n, keep_ccr, poll):
            out = ['\tmove sr,-(a7)'] if keep_ccr else []
            out.append(f'\tsubi.l #{n},{COUNTER}' if n else f'\ttst.l {COUNTER}')
            if poll:
                ok = self.new_label()
                out += [f'\tbpl.s {ok}', '\tjsr cyc_poll', f'{ok}:']
            if keep_ccr:
                out.append('\tmove (a7)+,ccr')
            return out

        def _after_labels(self, n0, lines):
            i = n0
            while i < len(self.lines) and gen.re.match(r'^[A-Za-z]+[0-9A-F]{4,5}(_r)?:', self.lines[i]):
                i += 1
            self.lines[i:i] = lines

        def emit_ins(self, pc, live_out_override=None, with_label=True):
            n0 = len(self.lines)
            super().emit_ins(pc, live_out_override, with_label)
            if with_label and pc in self._starts():
                self._after_labels(n0, self._charge(self._cost(pc), self.ccr_in.get(pc, 0), True))

        def emit_copy(self, pc, push, pop):
            n0 = len(self.lines)
            super().emit_copy(pc, push, pop)
            if pc in self._starts():
                self._after_labels(n0, self._charge(self._cost(pc), self.ccr_in.get(pc, 0), True))

        # taken extras ---------------------------------------------------------------------------
        def _taken(self, extra, target):
            self.lines += self._charge(extra, self.ccr_in.get(target, 0), False)

        def x_jr(self, ins):
            if ins.ops[0][0] == 'addr':
                return super().x_jr(ins)
            cc, tgt = ins.ops[0][1], ins.ops[1][1]
            skip = self.new_label()
            self.branch(cc, skip, inv=True)
            self._taken(5, tgt)
            self.jmp_to(tgt)
            self.lines.append(skip + ':')

        def x_djnz(self, ins):
            tgt = ins.ops[0][1]
            skip = self.new_label()
            self.e('subq.b #1,d1')
            self.e(f'beq {skip}')
            self._taken(5, tgt)
            self.jmp_to(tgt)
            self.lines.append(skip + ':')

        def x_call(self, ins):
            ops = ins.ops
            if ops[0][0] == 'addr' or self.inline_body(ops[1][1]):
                return super().x_call(ins)
            cc, tgt, nxt = ops[0][1], ops[1][1], ins.pc + ins.length
            skip = self.new_label()
            self.branch(cc, skip, inv=True)
            self._taken(7, tgt)
            self.push_ret(nxt)
            self.jmp_to(tgt)
            self.lines.append(skip + ':')

        def x_ret(self, ins):
            if not ins.ops:
                return super().x_ret(ins)
            skip = self.new_label()
            self.branch(ins.ops[0][1], skip, inv=True)
            self._taken(6, None)                # (the dispatch after it sets the CCR anew)
            self.dispatch_ret(ins.pc)
            self.lines.append(skip + ':')

        def x_ldir(self, ins):
            keep = self.ccr_in.get(ins.pc, 0)
            lines = ['\tmove sr,-(a7)'] if keep else []
            lines += ['\tmoveq #0,d7', '\tmove.w d1,d7', '\tror.w #8,d7',      # BC (d1 holds it byte-swapped)
                      '\tsubq.l #1,d7', '\tand.l #$ffff,d7', '\taddq.l #1,d7',  # 0 = 65536
                      '\tmove.l d7,d5', '\tlsl.l #2,d5', '\tadd.l d5,d7',       # 21 * BC: n + 4n + 16n
                      '\tlsl.l #2,d5', '\tadd.l d5,d7', '\tsubq.l #5,d7', f'\tsub.l d7,{COUNTER}']
            if keep:
                lines.append('\tmove (a7)+,ccr')
            self.lines += lines
            super().x_ldir(ins)

        # the interrupt gate ----------------------------------------------------------------------
        def x_di(self, ins):
            self.e('clr.b g_iff')

        def x_ei(self, ins):
            self.e('jsr cyc_ei')                # (sets g_iff; a frame passed under di keeps one interrupt pending)

    return CycleEmitter
