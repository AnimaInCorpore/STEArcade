"""A recorded play for a port's benchmark: a search bot plays the port's reference machine (the arcade's logic tick for
tick, as each port's logic_test.py checks the translation against it) and saves its inputs by game tick, which the
port replays (-D PLAYBACK=1: the same game at any picture rate, so a benchmark run measures play, not the attract
mode, and repeats to the digit).

A game supplies an adapter (games/<game>/tools/play_search.py):
    PLAY                  ticks of attract mode, coin and start before the bot plays (start_system(t) gives SYSTEM;
                          optional: start_p1(t) P1 before PLAY, SYSTEM the system byte while the bot plays, 255)
    machine()             a new reference machine
    tick(m, t, system, p1)  one game tick with these inputs (t: the tick's number; from PLAY on the adapter also
                          applies its infinite-lives cheat, which the port's replay applies the same way)
    died(m)               a life was lost in the last tick (the cheat restores it before the next one)
    pos(m), POS_WRAP      a position that grows with the progress (the scroll), modulo POS_WRAP
    snapshot(m), restore(m, s)
    segment(rnd)          SEG ticks of P1 (active low) for one decision
The bot plays in segments; a lost life rewinds the play (HIT_BACK segments and more after each failed retry: a life
drops some time after the hit), a long stretch without progress rewinds too; when RETRIES run out, the death or the
stretch is accepted and the play goes on.

The file (build/<game>/play_inputs.bin) holds runs of equal ticks, 3 bytes each: count (1-255), SYSTEM, P1; a count of
0 ends it (the ports decode it a tick at a time, pb_inputs; a raw file would not fit next to 1943 in 4 MB).
"""
import random
import time

SEG = 12


def record(game, ticks, seed=1, out=None, log=print, *, policy=None, stats=None):
    """Record with the existing search, optionally proposing segments via policy(game, machine, tick, rng).

    Policies share the same rewind rules. stats, when supplied, receives search
    costs (including discarded attempts); the return value remains replay bytes.
    """
    if ticks < game.PLAY:
        raise ValueError('recording must include the startup frames')
    started = time.perf_counter()
    rnd = random.Random(seed)
    m = game.machine()
    system, p1 = [], []
    idle = getattr(game, 'SYSTEM', 255)
    for t in range(game.PLAY):
        s = game.start_system(t)
        p = game.start_p1(t) if hasattr(game, 'start_p1') else 255
        system.append(s); p1.append(p)
        game.tick(m, t, s, p)
    hist = [(game.snapshot(m), 0)]                 # per segment: the state at its start, the progress so far
    segs = []
    best, best_at = 0, 0
    floor = 0                                      # no rewind before this segment (an accepted death)
    r_death = r_stuck = 0
    death_at = -1000
    deaths = rewinds = 0
    attempts = simulated = 0
    t0 = time.time()
    half = game.POS_WRAP // 2
    while game.PLAY + len(segs) * SEG < ticks:
        n = len(segs)
        progress = hist[n][1]
        t = game.PLAY + n * SEG
        seg = game.segment(rnd) if policy is None else policy(game, m, t, rnd)
        if len(seg) != SEG or any(type(v) is not int or not 0 <= v <= 255 for v in seg):
            raise ValueError('a policy must return SEG active-low input bytes')
        attempts += 1
        y = game.pos(m); died = False
        for i, v in enumerate(seg):
            game.tick(m, t + i, idle, v)
            simulated += 1
            died |= game.died(m)
            ny = game.pos(m)
            d = (ny - y) % game.POS_WRAP
            if 0 < d < min(64, half): progress += d    # forward only (a death's jump back is not counted)
            y = ny
        if progress > best: best, best_at, r_stuck = progress, n + 1, 0
        stuck = n + 1 - best_at >= game.STUCK
        if died or stuck:
            r = r_death if died else r_stuck
            back = min(n - floor, game.HIT_BACK + 4 * r if died else (2 + r) * 3)
            if r < game.RETRIES and back > 0:
                if died: r_death += 1; death_at = n
                else: r_stuck += 1; best_at = n - back
                game.restore(m, hist[n - back][0])
                del segs[n - back:]; del hist[n - back + 1:]
                best = max(h[1] for h in hist)     # (the kept line's best, not an abandoned branch's)
                best_at = max(best_at if stuck else 0, next(i for i, h in enumerate(hist) if h[1] == best))
                rewinds += 1
                continue
            if died: deaths += 1; floor = n + 1; r_death = 0
            if stuck: best_at = n + 1; r_stuck = 0
        if n > death_at + 40: r_death = 0
        segs.append(seg)
        hist.append((game.snapshot(m), progress))
        if len(segs) % 50 == 0:
            log(f'tick {game.PLAY + len(segs) * SEG}: progress {progress}, deaths {deaths}, rewinds {rewinds}, '
                f'{time.time() - t0:.0f} s')
    for seg in segs:
        p1 += seg
        system += [idle] * SEG
    data = encode(list(zip(system[:ticks], p1[:ticks])))
    if out:
        out.write_bytes(data)
    if stats is not None:
        stats.update(seed=seed, ticks=ticks, segment_frames=SEG, attempts=attempts,
                     simulated_frames=game.PLAY + simulated, rewinds=rewinds,
                     accepted_deaths=deaths, search_progress=hist[-1][1],
                     recording_seconds=time.perf_counter() - started)
    log(f'{ticks} ticks -> {out} ({len(data)} bytes): progress {hist[-1][1]}, deaths {deaths}, rewinds {rewinds}')
    return data


def encode(ticks):
    """[(SYSTEM, P1)] a tick -> the run file."""
    out = bytearray()
    i = 0
    while i < len(ticks):
        j = i
        while j < len(ticks) and j - i < 255 and ticks[j] == ticks[i]:
            j += 1
        out += bytes((j - i, *ticks[i]))
        i = j
    return bytes(out + b'\0')


def load(path):
    """The run file -> [(SYSTEM, P1)] a tick."""
    data, ticks, k = path.read_bytes(), [], 0
    while data[k]:
        ticks += [(data[k + 1], data[k + 2])] * data[k]
        k += 3
    return ticks
