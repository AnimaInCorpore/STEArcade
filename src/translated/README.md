# Translated and native routine sources

This directory contains two kinds of artifacts:

- `boot_init.asm` is a structural reference translation and is not production code.
- `*_native.asm` files are routine drafts or validated replacements. A file is not eligible for
  integration merely because it exists; it needs a complete contract and a passing differential
  fixture.

The `routine_L_...` naming variant is legacy output from an earlier batch generator. Do not add
new files with that prefix. New routine files use `routine_XXXX_native.asm` and labels of the form
`L_XXXX_native`.

Generated snapshots under `src/generated/` are reference artifacts only. They are not included by
`src/main.asm`; regenerate them from the converter rather than editing them by hand.
