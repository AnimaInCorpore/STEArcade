# Go-Explore: from the progress search to a cell archive

Status: recommended next step for exploration, not yet implemented (recorded
2026-10-19). Consider it before adding another PPO profile or a longer search
recording when a port's coverage, a test's reach or a benchmark's play needs
to go further into a game.

## Why

The two existing generators stop short in opposite ways. PPO
([ppo.md](ppo.md)) optimises a reward and has to re-earn every deep state from
the start of each episode: the Kung-Fu Master pilot gained 0.55% logical PC
coverage over uniform input and stayed on floor 1. `engine/playbot.py` plays
forward with snapshots and rewinds (on a lost life or a stretch without
progress) and reached Double Dragon's missions 2 to 4, but it follows one
measure, `pos(m)`, so a side path that does not advance the scroll - a bonus
room, a continue screen, the two-player logic, a boss's later phase - is
never kept.

Go-Explore (Ecoffet et al., *First return, then explore*, Nature 2021;
https://github.com/uber-research/go-explore) keeps **every** distinct state it
reaches in an archive, returns to a promising one by restoring it, and only
then explores. Depth is never paid for twice, and nothing that looked
unproductive is thrown away.

## Mapping onto what exists

`playbot.py`'s adapter (`games/<game>/tools/play_search.py`) already supplies
almost every piece:

| Go-Explore | STEArcade |
| --- | --- |
| deterministic environment | the reference machine, `machine()` / `tick(m, t, system, p1)` |
| return to a cell | `snapshot(m)` / `restore(m, s)` - cheap, in-process Python |
| explore step | `segment(rnd)`: 12-tick (`SEG`) input decisions |
| score / novelty | first-executed main-CPU logical PCs, as the PPO reward counts them |
| dead ends | `died(m)` and the infinite-lives cheat the replay applies too |
| product | the input timeline in the count/SYSTEM/P1 RLE format of `play_inputs.bin` |

The one new adapter function is `cell(m)`: a coarse key built from RAM -
stage/mission, `pos(m)` in buckets, a coarse player position, the boss or
attract phase, a lives band - plus the archive driver: select a cell weighted
towards few visits and recent new PCs, `restore` it, explore N segments,
archive or improve every cell met (keeping the shortest timeline to it).

Rules that carry over unchanged from [ppo.md](ppo.md): the count/SYSTEM/P1
replay contract, native Hatari replay of every kept timeline before it is used
anywhere, curated `port.py cover` runs and canonical fixtures are never
replaced, and Galaga stays deferred until its real MCU ROMs are available.

## What it is not

Go-Explore finds shortcuts and edge paths; it does not play like a person.
For human-like benchmark play keep `playbot.py`, or imitate recorded human
sessions. Use Go-Explore for coverage, for reaching the code a translation
has never run, and for bug finding.

## References

- https://github.com/uber-research/go-explore - code of the papers (archived
  2022; licence marked "Other" - read it before reusing code).
- https://github.com/conglu1997/intelligent-go-explore - a foundation model
  choosing interesting cells.
- F030Arcade `docs/go-explore.md` - the same method for MAME telemetry
  coverage (the 68000 disassembler) and Falcon port tests.
