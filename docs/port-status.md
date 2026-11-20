# Port status and full-game verification

Every port, experimental ones included, carries one of five status labels. The current label of each port is in the
[main README](../README.md).

| Label | Meaning |
|---|---|
| **Complete** | Graphics and sound done, and the whole game has been played through in Hatari. No port has this yet. |
| **Verification pending** | Graphics, sound and gameplay done; a full playthrough in Hatari is still to be checked. |
| **Incomplete** | Runs in Hatari, but something is missing (sound, a mode) or it is noticeably too slow. |
| **Not playable** | Crashes, broken behaviour or speed keep it from being played. |
| **Experimental / deferred** | Early work, research, or development on hold. |

## What counts as "Complete"

A port is **Complete** only when graphics and sound work and someone (or an automated player) has played it through
in Hatari without help: every required stage, up to the ending or the point where the game loops. Keep the evidence:
which build was played, the recorded inputs, proof of how far it got, and the result of replaying the recording in a
fresh run. Check normal keyboard and pad controls, the picture and the sound too; a run that only watches the game's
memory does not show those.

The automated tests (the port's logic and picture against the arcade) are a separate check and do not replace a
playthrough.

## What does not count

Report a real playthrough separately from an assisted one. Choosing a stage, editing memory, infinite lives, finishing
cheats, short integration tests, attract-mode runs and saved checkpoints do not show that the whole game can be
played. Say clearly what each result covers.

An automated player that fails does not prove a port unplayable either: tell a weak player apart from a reproduced
bug in the port. Before starting an automated player, check that its connection to the game (memory, inputs, the
replay in Hatari) works for that port; support for one port says nothing about another.

## Notes

- Galaga runs the arcade's real input chip since 2026-10-22 (see [its README](../games/galaga/README.md#mcu)); it has
  no automated-player profile yet.
- Donkey Kong (2026-10-20): the automated player did not get past the barrels by itself. An assisted run visited all
  four stage types by editing memory, which is not a playthrough, so Donkey Kong stays **Verification pending**. See
  the [dated report](../games/dkong/docs/dkong-loop-regression-2026-10-20.md) and its README's "Verification".
