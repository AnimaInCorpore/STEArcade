# Port status and full-game verification

This policy applies to every port, including experimental and deferred ports.
The current per-port classifications and five-color legend are in the
[root README](../README.md).

An automated player such as Dreamer can attempt natural progression through a
supported port, including its final stage or loop transition. This is an
exploration goal, not a guarantee that its learned policy can finish the game.
Check that the game's RAM/input adapter and native Hatari replay transport work
before starting; support for one port does not establish support for every port.
Galaga's hold for its real 51xx/54xx MCU ROMs ended on 2026-10-22: the port runs the real 51XX
(see [its README](../games/galaga/README.md#the-real-51xx-on-the-ste-2026-10-21)); it has no PPO adapter yet.

A green **Complete** status requires graphics and sound to be implemented and
complete playability to be verified in Hatari. Record a successful natural
playthrough through every required stage and the ending or first full loop
transition, as appropriate for that game. Retain the build identity, input/replay
recording, progression evidence and results of a fresh replay. Verify ordinary
keyboard/pad controls, graphics and sound as well; a RAM-only run does not establish
those. Keep independent logic/render equivalence checks separate from playtesting.

Report natural clears separately from assisted visits. Stage selection, RAM pokes,
infinite lives, finish cheats, short integration tests, attract-mode runs and
reproducible checkpoints alone do not establish full-game completion. Label the
scope and limits of each result explicitly. An unsuccessful policy run alone also
does not prove that a port is unplayable; distinguish agent failure from a
reproduced port defect.

As of 2026-10-20, dkong's documented Dreamer natural run did not clear barrels.
Its assisted run visited all four stage types by changing RAM; it did not naturally
clear them. A full playthrough can be attempted, but success remains unverified,
so dkong is yellow (**Verification pending**). See the
[dated report](../games/dkong/README.md#dreamer-hatari-playtest-2026-10-20).
