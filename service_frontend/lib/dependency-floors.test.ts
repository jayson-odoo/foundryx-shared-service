import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// Minimum patch levels for the framework packages, read from the lockfile
// because that is what the production image installs. Raising these is always
// fine. Lowering one needs a reason in the PR.
const FLOORS: Record<string, string> = {
  next: '15.3.9',
  react: '19.2.9',
  'react-dom': '19.2.9',
};

type LockEntry = { version: string };

function installedVersion(name: string): string {
  const lock = JSON.parse(
    readFileSync(resolve(process.cwd(), 'package-lock.json'), 'utf8'),
  ) as { packages: Record<string, LockEntry> };
  return lock.packages[`node_modules/${name}`].version;
}

function atLeast(version: string, floor: string): boolean {
  const have = version.split('.').map(Number);
  const want = floor.split('.').map(Number);
  for (let i = 0; i < 3; i += 1) {
    if (have[i] !== want[i]) return have[i] > want[i];
  }
  return true;
}

describe('framework dependency floors', () => {
  it.each(Object.entries(FLOORS))('%s is at or above %s', (name, floor) => {
    const version = installedVersion(name);
    expect(atLeast(version, floor), `${name} is ${version}`).toBe(true);
  });

  it('compares versions numerically', () => {
    expect(atLeast('15.3.10', '15.3.9')).toBe(true);
    expect(atLeast('15.10.0', '15.3.9')).toBe(true);
    expect(atLeast('15.3.4', '15.3.9')).toBe(false);
    expect(atLeast('15.3.9', '15.3.9')).toBe(true);
  });
});
