#!/usr/bin/env node
const { spawnSync } = require('child_process');

const args = process.argv.slice(2);
const isWin = process.platform === 'win32';
// Try 'python' first (or active environment), then standard launcher candidates
const candidates = isWin ? ['python', 'py', 'python3'] : ['python', 'python3', 'py'];

let result = null;
for (const cmd of candidates) {
  result = spawnSync(cmd, args, { stdio: 'inherit' });
  if (!result.error) {
    process.exit(result.status ?? 0);
  }
}

console.error(`Error: Could not execute Python. Tried: ${candidates.join(', ')}`);
if (result && result.error) {
  console.error(result.error);
}
process.exit(1);
