# ROM Information

## Files
- `assets/roms/dkong.zip` - Original arcade ROM archive
- Extracted files in `assets/roms/extracted/`
- Working copy `C:/Arbeit/jsz80test/dkong.dat` - 65536 bytes
- Concatenated CPU ROM `assets/roms/extracted/cpu.rom` - 16 KiB, built from selected set

## Selected CPU ROM Set

Selected MAME driver: `dkong` (TKG-04 Upgrade, Nintendo Service Department Bulletin # TKG-02 12-11-81)

CPU ROM load map (Z80 main CPU, memory 0000-3FFF):

| Z80 Address | Size | File | MAME name | CRC32 | SHA1 |
|-------------|------|------|-----------|-------|------|
| 0x0000 | 0x1000 | `c_5et_g.bin` | c_5et_g.bin | ba70b88b | d76ebecfea1af098d843ee7e578e480cd658ac1a |
| 0x1000 | 0x1000 | `c_5ct_g.bin` | c_5ct_g.bin | 5ec461ec | acb11a8fbdbb3ab46068385fe465f681e3c824bd |
| 0x2000 | 0x1000 | `c_5bt_g.bin` | c_5bt_g.bin | 1c97d324 | c7966261f3a1d3296927e0b6ee1c58039fc53c1f |
| 0x3000 | 0x1000 | `c_5at_g.bin` | c_5at_g.bin | b9005ac0 | 3fe3599f6fa7c496f782053ddf7bacb453d197c4 |

Concatenation order for structural AOT:
```
cat c_5et_g.bin c_5ct_g.bin c_5bt_g.bin c_5at_g.bin > cpu.rom
```

Total CPU code size: 16 KiB (0x4000 bytes). This matches MAME `ROM_REGION(0x10000, "maincpu",0)` with ROM_LOAD at 0x0000-0x3FFF.

Sound CPU ROMs (I8035) retained for reference:
- `s_3i_b.bin` 0x0000-0x07FF, CRC 45a4ed06
- `s_3j_b.bin` 0x1000-0x17FF, CRC 4743fe92

Graphics and PROMs are not required for initial structural translation but are listed in MAME for completeness.

## Disassembly Status
Initial skeleton disassembly generated via `tools/convert.js`:
- `src/test.asm` - Test conversion from extracted ROM
- `src/test2.asm` - Conversion from c_5at_g.bin
- `src/dkong_initial.asm` - Initial conversion from dkong.dat

Current converter supports minimal opcodes:
- nop, ld a,imm8, ld b,imm8, jp imm16, ret

These files are exploratory structural translations, not validated final game code. The first pass
is intended to recover control flow, routine boundaries, data references, and hardware accesses.
Routines with a clear purpose may later be replaced by native 68030 implementations.

The converter still needs reachability-based disassembly, code/data separation, label generation,
explicit diagnostics for unknown instructions, and a reproducible ROM-input manifest. A full
one-for-one opcode table is not a prerequisite for native replacement, but all unresolved control
flow must be visible.

## Next Steps
1. Select and document the exact CPU ROM set, ordering, and load addresses.
2. Implement a buildable structural disassembler with labels and code/data separation.
3. Generate routine-level source references and unresolved-issue markers.
4. Identify high-confidence routines for native replacement and document their contracts.
5. Map memory regions and hardware effects to Falcon-side interfaces.
