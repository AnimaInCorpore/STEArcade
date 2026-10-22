"""The translated 51XX (engine/mb88x.py) against the event-driven reference (games/galaga/tools/machine.py,
Galaga(mcu=True, mcu_events=True), which matches the cycle-exact 51XX and MAME): a game is played in the reference with
the inputs of games/galaga/ref/mame_cmp_51xx.py; every pin change, reset, port value and run of its 51XX is replayed
in the STE simulator on the translated code, and after each run the 51XX's RAM, the shared latch, A, X, Y, the timer
and the interrupt enables are compared.  Also reports the 68000 cycles of the runs.

    python engine/mb88x_test.py [frames] [script]        # default 3000 two (needs assets/roms/namco51.zip)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "games", "galaga", "tools"), os.path.join(HERE, "..", "games", "galaga", "ref")]
FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
SCRIPT = sys.argv[2] if len(sys.argv) > 2 else "two"
sys.argv = [sys.argv[0], str(FRAMES), SCRIPT]
import mb88x
from mb88x import S_RAM, S_PORTO, S_RW, S_R, S_A, S_X, S_Y, S_TL, S_PIO
from paths import VASM, VLINK, build_dir
import machine
import mame_cmp_51xx as scripts

OUT_BYTES = 70          # per run: 64 RAM, the latch, A, X, Y, TL, PIO
CHUNK = 300             # frames per replay

HARNESS = r"""
; engine/mb88x_test.py: replays the reference's 51XX events on the translated code
	section	text,code
start:	bra.s	start
mbx_replay:
	lea	mbx_ops,a2
	lea	mbx_out,a3
	lea	N51_state,a4
.next:	moveq	#0,d6
	move.b	(a2)+,d6
	beq	.end
	cmp.b	#1,d6
	bne.s	.n2
	bsr	N51_reset
	bra.s	.next
.n2:	move.b	(a2)+,d7
	cmp.b	#2,d6
	bne.s	.n3
	bsr	N51_set_tc
	bra.s	.next
.n3:	cmp.b	#3,d6
	bne.s	.n4
	bsr	N51_set_irq
	bra.s	.next
.n4:	cmp.b	#4,d6
	bne.s	.n5
	move.b	d7,%(rw)d(a4)
	bra.s	.next
.n5:	cmp.b	#5,d6
	bne.s	.n6
	move.b	d7,%(porto)d(a4)
	bra.s	.next
.n6:	cmp.b	#6,d6
	bne.s	.n7
	move.b	d7,%(r)d(a4)
	move.b	(a2)+,%(r)d+1(a4)
	move.b	(a2)+,%(r)d+2(a4)
	move.b	(a2)+,%(r)d+3(a4)
	bra.s	.next
.n7:	subq.l	#1,a2			; (7: run, no argument)
	tst.b	mbx_norun
	bne.s	.skip
	bsr	N51_run
.skip:
	move.l	a4,a0
	moveq	#63,d0
.c:	move.b	(a0)+,(a3)+
	dbf	d0,.c
	move.b	%(porto)d(a4),(a3)+
	move.b	%(a)d(a4),(a3)+
	move.b	%(x)d(a4),(a3)+
	move.b	%(y)d(a4),(a3)+
	move.b	%(tl)d(a4),(a3)+
	move.b	%(pio)d(a4),(a3)+
	bra	.next
.end:	move.l	a3,mbx_end
mbx_done:
	bra.s	mbx_done
	include	"n51_code.s"
	section	bss,bss
