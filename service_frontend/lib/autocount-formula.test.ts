import { describe, expect, it } from 'vitest';
import {
  FUNCTION_CATALOG,
  FormulaDate,
  FormulaParseError,
  FormulaRuntimeError,
  PRESETS,
  evaluateFormula,
  parseFormula,
  testFormula,
  validateFormula,
} from './autocount-formula';

describe('autocount-formula - TS twin of modules/autocount/formula.py', () => {
  describe('core expression semantics', () => {
    it('reads the value variable', () => expect(evaluateFormula('value', 'abc')).toBe('abc'));
    it('boolean preset on T/F', () => {
      expect(evaluateFormula('if(value == "T", true, false)', 'T')).toBe(true);
      expect(evaluateFormula('if(value == "T", true, false)', 'F')).toBe(false);
    });
    it('arithmetic + precedence', () => {
      expect(evaluateFormula('2 * 3 + 4', 'x')).toBe(10);
      expect(evaluateFormula('(2 + 3) * 4', 'x')).toBe(20);
      expect(evaluateFormula('-(2 + 3)', 'x')).toBe(-5);
    });
    it('numeric comparison via number()', () => {
      expect(evaluateFormula('number(value) > 1000', '30000.0')).toBe(true);
      expect(evaluateFormula('number(value) == 30000', '30000.00000000')).toBe(true);
    });
    it('string funcs', () => {
      expect(evaluateFormula('upper(value)', 'abc')).toBe('ABC');
      expect(evaluateFormula('replace(value, "-", "/")', '300-A001')).toBe('300/A001');
      expect(evaluateFormula('contains(value, "-A")', '300-A001')).toBe(true);
      expect(evaluateFormula('concat("AC-", value)', '300')).toBe('AC-300');
      expect(evaluateFormula('"code-" & value', '1')).toBe('code-1');
    });
    it('round is half-away-from-zero (not banker/Math.round)', () => {
      expect(evaluateFormula('round(2.5, 0)', 'x')).toBe(3);
      expect(evaluateFormula('round(-2.5, 0)', 'x')).toBe(-3);
      expect(evaluateFormula('round(number(value), 0)', '30000.6')).toBe(30001);
    });
    it('bool token conversion', () => {
      expect(evaluateFormula('bool(value)', 'yes')).toBe(true);
      expect(evaluateFormula('bool(value)', '0')).toBe(false);
    });
    it('default rescues null, not blank-value', () => {
      expect(evaluateFormula('default(value, "N/A")', 'x')).toBe('x');
      expect(evaluateFormula('default(null, "fallback")', 'x')).toBe('fallback');
    });
    it('type-aware equality has no bool/number trap', () => {
      expect(evaluateFormula('true == 1', 'x')).toBe(false);
      expect(evaluateFormula('1 == 1.0', 'x')).toBe(true);
    });
  });

  describe('dates - fixed token vocabulary', () => {
    it('parses the vendor format to a FormulaDate', () => {
      const d = evaluateFormula('parseDate(value, "yyyy/MM/dd HH:mm:ss")', '2026/03/18 16:03:21');
      expect(d).toBeInstanceOf(FormulaDate);
      expect((d as FormulaDate).iso()).toBe('2026-03-18T16:03:21Z');
    });
    it('the anchor: vendor format → ISO Z', () => {
      expect(
        evaluateFormula(
          'formatDate(parseDate(value, "yyyy/MM/dd HH:mm:ss"), "yyyy-MM-ddTHH:mm:ssZ")',
          '2026/03/18 16:03:21',
        ),
      ).toBe('2026-03-18T16:03:21Z');
    });
    it('reformats between token sets', () => {
      expect(
        evaluateFormula('formatDate(parseDate(value, "yyyy/MM/dd"), "dd/MM/yyyy")', '2026/03/18'),
      ).toBe('18/03/2026');
    });
    it('rejects an invalid month / a short field', () => {
      expect(() => evaluateFormula('parseDate(value, "yyyy/MM/dd")', '2026/13/01')).toThrow(
        FormulaRuntimeError,
      );
      expect(() => evaluateFormula('parseDate(value, "yyyy/MM/dd")', '2026/03/9')).toThrow(
        FormulaRuntimeError,
      );
    });
  });

  describe('fail closed', () => {
    it('unknown name / function / arity → parse error', () => {
      for (const bad of ['foo + 1', 'teleport(value)', 'upper()', 'round(value)', 'value = 1']) {
        expect(() => parseFormula(bad)).toThrow(FormulaParseError);
      }
    });
    it('runtime faults throw, never silently null', () => {
      expect(() => evaluateFormula('number(value)', 'abc')).toThrow(FormulaRuntimeError);
      expect(() => evaluateFormula('10 / value', '0')).toThrow(FormulaRuntimeError);
      expect(() => evaluateFormula('not value', 'T')).toThrow(FormulaRuntimeError);
    });
    it('validateFormula returns a message, not a throw', () => {
      expect(validateFormula('if(value == "T", true, false)')).toBeNull();
      expect(validateFormula('teleport(value)')).toContain('teleport');
    });
  });

  describe('testFormula (builder live preview)', () => {
    it('returns ok + output for a good formula', () => {
      expect(testFormula('upper(value)', 'abc')).toEqual({ ok: true, output: 'ABC', error: null });
    });
    it('returns a named error, never a throw', () => {
      const r = testFormula('number(value)', 'abc');
      expect(r.ok).toBe(false);
      expect(r.output).toBeNull();
      expect(r.error).toBeTruthy();
    });
    it('projects a FormulaDate to ISO', () => {
      const r = testFormula('parseDate(value, "yyyy/MM/dd")', '2026/03/18');
      expect(r.output).toBe('2026-03-18T00:00:00Z');
    });
  });

  describe('catalog + presets', () => {
    it('exposes the function catalog by category', () => {
      const names = new Set(FUNCTION_CATALOG.map((f) => f.name));
      for (const n of ['upper', 'number', 'if', 'parseDate', 'formatDate', 'bool']) {
        expect(names.has(n)).toBe(true);
      }
    });
    it('the boolean preset is the canonical T/F formula', () => {
      const boolean = PRESETS.find((p) => p.key === 'boolean');
      expect(boolean?.formula).toBe('if(value == "T", true, false)');
    });
  });
});
