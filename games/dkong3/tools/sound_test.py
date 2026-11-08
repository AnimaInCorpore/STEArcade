"""The STE sound driver (src/sound.s, run/dkong3_sim on Musashi) against the game's commands.

    python sound_test.py [frames] [--seed N]

The logic runs in lock-step with the reference (render_test.Harness); the driver's rules are modelled here from the
converter's tables (build/dkong3/sound/pcm/report.json: per latch the tune a value holds and the effect it starts):
a changed latch value starts or stops the latch's tune voice (a different tune clip; none stops it) and starts the
effect clip (a changed non-zero one).  Each frame the model is fed the latch values the reference's previous NMI wrote
(the driver runs before the next NMI); then snd_mix is called once and the six voices must be on the clips the model
names (the voice's pointer within the clip's bytes; 0: silent).  Then the mixing: the sum of the voices' samples (the
driver's saturating add) against snd_mixbuf, for a frame's worth of samples, with the DMA position faked.
"""
from pathlib import Path
import argparse
import json
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
import render_test as rt
from paths import build_dir

BUILD = build_dir('dkong3')
LATCHES = (0x7C00, 0x7C80, 0x7D00)


def call(h, label):
    """call a routine of the program (returning to sim_render_ret)"""
    sym, mem, cpu = h.sym, h.mem, h.cpu
    a7 = cpu.r_reg(R.A7)
    sp = a7 - 64
    mem.w32(sp, sym['sim_render_ret'])
    cpu.w_reg(R.A7, sp)
    cpu.w_pc(sym[label])
    h.run_to({sym['sim_render_ret']})
    cpu.w_reg(R.A7, a7)