mbx_end:	ds.l	1
mbx_norun:	ds.w	1
mbx_ops:	ds.b	262144
mbx_out:	ds.b	%(outsize)d
""" % dict(rw=S_RW, porto=S_PORTO, r=S_R, a=S_A, x=S_X, y=S_Y, tl=S_TL, pio=S_PIO, outsize=OUT_BYTES * 8 * CHUNK * 3)


def build():
    out = build_dir("mb88x")
    rom = machine.load_mcu("namco51.zip", "51xx.bin", 0xc2f57ef8)
    text, seen = mb88x.translate_51xx(rom)
    (out / "n51_code.s").write_text(text + "\n\tsection\tbss,bss\n" + mb88x.bss("N51") + "\tsection\ttext,code\n")
    (out / "harness.s").write_text(HARNESS)
    obj, prg, mp = out / "harness.o", out / "HARNESS.PRG", out / "harness.map"
    for cmd in ([VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(out), "-o", str(obj), str(out / "harness.s")],
                [VLINK, "-b", "ataritos", "-s", "-o", str(prg), "-M" + str(mp), str(obj)]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    return prg, mp, len(seen)


class Recorder:
    """the reference's 51XX events as replay ops, and the state after each run"""

    def __init__(self, m):
        self.m, self.ops, self.want, self.frames = m, bytearray(), [], {}
        self.last = None
        n51, mcu = m.n51, m.n51.mcu
        for name, code in (("set_tc", 2), ("set_irq", 3)):
            f = getattr(mcu, name)

            def wrap(v, f=f, code=code):
                self.sync()
                self.ops += bytes([code, 1 if v else 0])
                f(v)
            setattr(mcu, name, wrap)
        rs = n51.reset

        def reset():
            self.sync()
            self.ops.append(1)
            rs()
        n51.reset = reset
        run = m.run51

        def run51():
            if n51.held:
                return run()
            self.sync()
            self.ops.append(7)
            run()
            c = n51.mcu
            self.want.append(bytes(v & 15 for v in c.ram) + bytes([n51.port_o, c.a, c.x, c.y, c.tl, c.pio]))
            self.last = (n51.rw, n51.port_o, self.inputs())
        m.run51 = run51

    def inputs(self):
        m = self.m
        return (m.in0 & 15, m.in0 >> 4, m.in1 & 15, m.in1 >> 4)

    def sync(self):
        n51 = self.m.n51
        rw, po, r = n51.rw, n51.port_o, self.inputs()
        last = self.last or (None, None, None)
        if rw != last[0]:
            self.ops += bytes([4, rw])
        if po != last[1]:
            self.ops += bytes([5, po])
        if r != last[2]:
            self.ops += bytes([6]) + bytes(r)
        self.last = (rw, po, r)


def main():
    from sim import Sim
    from machine68k import Register as R
    prg, mp, ninsn = build()
    s = Sim(str(prg), ram_kib=16384, run_dir=prg.parent)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(mp).items()}
    cpu, mem = s.cpu, s.mem
    m = machine.Galaga(mcu=True, mcu_events=True)
    rec = Recorder(m)
    runs = bad = 0
    cycles = active = 0
    while m.frame < FRAMES:
        for _ in range(CHUNK):
            if m.frame >= FRAMES:
                break
            m.in0, m.in1 = scripts.inputs(m.frame)
            k = len(rec.want)
            m.run_frame()
            rec.frames[m.frame] = len(rec.want) > k
        ops = bytes(rec.ops) + b"\0"
        assert len(ops) < 262144, "chunk too large"
        mem.w_block(sym["mbx_ops"], ops)
        # the same replay without the runs first (its cycles subtracted: the 51XX's own), then with them
        state = mem.r_block(sym["N51_state"], mb88x.S_SIZE)
        for norun in (1, 0):
            mem.w8(sym["mbx_norun"], norun)
            mem.w_block(sym["N51_state"], state)
            cpu.w_reg(R.A7, 0xF00000)
            cpu.w_sr(0x2700)
            cpu.w_pc(sym["mbx_replay"])
            c = 0
            while cpu.r_pc() != sym["mbx_done"]:
                c += cpu.execute(200000).cycles
            cycles += -c if norun else c
            active += 0 if norun else sum(1 for v in rec.frames.values() if v)
        n = (mem.r32(sym["mbx_end"]) - sym["mbx_out"]) // OUT_BYTES
        got = mem.r_block(sym["mbx_out"], n * OUT_BYTES)
        if n != len(rec.want):
            sys.exit("frame %d: %d runs on the 68000, %d in the reference" % (m.frame, n, len(rec.want)))
        for i, w in enumerate(rec.want):
            g = bytes(got[i * OUT_BYTES:(i + 1) * OUT_BYTES])
            if g != w:
                bad += 1
                if bad <= 5:
                    d = [j for j in range(OUT_BYTES) if g[j] != w[j]]
                    print("run %d (frame <= %d): bytes %s: 68000 %s reference %s" % (runs + i, m.frame, d[:8],
                          [g[j] for j in d[:8]], [w[j] for j in d[:8]]))
        runs += n
        rec.ops, rec.want, rec.frames = bytearray(), [], {}
    print("%d reachable instructions; %s %d frames: %d runs, %d differ; the translated 51XX: %d 68000 cycles, "
          "%.0f a frame over the %d frames it ran in" % (ninsn, SCRIPT, FRAMES, runs, bad, cycles, cycles / max(active, 1), active))
    print("PASS" if bad == 0 else "FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
