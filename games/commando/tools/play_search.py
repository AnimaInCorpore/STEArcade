"""A recorded play-through for the benchmarks: a search bot plays the reference machine (tools/machine.py, the arcade's
logic tick for tick, as logic_test.py checks the port against it) and saves its inputs by game tick.

    python play_search.py [ticks] [seed]       -> build/commando/play_inputs.bin (2 bytes a tick: SYSTEM, P1)

Infinite lives: $EDA0 is set to 3 before every tick from PLAY on (the port's replay does the same), so the play never
ends; a death still costs the way back to the checkpoint.  The bot plays in segments of SEG ticks: a direction (mostly up: the game scrolls up), fire pressed and released, now
and then a grenade.  A lost life ($EDA0 drops) rewinds the play a few segments and tries other moves (further back
after each failed retry: the lives drop ~250 ticks after the hit); so does a stretch without progress (the scroll register $C808/9 not moving forward).  When
the retries run out the death is accepted and the play goes on.  Coin and start come at the ticks cover.py uses.
The port replays the file by game tick (build.py -D PLAYBACK=1, bench.sh PLAY=1): the same game at any picture rate.
"""
from pathlib import Path
import sys, random, time
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import Commando, BUILD

SEG = 12                    # ticks a segment (one decision)
LIVES = 0xeda0
COIN, START, PLAY = 700, 740, 780
STUCK = 200                 # segments without new progress before a rewind (gates and bunkers hold the scroll a while)
RETRIES = 6                 # rewinds for one death or one stuck stretch before it is accepted

UP, DOWN, LEFT, RIGHT, FIRE, GRENADE = 8, 4, 2, 1, 16, 32
DIRS = [UP, UP, UP, UP | LEFT, UP | RIGHT, UP | LEFT, UP | RIGHT, LEFT, RIGHT, 0, DOWN, DOWN | LEFT, DOWN | RIGHT]


def snapshot(m):
    return (bytes(m.mem), bytes(m.sprites), bytes(m.scroll), m.control, m.latch, m.pending, m.frame, m.booted,
            dict(m.cpu.__dict__))


def restore(m, s):
    m.mem[:], m.sprites[:], m.scroll[:] = s[0], s[1], s[2]
    m.control, m.latch, m.pending, m.frame, m.booted = s[3:8]
    m.cpu.__dict__.update(s[8])


def segment_inputs(rnd):
    """SEG ticks of P1 (active low): one direction, fire pressed every other 4 ticks, sometimes a grenade."""
    d = rnd.choice(DIRS)
    grenade = rnd.random() < 0.15
    out = []
    for t in range(SEG):
        held = d | (FIRE if (t // 4) % 2 == 0 else 0) | (GRENADE if grenade and t < 3 else 0)
        out.append(255 & ~held)
    return out


def scroll_y(m):
    return m.scroll[0] | (m.scroll[1] & 1) << 8


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rnd = random.Random(seed)
    m = Commando(); m.cpu.afmask = 0xc1
    system = []
    for f in range(PLAY):                       # attract, coin, start
        s = 255 & ~(128 if COIN <= f < COIN + 6 else 0) & ~(1 if START <= f < START + 6 else 0)
        system.append(s)
        m.inputs[:3] = [s, 255, 255]; m.run_frame_port()
    p1 = [255] * PLAY
    # Per segment: the snapshot at its start and the progress so far (the scroll moved forward, summed).
    hist = [(snapshot(m), 0)]
    segs = []                                   # the inputs of the played segments
    best, best_at = 0, 0                        # the most progress, and the segment it was reached in
    floor = 0                                   # no rewind goes before this segment (an accepted death)
    r_death = r_stuck = 0                       # rewinds for the current death / stuck stretch
    death_at = -1000
    deaths = rewinds = 0
    t0 = time.time()
    while PLAY + len(segs) * SEG < ticks:
        n = len(segs)
        progress = hist[n][1]
        seg = segment_inputs(rnd)
        y = scroll_y(m); died = False
        for v in seg:
            m.mem[LIVES] = 3                    # (the cheat: the port's PLAYBACK build does the same every tick)
            m.inputs[:3] = [255, v, 255]; m.run_frame_port()
            died |= m.mem[LIVES] < 3
            ny = scroll_y(m)
            d = (ny - y) & 511
            if 0 < d < 64: progress += d        # forward only (a death's jump back to the checkpoint is not counted)
            y = ny
        if progress > best: best, best_at, r_stuck = progress, n + 1, 0
        stuck = n + 1 - best_at >= STUCK
        if died or stuck:
            r = r_death if died else r_stuck
            back = min(n - floor, 26 + 4 * r if died else (2 + r) * 3)   # (a hit shows ~250 ticks before $EDA0 drops)
            if r < RETRIES and back > 0:
                if died: r_death += 1; death_at = n
                else: r_stuck += 1; best_at = n - back
                restore(m, hist[n - back][0])
                del segs[n - back:]; del hist[n - back + 1:]
                best = max(h[1] for h in hist)          # (the kept line's best, not an abandoned branch's)
                best_at = max(best_at if stuck else 0, next(i for i, h in enumerate(hist) if h[1] == best))
                rewinds += 1
                continue
            if died: deaths += 1; floor = n + 1; r_death = 0
            if stuck: best_at = n + 1; r_stuck = 0      # give up on this stretch
        if n > death_at + 40: r_death = 0               # (past the place of the last death)
        segs.append(([255] * SEG, seg))
        hist.append((snapshot(m), progress))
        if len(segs) % 50 == 0:
            print(f'tick {PLAY + len(segs) * SEG}: progress {progress}, deaths {deaths}, rewinds {rewinds}, '
                  f'{time.time() - t0:.0f} s', flush=True)
    for sysin, seg in segs:
        p1 += seg
        system += sysin
    data = bytes(b for pair in zip(system[:ticks], p1[:ticks]) for b in pair)
    (BUILD / 'play_inputs.bin').write_bytes(data)
    print(f'{ticks} ticks -> {BUILD / "play_inputs.bin"}: progress {hist[-1][1]}, deaths {deaths}, rewinds {rewinds}')


if __name__ == '__main__':
    main()
