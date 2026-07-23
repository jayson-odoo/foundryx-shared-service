/**
 * Client/server PARITY harness (AC-16-01). This runs the SHARED golden matrix
 * (`service_backend/modules/autocount/formula_parity.json`) through the TS
 * evaluator; the pytest side runs the SAME file through the Python evaluator.
 * A divergence between `lib/autocount-formula.ts` and `modules/autocount/
 * formula.py` fails whichever side drifted — the matrix is the single source of
 * truth, never forked.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  FormulaParseError,
  FormulaRuntimeError,
  evaluateFormula,
  parseFormula,
  resultToJson,
} from './autocount-formula';

interface MatrixCase {
  formula: string;
  value: unknown;
  expected?: unknown;
  error?: boolean;
  parseError?: boolean;
}

const here = dirname(fileURLToPath(import.meta.url));
// lib/ → service_frontend/ → repo root → service_backend/modules/autocount/...
const matrixPath = resolve(
  here,
  '../../service_backend/modules/autocount/formula_parity.json',
);
const matrix = JSON.parse(readFileSync(matrixPath, 'utf8')) as { cases: MatrixCase[] };

function matrixEqual(expected: unknown, got: unknown): boolean {
  if (typeof expected === 'boolean' || typeof got === 'boolean') return expected === got;
  if (typeof expected === 'number' && typeof got === 'number') {
    return Math.abs(expected - got) < 1e-9;
  }
  return expected === got;
}

describe('formula parity matrix — TS side', () => {
  it('loaded the shared matrix', () => {
    expect(matrix.cases.length).toBeGreaterThan(40);
  });

  for (const c of matrix.cases) {
    const label = `${c.formula}  ⟨value=${JSON.stringify(c.value)}⟩`;
    if (c.parseError) {
      it(`parse-error: ${label}`, () => {
        expect(() => parseFormula(c.formula)).toThrow(FormulaParseError);
      });
      continue;
    }
    if (c.error) {
      it(`runtime-error: ${label}`, () => {
        expect(() => evaluateFormula(c.formula, c.value)).toThrow(FormulaRuntimeError);
      });
      continue;
    }
    it(`= ${JSON.stringify(c.expected)}: ${label}`, () => {
      const got = resultToJson(evaluateFormula(c.formula, c.value));
      expect(matrixEqual(c.expected, got)).toBe(true);
    });
  }
});
