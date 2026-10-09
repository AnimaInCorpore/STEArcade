# Gun.Smoke (Capcom, 1985)

Initial main-Z80 reference for MAME set `gunsmoke`. ROM preparation verifies all
32 files by size, CRC32 and SHA1 and builds seven unmodified MAME regions.
The reference implements the memory map, four ROM banks, active-low controls,
DIP defaults, held VBL interrupts, explicit sprite buffering, a reference renderer and MAME's
three-byte protection read workaround. No boot or checksum patches are applied.

```sh
python port.py prepare gunsmoke
python port.py test gunsmoke          # bus checks and 700 unpatched CPU frames
python port.py mame gunsmoke          # exact pixels and all 640 pens against MAME
python port.py mame gunsmoke --play   # insert a coin and start for gameplay snapshots
python port.py cover gunsmoke 1      # bank-aware PCs, window reads and latch writes
```

Preparation reads `assets/roms/gunsmoke.zip`, extracts to
`assets/roms/extracted/gunsmoke` and writes regions to `build/gunsmoke`.
The checked manifest is in [docs/rom_manifest.json](docs/rom_manifest.json).
Coverage writes `build/gunsmoke/cover<seed>.pkl`; PCs in the bank window carry
the bank number, other PCs use bank -1. The sound latch is recorded but the
audio Z80 and YM2203s are not emulated.

Hardware comes from F030Arcade's
`third_party/jsm68kdisassembler/third_party/mame/src/mame/capcom/gunsmoke.cpp`:
main CPU 3 MHz, pixel clock 6 MHz, 384 pixels per line, 262 lines per frame;
192 CPU cycles per line, VBL interrupt at line 240. A write to C806 buffers
all 4096 sprite bytes. C804 selects the bank in bits 2–3 and controls text
and screen flip; D806 controls background, sprites and sprite bank.

The renderer decodes 8x8 text, 32x32 ROM-map background tiles and 16x16
sprites. It implements scrolling, flips, sprite bank selection, text transparency
by indirect palette entry 0x4f, layer enables and the board's ROT270 orientation.
`test` writes `build/gunsmoke/reference.png`. `mame` reads MAME's actual buffered
sprite device and saved layer state, compares the rendered snapshot pixel by
pixel, and checks all 640 PROM-derived pen colours. It keeps captures and logs
in a temporary directory printed for each frame. Set `MAME` to override the
MAME executable.

The STE translation, executable and sound remain pending. Boot tests establish
CPU progress, not full gameplay or agreement with MAME timing. Snapshot checks
validate the renderer using MAME's machine state, not the reference CPU schedule.
`build` and `run` report the missing runtime.

Validation: MAME snapshots at frames 100, 700, 1500, 2500, 4000 and 6000
all match with zero differing pixels, covering boot and attract screens. All 640 palette pens match at every capture.
The `--play` captures at frames 1500 and 2500 also match exactly; frame 2500
exercises the scrolling stage background, character sprites and HUD.
