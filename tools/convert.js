#!/usr/bin/env node
/**
 * Z80 → MC68000 converter skeleton for Donkey Kong Falcon030 port
 * Reuses mapping tables from C:\Arbeit\jsz80test\main.js
 * 
 * Usage: node tools/convert.js assets/roms/dkong.zip <output.asm>
 */

const fs = require('fs');
const path = require('path');

// --- Usable parts from jsz80test/main.js ---

const Z80Reg8Names = ["b","c","d","e","h","l","(hl)","a"];
const Z80Reg16Names = ["bc","de","hl","sp"];
const M68kDataRegisterNames = ["d1","d2","d3","d4","h","l","(a1)","d0"];
const M68kAddressRegisterNames = ["a2","a3","a1","a0"];
const M68kConditionCodeNames = ["ne","eq","cc","cs","po","pe","p","m"];

// Minimal opcode table – expand as needed
const Z80_OPCODES = {
  0x00: { name: 'nop', m68k: 'nop', rationale: '68030 nop is single-cycle, matches Z80 NOP timing' },
  0x3E: { name: 'ld a,imm8', m68k: (imm) => `move.b #0x${imm.toString(16).padStart(2,'0')},d0`, rationale: 'Z80 A maps to 68030 D0, immediate byte move preserves value' },
  0x06: { name: 'ld b,imm8', m68k: (imm) => `move.b #0x${imm.toString(16).padStart(2,'0')},d1`, rationale: 'Z80 B maps to 68030 D1 per jsz80test mapping' },
  0x32: { name: 'ld (nn),a', m68k: (addr) => `move.b d0,$${addr.toString(16).padStart(4,'0')}`, bytes:3, rationale: 'Byte store from D0 to absolute address; Z80 memory-mapped I/O handled as absolute' },
  0x3A: { name: 'ld a,(nn)', m68k: (addr) => `move.b $${addr.toString(16).padStart(4,'0')},d0`, bytes:3, rationale: 'Byte load into D0 mirrors Z80 A, 68030 can do absolute byte load' },
  0x0F: { name: 'rrca', m68k: 'ror.b d0', rationale: 'RRCA rotates A right through carry; 68030 ROR.B on D0 emulates rotate, carry handling deferred for AOT' },
  0x33: { name: 'inc sp', m68k: 'addq.l #1,a7', rationale: 'Z80 SP maps to 68030 A7, addq.l #1 is single-cycle increment' },
  0xC3: { name: 'jp imm16', m68k: (addr) => `jbra ${formatLabel(addr)}`, rationale: 'Unconditional branch to absolute label, 68030 jbra is direct equivalent' },
  0xC9: { name: 'ret', m68k: 'rts', rationale: 'Z80 RET maps to 68030 RTS' },
  0xD0: { name: 'ret nc', m68k: 'jsr Z80_RET_NC', rationale: 'RET NC requires Z80 carry flag. Static translation calls flag emulation stub Z80_RET_NC which tests Z80_FLAGS carry bit and returns conditionally.' },
  0xD8: { name: 'ret c', m68k: 'jsr Z80_RET_C', rationale: 'RET C requires Z80 carry flag. Static translation calls flag emulation stub Z80_RET_C which tests Z80_FLAGS carry bit and returns conditionally.' },
};

function formatLabel(addr) {
  return `L_${addr.toString(16).padStart(4,'0')}`;
}

// Simple ZIP handling – expects a raw binary ROM file for now
function readRom(filePath) {
  const data = fs.readFileSync(filePath);
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
    let m68kText = '/* TODO */';
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
      // unknown opcode
      advance = 1;
    }
    
    pc += advance;
    
    // Keep Z80 source as comment behind 68000 code per project rule
    const rationaleComment = rationale ? `  // why: ${rationale}` : '';
    const line = `        ${m68kText.padEnd(30)} | ; ${z80Text}${rationaleComment}`;
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
  '        section .text',
  '',
  ...disassemble(rom, 0, 512)
];

fs.writeFileSync(outputPath, asmLines.join('\n'));
console.log(`Wrote ${outputPath} with ${asmLines.length} lines`);
console.log('Note: This is a skeleton using the mapping tables from jsz80test/main.js.');
console.log('Expand Z80_OPCODES with full tables from main.js for production use.');
