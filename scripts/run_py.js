#!/usr/bin/env node
const { spawnSync } = require('child_process');

const args = process.argv.slice(2);
const isWin = process.platform === 'win32';
// On Windows try 'py' first (standard launcher); on Linux/CI try 'python' then 'python3'
const candidates = isWin ? ['py', 'python', 'python3'] : ['python', 'python3', 'py'];

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
