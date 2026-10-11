"""The sound of the STE build (the --sim build on Musashi) against the reference, frame by frame:

1. the sound CPU: the reference plays a game in the port's schedule (tools/machine.py run_frame_port); before its
   sound CPU's two NMIs of a frame, the shared page $9A00-$9AFF and $9211 go into the 68000 build too, which runs
   `g_sound_frame` (the translated NMI handler twice, the page copied in and out, snd_update); after them the page
   (but its stack bytes $9AF0-$9AFF) and the WSG registers $6800-$681F must be the same, and the YM's registers those of tools/sound.py ym_image
   (with the explosions the reference's 54XX started in that frame).
2. snd_update alone on random WSG registers and explosion envelopes, against ym_image.

    python sound_test.py [frames]
"""
import os
import random
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir
from machine import Galaga
import gen
import sound

RUN = ROOT / "run" / "galaga_sim"
MAP = build_dir("galaga") / "galaga.map"


def inputs(f, rnd, st):
    """(IN0, IN1): a coin and the start button, then random play; another coin after a game over"""
    in0 = in1 = 0xFF
    if st["state"] == "attract" and f >= st["coin_at"]:
        st["state"], st["t0"] = "coin", f
    g = f - st["t0"]
    if st["state"] == "coin":
        if g < 5:
            in1 &= ~0x10
        elif 40 <= g < 45:
            in1 &= ~0x04
        elif g >= 45:
            st["state"], st["t0"] = "play", f
    if st["state"] == "play":
        if f % 15 == 0:
            st["joy"] = rnd.choice([0, 0, 1, 2])
        if st["joy"] == 1:
            in0 &= ~0x02
        if st["joy"] == 2:
            in0 &= ~0x08
        if rnd.random() < 0.1:
            in1 &= ~0x01
        if g > 3000 and g % 1500 == 0:
            st["state"], st["coin_at"] = "attract", f + 100
    return in0, in1


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    s = Sim(str(RUN / "GALAGA.PRG"), run_dir=RUN)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    stop = sym["snd_off"]                       # (a return address: the test stops before running it)

    def call(addr):
        sp = s.base - 0x100
        cpu.w_reg(R.A7, sp - 4)
        mem.w32(sp - 4, stop)
        cpu.w_pc(addr)
        for _ in range(2000000):
            if cpu.r_pc() == stop:
                return
            cpu.execute(1)
        raise RuntimeError("no return from %06X: pc %06X" % (addr, cpu.r_pc()))

    cpu.w_sr(0x2700)
    # the start-up parts the test needs: the dispatch tables, the sound CPU's context, the YM's shadow
    cpu.w_reg(R.A0, sym["g3_dispatch"])
    cpu.w_reg(R.A1, sym["g3_dispatch_sw"])
    cpu.w_reg(R.D0, gen.ENTRIES)
    call(sym["z80_init_dispatch"])
    for i in range(16):
        mem.w32(sym["ctx3"] + 4 * i, 0)
    mem.w32(sym["ctx3"] + 4 * 12, sym["g3_dispatch_sw"])
    mem.w32(sym["ctx3"] + 4 * 13, sym["g3_ram"] + 0x1B00)
    mem.w32(sym["ctx3"] + 4 * 14, sym["g3_block"])
    mem.w_block(sym["g3_block"], bytes(sound.load("gg1_7b.2c")))     # (the program's load_roms did not run)
    mem.w8(sym["snd_expl_t"], 0xFF)
    call(sym["snd_init"])

    g_ram, g3, g3_ram = sym["g_block"] + 0x8000, sym["g3_block"], sym["g3_block"] + 0x8000
    m = Galaga(skip_tests=True)
    expl = sound.Explosion()
    rnd = random.Random(1)
    st = {"state": "attract", "coin_at": 900, "t0": 0, "joy": 0}
    bad = [0, 0, 0]
    compared = [0]
    triggers = [0]
    nonsilent = [0]

    def hook(machine, when):
        if when == "before":
            mem.w_block(g_ram + 0x1A00, bytes(machine.ram[0x1A00:0x1B00]))
            mem.w8(g_ram + 0x1211, machine.ram[0x1211])
            return
        mem.w8(sym["cpu3_state"], 2)
        if machine.n54_triggers != triggers[0]:
            triggers[0] = machine.n54_triggers
            mem.w8(sym["snd_expl_t"], 0)
            expl.trigger()
        call(sym["g_sound_frame"])
        f = machine.frame
        compared[0] += 1
        want_page = bytes(machine.ram[0x1A00:0x1AF0])          # (not $9AF0-$9AFF: the stack below $9B00, its dead
        page = bytes(mem.r_block(g3_ram + 0x1A00, 0xF0))        # bytes are the runtime's token and flags)
        shared = bytes(mem.r_block(g_ram + 0x1AA0, 0x1A)) + bytes([mem.r8(g_ram + 0x1A79)])
        if page != want_page or shared != want_page[0xA0:0xBA] + want_page[0x79:0x7A]:
            bad[0] += 1
            if bad[0] <= 3:
                d = [i for i in range(0xF0) if page[i] != want_page[i]]
                print("frame %d: $9Axx differs at %s (own copy), shared %s / %s" % (
                    f, " ".join("%02X" % i for i in d[:16]), shared.hex(), (want_page[0xA0:0xBA] + want_page[0x79:0x7A]).hex()))
        wsg = [b & 15 for b in mem.r_block(g3 + 0x6800, 0x20)]
        want = [b & 15 for b in machine.sound]
        if wsg != want:
            bad[1] += 1
            if bad[1] <= 3:
                print("frame %d: WSG 68000 %s reference %s" % (f, wsg, want))
        ym = list(mem.r_block(sym["snd_ym"], 11))
        img = sound.ym_image(want, expl.step())
        if any(img[8:11]):
            nonsilent[0] += 1
        if ym != img:
            bad[2] += 1
            if bad[2] <= 3:
                print("frame %d: YM 68000 %s model %s" % (f, ym, img))

    m.sound_hook = hook
    for f in range(frames):
        m.in0, m.in1 = inputs(f, rnd, st)
        m.run_frame_port()
    print("sound CPU: %d frames compared, $9Axx differs in %d, WSG in %d, YM in %d; %d frames with sound, %d explosions" % (
        compared[0], bad[0], bad[1], bad[2], nonsilent[0], triggers[0]))

    # snd_update alone
    rnd = random.Random(2)
    nbad = 0
    expl = sound.Explosion()
    mem.w8(sym["snd_expl_t"], 0xFF)
    mem.w8(sym["cpu3_state"], 0)                # (g_sound_frame: no NMIs, only snd_update)
    for t in range(3000):
        regs = [rnd.randrange(256) if rnd.random() < 0.5 else rnd.choice([0, 15, 0x10]) for _ in range(32)]
        if rnd.random() < 0.3:
            regs[0x15] = regs[0x1A] = regs[0x1F] = 0
        mem.w_block(g3 + 0x6800, bytes(regs))
        if rnd.random() < 0.02:
            mem.w8(sym["snd_expl_t"], 0)
            expl.trigger()
        call(sym["g_sound_frame"])
        ym = list(mem.r_block(sym["snd_ym"], 11))
        img = sound.ym_image(regs, expl.step())
        if ym != img:
            nbad += 1
            if nbad <= 3:
                print("random %d: YM 68000 %s model %s (WSG %s)" % (t, ym, img, regs))
    print("random WSG registers: 3000 frames, %d differ" % nbad)
    return 1 if sum(bad) or nbad else 0


if __name__ == "__main__":
    sys.exit(main())
