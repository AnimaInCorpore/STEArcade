# STEArcade 0.4

This release fixes 1942's ending/high-score task dispatch and records reproducible
assisted progression through 1942's ending and Donkey Kong's difficulty loop.
Both ports remain **Verification pending** (yellow); these assisted runs do not
certify natural complete playability.

- **1942:** translate indirect task entries `$70F2`, `$6EEB` and `$6EDA` even
  without observed gameplay coverage. The final fresh Hatari replay completed
  51,176 inputs with 426 matching RAM checkpoints, through the ending,
  high-score/continue flow and subsequent gameplay.
- **Donkey Kong:** no port fix was needed. Assisted completion of all four board
  types reached difficulty 6 and wrapped the repeating board sequence. A fresh
  replay completed 38,200 inputs with 318 matching RAM checkpoints and 22
  identical framebuffer/palette samples.
- Include the shared short-HOG Blitter copy/fill paths, conservative bus-cycle
  budgeting, M72 bitmap rotations and cross-port validation notes. See
  [the measurements](docs/virtual-scroll-performance.md); small simulator-cycle
  improvements are not new native-fps claims.
- Add the five-color port-status legend, dated reports, small machine-readable
  results, screenshots, and Windows retained-input replay runners. Full timelines,
  RAM checkpoints, ROM sets and private emulator files remain local.
- Compared with the 0.3 package, the release now includes the already committed
  R-Type, Kung-Fu Master, Trojan, Double Dragon, Gauntlet and Gyruss ports alongside
  the original eight. Their individual limitations are documented in the game
  READMEs and packaged README.TXT. Galaga remains experimental/deferred pending
  real MCU ROMs; its packaged build is not a gameplay certification.

The release archive contains default, self-contained TOS programs and a
README.TXT with controls and SHA-256 sums. It is built from the release commit,
including the shared Blitter/renderer updates and port validation notes. The new regression coverage uses native
Hatari with sound disabled and injected held inputs; ordinary control devices,
sound, natural completion and real STE timing were not verified by these runs.

See [1942 evidence](docs/1942-ending-regression-2026-10-20.md),
[Donkey Kong evidence](docs/dkong-loop-regression-2026-10-20.md), and the
[status policy](docs/port-status.md).
