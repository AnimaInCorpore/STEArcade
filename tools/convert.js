#!/usr/bin/env node
/**
 * Z80 → MC68000 converter skeleton for Donkey Kong Falcon030 port
 * Reuses mapping tables from C:\Arbeit\jsz80test\main.js
 * 
 * Usage: node tools/convert.js assets/roms/extracted/cpu.rom <output.asm>
 */

const fs = require('fs');
// --- Usable parts from jsz80test/main.js ---

const Z80Reg8Names = ["b","c","d","e","h","l","(hl)","a"];
const Z80Reg16Names = ["bc","de","hl","sp"];

// Minimal opcode table – expand as needed
const Z80_OPCODES = {
  0x00: { name: 'nop', m68k: 'nop', rationale: '68030 nop is single-cycle, matches Z80 NOP timing' },
  0x3E: { name: 'ld a,imm8', m68k: (imm) => `move.b #$${imm.toString(16).padStart(2,'0')},d0`, rationale: 'Z80 A maps to 68030 D0, immediate byte move preserves value' },
  0x06: { name: 'ld b,imm8', m68k: (imm) => `move.b #$${imm.toString(16).padStart(2,'0')},d1`, rationale: 'Z80 B maps to 68030 D1 per jsz80test mapping' },
  0x32: { name: 'ld (nn),a', m68k: (addr) => `move.b d0,$${addr.toString(16).padStart(4,'0')}`, bytes:3, rationale: 'Byte store from D0 to absolute address; Z80 memory-mapped I/O handled as absolute' },
  0x3A: { name: 'ld a,(nn)', m68k: (addr) => `move.b $${addr.toString(16).padStart(4,'0')},d0`, bytes:3, rationale: 'Byte load into D0 mirrors Z80 A, 68030 can do absolute byte load' },
  0x0F: { name: 'rrca', m68k: 'ror.b #1,d0', rationale: 'Structural rotate only; Z80 flag materialization remains a boundary obligation' },
  0x33: { name: 'inc sp', m68k: 'addq.l #1,a7', rationale: 'Z80 SP maps to 68030 A7, addq.l #1 is single-cycle increment' },
  0xC3: { name: 'jp imm16', m68k: (addr) => `bra ${formatLabel(addr)}`, rationale: 'Unconditional branch to an address label' },
  0xC9: { name: 'ret', m68k: 'rts', rationale: 'Z80 RET maps to 68030 RTS' },
  0xD0: { name: 'ret nc', m68k: 'jsr Z80_RET_NC', rationale: 'RET NC requires Z80 carry flag. Static translation calls flag emulation stub Z80_RET_NC which tests Z80_FLAGS carry bit and returns conditionally.' },
  0xD8: { name: 'ret c', m68k: 'jsr Z80_RET_C', rationale: 'RET C requires Z80 carry flag. Static translation calls flag emulation stub Z80_RET_C which tests Z80_FLAGS carry bit and returns conditionally.' },
  // Additional opcodes for init routine
  0x21: { name: 'ld hl,imm16', m68k: (addr) => `move.l #$${addr.toString(16).padStart(4,'0')},a1`, bytes:3, rationale: 'HL maps to A1 pointer for memory indirect' },
  0xAF: { name: 'xor a,a', m68k: 'clr.b d0', rationale: 'XOR A clears A, maps to CLR.B D0' },
  0x4F: { name: 'ld c,a', m68k: 'move.b d0,d2', rationale: 'C maps to D2' },
  0x77: { name: 'ld (hl),a', m68k: 'move.b d0,(a1)', rationale: 'Store A to memory pointed by HL/A1' },
  0x23: { name: 'inc hl', m68k: 'addq.l #1,a1', rationale: 'Increment HL pointer' },
  0x0D: { name: 'dec c', m68k: 'subq.b #1,d2', rationale: 'Decrement C' },
  0x20: { name: 'jr nz,e8', m68k: (rel) => `bne.s ${formatLabel(rel)}`, bytes:2, rationale: 'Relative branch if Z flag clear' },
  0x10: { name: 'djnz e8', m68k: (rel) => `dbne d1,${formatLabel(rel)}`, bytes:2, rationale: 'Assembler-valid structural placeholder; exact Z80 B-width semantics require validation' },
  0x18: { name: 'jr e8', m68k: (rel) => `bra.s ${formatLabel(rel)}`, bytes:2, rationale: 'Relative jump' },
  0x28: { name: 'jr z,e8', m68k: (rel) => `beq.s ${formatLabel(rel)}`, bytes:2, rationale: 'Relative jump if Z' },
  0x30: { name: 'jr nc,e8', m68k: (rel) => `bhs.s ${formatLabel(rel)}`, bytes:2, rationale: 'Relative jump if NC' },
  0x38: { name: 'jr c,e8', m68k: (rel) => `bcs.s ${formatLabel(rel)}`, bytes:2, rationale: 'Relative jump if C' },
  0x31: { name: 'ld sp,imm16', m68k: (addr) => `move.l #$${addr.toString(16).padStart(4,'0')},a7`, bytes:3, rationale: 'SP maps to A7' },
  0x34: { name: 'inc (hl)', m68k: 'addq.b #1,(a1)', rationale: 'Increment memory at HL' },
  0x35: { name: 'dec (hl)', m68k: 'subq.b #1,(a1)', rationale: 'Decrement memory at HL' },
  0x36: { name: 'ld (hl),imm8', m68k: (imm) => `move.b #$${imm.toString(16).padStart(2,'0')},(a1)`, bytes:2, rationale: 'Store immediate to HL' },
  0x3C: { name: 'inc a', m68k: 'addq.b #1,d0', rationale: 'Increment A' },
  0x3D: { name: 'dec a', m68k: 'subq.b #1,d0', rationale: 'Decrement A' },
  0xC1: { name: 'pop bc', m68k: 'move.l (a7)+,d3', rationale: 'Pop BC' },
  0xC5: { name: 'push bc', m68k: 'move.l d3,-(a7)', rationale: 'Push BC' },
  0xD1: { name: 'pop de', m68k: 'move.l (a7)+,d4', rationale: 'Pop DE' },
  0xD5: { name: 'push de', m68k: 'move.l d4,-(a7)', rationale: 'Push DE' },
  0xE1: { name: 'pop hl', m68k: 'move.l (a7)+,a1', rationale: 'Pop HL' },
  0xE5: { name: 'push hl', m68k: 'move.l a1,-(a7)', rationale: 'Push HL' },
  0xF1: { name: 'pop af', m68k: 'move.l (a7)+,d0', rationale: 'Pop AF' },
  0xF5: { name: 'push af', m68k: 'move.l d0,-(a7)', rationale: 'Push AF' },
  0xCD: { name: 'call imm16', m68k: (addr) => `jsr ${formatLabel(addr)}`, bytes:3, rationale: 'Call subroutine' },
  0xC9: { name: 'ret', m68k: 'rts', rationale: 'Z80 RET maps to 68030 RTS' },
  0xC0: { name: 'ret nz', m68k: 'jsr Z80_RET_NZ', rationale: 'RET NZ requires Z flag' },
  0xC8: { name: 'ret z', m68k: 'jsr Z80_RET_Z', rationale: 'RET Z requires Z flag' },
  0xD0: { name: 'ret nc', m68k: 'jsr Z80_RET_NC', rationale: 'RET NC requires Z80 carry flag. Static translation calls flag emulation stub Z80_RET_NC which tests Z80_FLAGS carry bit and returns conditionally.' },
  0xD8: { name: 'ret c', m68k: 'jsr Z80_RET_C', rationale: 'RET C requires Z80 carry flag. Static translation calls flag emulation stub Z80_RET_C which tests Z80_FLAGS carry bit and returns conditionally.' },
  0x01: { name: 'ld bc,imm16', m68k: (addr) => `move.w #$${addr.toString(16).padStart(4,'0')},d3`, bytes:3, rationale: 'BC maps to D3' },
  0x11: { name: 'ld de,imm16', m68k: (addr) => `move.w #$${addr.toString(16).padStart(4,'0')},d4`, bytes:3, rationale: 'DE maps to D4' },
  0x2A: { name: 'ld hl,(nn)', m68k: (addr) => `move.l $${addr.toString(16).padStart(4,'0')},a1`, bytes:3, rationale: 'Load HL from memory' },
  0x22: { name: 'ld (nn),hl', m68k: (addr) => `move.l a1,$${addr.toString(16).padStart(4,'0')}`, bytes:3, rationale: 'Store HL to memory' },
  0xC2: { name: 'jp nz,nn', m68k: (addr) => `beq.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
  0xCA: { name: 'jp z,nn', m68k: (addr) => `bne.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
  0xD2: { name: 'jp nc,nn', m68k: (addr) => `bcs.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
  0xDA: { name: 'jp c,nn', m68k: (addr) => `bhs.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
  0xE2: { name: 'jp po,nn', m68k: (addr) => `bra.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
  0xEA: { name: 'jp pe,nn', m68k: (addr) => `bra.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
  0xF2: { name: 'jp p,nn', m68k: (addr) => `bra.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
  0xFA: { name: 'jp m,nn', m68k: (addr) => `bra.s ${formatLabel(addr)}`, bytes:3, rationale: 'Conditional jump' },
};

function formatLabel(addr) {
  return `L_${addr.toString(16).padStart(4,'0').toUpperCase()}`;
}

// The converter consumes the validated raw CPU image. Archive extraction belongs to the ROM step.
function readRom(filePath) {
  const data = fs.readFileSync(filePath);
  if (data.length >= 2 && data[0] === 0x50 && data[1] === 0x4B) {
    throw new Error('ZIP input is not a CPU image; extract and concatenate the selected ROM set first');
  }
  return new Uint8Array(data);
}

// Very small disassembler for demo purposes
function collectJumpTargets(data, start = 0, maxBytes = 65536) {
  const targets = new Set();
  let pc = start;
  while (pc < data.length && pc < start + maxBytes) {
    const opcode = data[pc];
    // JP nn 0xC3
    if (opcode === 0xC3 && pc+2 < data.length) {
      const lo = data[pc+1];
      const hi = data[pc+2];
      const addr = lo | (hi << 8);
      targets.add(addr);
      pc += 3;
      continue;
    }
    // Simple advance for other opcodes (not accurate, just for target collection)
    // For demo, assume 1 byte, with some 2-byte immediates
    const entry = Z80_OPCODES[opcode];
    let advance = 1;
    if (entry && entry.bytes === 3) advance = 3;
    else if (opcode === 0x3E || opcode === 0x06) advance = 2;
    else if (opcode === 0xC3) advance = 3;
    pc += advance;
  }
  return targets;
}

function disassemble(data, start = 0, maxBytes = 256) {
  const lines = [];
  let pc = start;
  const jumpTargets = collectJumpTargets(data, 0, data.length);
  while (pc < data.length && pc < start + maxBytes) {
    if (jumpTargets.has(pc)) {
      lines.push(`L_${pc.toString(16).padStart(4,'0')}:`);
    }
    const opcode = data[pc];
    const entry = Z80_OPCODES[opcode];
    let z80Text = `db $${opcode.toString(16).padStart(2,'0')}`;
    let m68kText = 'illegal';
    let rationale = '';
    let advance = 1;
    
    if (entry) {
      rationale = entry.rationale || '';
      if (entry.bytes === 3) {
        const lo = data[pc+1] ?? 0;
        const hi = data[pc+2] ?? 0;
        const addr = lo | (hi << 8);
        z80Text = `${entry.name} $${addr.toString(16).padStart(4,'0')}`;
        m68kText = entry.m68k(addr);
        advance = 3;
      } else if (entry.bytes === 2) {
        const imm = data[pc+1] ?? 0;
        // signed relative offset for JR
        const signed = imm > 0x7F ? imm - 0x100 : imm;
        const target = pc + 2 + signed;
        z80Text = `${entry.name} $${target.toString(16).padStart(4,'0')}`;
        m68kText = entry.m68k(target);
        advance = 2;
      } else if (opcode === 0x3E || opcode === 0x06) {
        const imm = data[pc+1] ?? 0;
        z80Text = `${entry.name} $${imm.toString(16).padStart(2,'0')}`;
        m68kText = entry.m68k(imm);
        advance = 2;
      } else if (opcode === 0xC3) {
        const lo = data[pc+1] ?? 0;
        const hi = data[pc+2] ?? 0;
        const addr = lo | (hi << 8);
        z80Text = `${entry.name} $${addr.toString(16).padStart(4,'0')}`;
        m68kText = entry.m68k(addr);
        advance = 3;
      } else {
        z80Text = entry.name;
        m68kText = typeof entry.m68k === 'string' ? entry.m68k : String(entry.m68k);
        advance = 1;
      }
    } else {
      // Unknown opcode - stop visibly at the original address instead of creating an unresolved label.
      z80Text = `db $${opcode.toString(16).padStart(2,'0')}`;
      m68kText = 'illegal';
      advance = 1;
    }
    
    pc += advance;
    
    // Keep Z80 source as comment behind 68000 code per project rule
    const rationaleComment = rationale ? `why: ${rationale}` : '';
    const line = `        ${m68kText.padEnd(30)}; Z80: ${z80Text}${rationaleComment ? `; ${rationaleComment}` : ''}`;
    lines.push(line);
  }
  return lines;
}

// CLI
const [, , inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error('Usage: node tools/convert.js <rom.bin> <output.asm>');
  process.exit(1);
}

console.log(`Reading ${inputPath}...`);
const rom = readRom(inputPath);
const asmLines = [
  '; Donkey Kong Z80 -> MC68000 conversion',
  '; Generated by tools/convert.js',
  '; Rule: Z80 source kept as comment behind 68000 code',
  '',
  '        section text',
  '',
  ...disassemble(rom, 0, rom.length),
  ''
];

fs.writeFileSync(outputPath, asmLines.join('\n'));
console.log(`Wrote ${outputPath} with ${asmLines.length} lines`);
console.log('Note: This is a structural draft. Unknown opcodes are emitted as ILLEGAL and must be resolved before execution.');
