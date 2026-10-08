#!/usr/bin/env node
/**
 * Reproducible CPU ROM build for Donkey Kong TKG-04
 * Concatenates the four CPU ROM files in MAME order to cpu.rom
 */

const fs = require('fs');
const path = require('path');

const base = path.resolve(__dirname, '..', 'assets', 'roms', 'extracted');
const out = path.join(base, 'cpu.rom');

const files = [
  'c_5et_g.bin',
  'c_5ct_g.bin',
  'c_5bt_g.bin',
  'c_5at_g.bin'
];

console.log('Building CPU ROM from selected set...');
let data = Buffer.alloc(0);
for (const f of files) {
  const p = path.join(base, f);
  if (!fs.existsSync(p)) {
    console.error(`Missing ${f}`);
    process.exit(1);
  }
  const buf = fs.readFileSync(p);
  console.log(`  ${f} ${buf.length} bytes`);
  data = Buffer.concat([data, buf]);
}

fs.writeFileSync(out, data);
console.log(`Wrote ${out} (${data.length} bytes)`);
console.log('ROM map:');
console.log('  0x0000-0x0FFF c_5et_g.bin');
console.log('  0x1000-0x1FFF c_5ct_g.bin');
console.log('  0x2000-0x2FFF c_5bt_g.bin');
console.log('  0x3000-0x3FFF c_5at_g.bin');
