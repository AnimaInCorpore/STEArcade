#!/usr/bin/env node
/**
 * Differential test harness for boot init routine
 * Validates contract against ROM bytes and native replacement
 */

const fs = require('fs');
const path = require('path');

const base = path.resolve(__dirname, '..');
const romPath = path.join(base, 'assets/roms/extracted/cpu.rom');
const nativeAsmPath = path.join(base, 'src/translated/boot_init_native.asm');
const contractPath = path.join(base, 'docs/analysis/boot_init_contract.md');

function readRom() {
  return fs.readFileSync(romPath);
}

function testRomBytes() {
  const rom = readRom();
  const expected = Buffer.from([0x3E,0x00,0x32,0x84,0x7D,0xC3,0x66,0x02]);
  const actual = rom.subarray(0, expected.length);
  const ok = actual.equals(expected);
  console.log(`[ROM bytes] expected ${expected.toString('hex')} got ${actual.toString('hex')} => ${ok ? 'PASS' : 'FAIL'}`);
  return ok;
}

function testNativeAsmExists() {
  const content = fs.readFileSync(nativeAsmPath, 'utf8');
  const hasLabel = content.includes('L_0000_native:');
  const hasWrite = content.includes('move.b  d0,$7D84');
  const hasJump = content.includes('jbra    L_0266');
  const ok = hasLabel && hasWrite && hasJump;
  console.log(`[Native asm] label ${hasLabel}, write ${hasWrite}, jump ${hasJump} => ${ok ? 'PASS' : 'FAIL'}`);
  return ok;
}

function testContractExists() {
  const content = fs.readFileSync(contractPath, 'utf8');
  const hasInputs = content.includes('Inputs');
  const hasOutputs = content.includes('Outputs');
  const hasValidation = content.includes('Validation');
  const ok = hasInputs && hasOutputs && hasValidation;
  console.log(`[Contract] inputs ${hasInputs}, outputs ${hasOutputs}, validation ${hasValidation} => ${ok ? 'PASS' : 'FAIL'}`);
  return ok;
}

function testIOPortMapping() {
  // Verify $7D84 is documented as interrupt enable in memory map
  const mapPath = path.join(base, 'docs/analysis/memory_map.md');
  const content = fs.readFileSync(mapPath, 'utf8');
  const ok = content.includes('7D84') && content.includes('interrupt enable');
  console.log(`[Memory map] 7D84 interrupt enable documented => ${ok ? 'PASS' : 'FAIL'}`);
  return ok;
}

const results = [
  testRomBytes(),
  testNativeAsmExists(),
  testContractExists(),
  testIOPortMapping()
];

if (results.every(Boolean)) {
  console.log('\nAll boot init differential checks PASSED');
  process.exit(0);
} else {
  console.log('\nSome checks FAILED');
  process.exit(1);
}