def mix_test(h, clips, pcm, nclips):
    """snd_mix with faked DMA positions: the ring gets the saturating sum of the voices' bytes, the voices advance (a tune
    loops at its end, an effect ends); wrapping at the ring's end included.  -> the number of failures"""
    mem, sym = h.mem, h.sym
    ring, mixbuf = sym['snd_ring'], sym['snd_mixbuf']
    rng = np.random.RandomState(5)
    bad = 0
    loops = [c for c in range(1, nclips + 1) if clips[c][2]]
    shots = [c for c in range(1, nclips + 1) if not clips[c][2]]
    short = min(shots, key=lambda c: clips[c][1] - clips[c][0])
    for trial in range(40):
        voices = {}
        for v in range(6):
            kind = rng.randint(4)
            if kind == 0:
                continue
            c = int(rng.choice(loops if kind == 1 else shots if kind == 2 else [short]))
            pos = clips[c][0] + int(rng.randint(0, clips[c][1] - clips[c][0] + 1)) // 2 * 2
            if kind == 3:
                pos = clips[c][1] - int(rng.randint(2, 200)) // 2 * 2         # (about to end)
            voices[v] = [c, pos]
        for v in range(6):
            base = sym['snd_voices'] + 12 * v
            if v in voices:
                c, pos = voices[v]
                mem.w32(base, pos)
                mem.w32(base + 4, clips[c][1])
                mem.w32(base + 8, clips[c][2])
            else:
                mem.w32(base, 0)
        wp = int(rng.randint(0, 512)) * 4
        dv = int(rng.randint(0, 11))                          # (the VBLs since the last call; more than 8 count as 8)
        acc = int(rng.randint(0, 200))
        mem.w16(sym['snd_wp'], wp)
        mem.w16(sym['snd_fc'], (mem.r16(sym['frame_counter'] + 2) - dv) & 0xFFFF)
        mem.w32(sym['snd_acc'], acc)
        tot = 6258 * min(dv, 8) + acc
        n = 4 * (tot // 200)
        before = bytes(mem.r_block(ring, 2048))
        call(h, 'snd_mix')
        after = bytes(mem.r_block(ring, 2048))
        if mem.r16(sym['snd_wp']) != (wp + n) & 2044 or mem.r32(sym['snd_acc']) != tot % 200:
            bad += 1
            print('mix trial %d: wp %d (expected %d), acc %d (expected %d)' % (trial, mem.r16(sym['snd_wp']), (wp + n) & 2044, mem.r32(sym['snd_acc']), tot % 200))
        want = np.zeros(n, int)
        for v, (c, pos) in voices.items():
            ptr, end, lp = pos, clips[c][1], clips[c][2]
            data = []
            while len(data) < n and ptr is not None:
                m = min(n - len(data), end - ptr)
                data += list(np.frombuffer(pcm[ptr - sym['dk_sound']:ptr - sym['dk_sound'] + m], np.int8))
                ptr += m
                if ptr >= end:
                    ptr = lp or None
            want[:len(data)] = np.clip(want[:len(data)] + np.array(data, int), -128, 127)
        exp = bytearray(before)
        for i in range(n):
            exp[(wp + i) & 2047] = int(want[i]) & 255
        if bytes(exp) != after:
            bad += 1
            d = [i for i in range(2048) if exp[i] != after[i]]
            print('mix trial %d: %d ring bytes differ (first %s), wp %d n %d' % (trial, len(d), d[:4], wp, n))
    print('snd_mix: 40 trials of the sample clock and the voices added (saturating, loops, ends, the ring wrapping), %d differ' % bad)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='dkong3_sim')
    a = ap.parse_args()
    h = rt.Harness(a.seed, a.tag)
    mem, sym = h.mem, h.sym
    rep = json.loads((BUILD / 'sound' / 'pcm' / 'report.json').read_text())
    tabs = {k: {int(v): n for v, n in t.items()} for k, t in rep['tabs'].items()}
    nclips = len(rep['clips'])
    clips = [(mem.r32(sym['snd_clips'] + 12 * n) + sym['dk_sound'], mem.r32(sym['snd_clips'] + 12 * n + 4) + sym['dk_sound'],
              (mem.r32(sym['snd_clips'] + 12 * n + 8) + sym['dk_sound']) if mem.r32(sym['snd_clips'] + 12 * n + 8) else 0)
             for n in range(nclips + 1)]
    ckind = [mem.r8(sym['snd_clipkind'] + n) for n in range(nclips + 1)]
    pcm = (BUILD / 'dkong3_sound.bin').read_bytes()
    # the driver's own tables must be the converter's
    for k, a_ in enumerate(LATCHES):
        for kind in ('hold', 'eff'):
            base = sym['snd_%s%d' % (kind, k + 1)]
            want = tabs['%04x_%s' % (a_, kind)]
            for v in range(256):
                assert mem.r8(base + v) == want.get(v, 0), (kind, k, v)
    last = [0, 0, 0]
    lh, le = [0, 0, 0], [0, 0, 0]
    want = [0] * 6
    prev_vals = (0, 0, 0)
    checked = starts = bad = 0
    voices = sym['snd_voices']
    for f in range(a.frames):
        h.frame()
        # the driver at this frame's hook read the latches as the previous NMI had left them
        for k in range(3):
            v = prev_vals[k]
            if v != last[k]:
                last[k] = v
                hold = tabs['%04x_hold' % LATCHES[k]].get(v, 0)
                eff = tabs['%04x_eff' % LATCHES[k]].get(v, 0)
                if hold != lh[k]:
                    lh[k] = hold
                    want[3 * (k // 2)] = hold
                    starts += bool(hold)
                if eff != le[k]:
                    le[k] = eff
                    if eff:
                        want[3 * (k // 2) + 1 + ckind[eff]] = eff
                        starts += 1
        prev_vals = tuple(h.m.snd[a_] for a_ in LATCHES)
        call(h, 'snd_mix')
        for n in range(6):
            ptr = mem.r32(voices + 12 * n)
            got = 0
            if ptr:
                got = next((c for c in range(1, nclips + 1) if clips[c][0] <= ptr < clips[c][1]), -1)
            checked += 1
            if got != want[n]:
                bad += 1
                print('frame %d: voice %d is on clip %d, expected %d' % (f, n, got, want[n]))
            if want[n] and not clips[want[n]][2] and not ptr:
                want[n] = 0                  # (an effect that ran out)
    mbad = mix_test(h, clips, pcm, nclips)
    bad += mbad
    print('%s: %d clips started, %d voice states checked (seed %d), %d differ; the model\'s tables equal the driver\'s' % (
        'PASS' if not bad else 'FAIL', starts, checked, a.seed, bad))
    return int(bool(bad))


if __name__ == '__main__':
    sys.exit(main())
