# Retained native Hatari regressions

These Windows runners replay the private instrumented programs and compressed
input/RAM evidence from the adjacent Dreamer exploration. They do not train or
load a model. NumPy and Pillow are required, plus the normal local VASM/VLINK
toolchain, generated game assets/coverage and ROMs.

The patched Hatari named-pipe transport and TOS are expected under the adjacent
`F030Arcade-private` checkout; `STEARCADE_HATARI_ROOT` can override that location.
Discovery manifests pin the original program, Hatari and TOS hashes. A changed
translation produces a new recorded program hash and relocates validated
TEXT-relative RAM assist writes; all retained checkpoints must still match.

From the STEArcade root, with new output folders:

```powershell
& C:/msys64/opt/dreamerv3-python/python.exe tools/playtests/stearcade_1942_ending.py C:/Arbeit/dreamerv3/runs/stearcade-1942-ending-fixed-2 C:/Arbeit/dreamerv3/runs/1942-release-replay --extend 0
& C:/msys64/opt/dreamerv3-python/python.exe tools/playtests/stearcade_dkong_loop.py C:/Arbeit/dreamerv3/runs/stearcade-dkong-loop-discovery-2 C:/Arbeit/dreamerv3/runs/dkong-release-replay --extend 0
```

Positive `--extend` budgets continue assisted exploration and retain the added
inputs/checkpoints. Donkey Kong's diagnostic capture schedule is retained in
the manifest and must remain identical during replay. Inputs/assist commands,
checkpoints, build identities, transition logs and private builds stay local;
small reports and screenshots are kept in `docs/` and the game docs.

The original `$70F2`-only regression can be rerun with
`stearcade_1942_regression.py SOURCE NEW_OUTPUT`. Current translation roots also
cover the later high-score tasks. See the dated reports for historical hashes.

These are assisted port regressions. They do not establish natural complete
playability, ordinary keyboard/pad input, sound, independent arcade/render
equivalence, or real STE timing.
