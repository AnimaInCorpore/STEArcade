# Generated assembly snapshots

The `.asm` files in this directory are historical converter outputs and review snapshots. They
are not build inputs and must not be included from `src/main.asm`.

Use `tools/convert.js` with the validated `assets/roms/extracted/cpu.rom` image to create a fresh
snapshot. The converter now rejects ZIP archives and emits VASM-compatible section/comment syntax,
but its output remains a structural draft until the opcode semantics and control flow pass the
differential-validation gate in `PORTING.md`.

Do not create versioned filenames such as `cpu_full_vN.asm` for routine work. Record the input ROM
hash and converter revision in the validation fixture instead.
