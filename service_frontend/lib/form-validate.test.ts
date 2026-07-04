/**
 * Form runtime validation + visibility (plan sprint-3/01, D14) — required-if-
 * visible, hidden-key dropping, the per-type validator matrix, repeater rows,
 * address, and computed live recompute + exclusion of hidden refs.
 */
import { describe, expect, it } from 'vitest';
import {
  computeValue,
  pageOfKey,
  validateAll,
  validatePage,
  visibleAnswers,
  visibleFieldSet,
} from './form-validate';
import type { FormDocument, FormField } from '@/types/forms';
import { FORM_SCHEMA_VERSION } from '@/types/forms';

/** Build a single-page doc from a flat field list. */
function doc(fields: FormField[], pages?: FormField[][]): FormDocument {
  if (pages) {
    return {
      schemaVersion: FORM_SCHEMA_VERSION,
      pages: pages.map((pf, i) => ({
        id: `pg${i}`,
        sections: [{ id: `sec${i}`, fields: pf }],
      })),
    };
  }
  return {
    schemaVersion: FORM_SCHEMA_VERSION,
    pages: [{ id: 'pg0', sections: [{ id: 'sec0', fields }] }],
  };
}

function field(over: Partial<FormField> & Pick<FormField, 'type' | 'key'>): FormField {
  return { id: `fld_${over.key}`, label: over.key ?? 'F', ...over };
}

describe('required applies only when visible', () => {
  const d = doc([
    field({ type: 'yesno', key: 'hasPet' }),
    field({
      type: 'text',
      key: 'petName',
      required: true,
      conditionsJson: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', fact: 'answers.hasPet', operator: 'is_true', value: true, valueKind: 'literal' }],
      },
    }),
  ]);

  it('skips required when the field is hidden', () => {
    expect(validateAll(d, { hasPet: false })).toEqual({});
  });

  it('enforces required when the field is shown', () => {
    expect(validateAll(d, { hasPet: true })).toEqual({ petName: 'This field is required.' });
    expect(validateAll(d, { hasPet: true, petName: 'Rex' })).toEqual({});
  });
});

describe('visibleFieldSet + visibleAnswers', () => {
  const d = doc([
    field({ type: 'yesno', key: 'subscribe' }),
    field({
      type: 'email',
      key: 'newsletterEmail',
      conditionsJson: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', fact: 'answers.subscribe', operator: 'is_true', value: true, valueKind: 'literal' }],
      },
    }),
  ]);

  it('drops hidden keys from the visible set and answers', () => {
    const answers = { subscribe: false, newsletterEmail: 'a@b.com' };
    expect(visibleFieldSet(d, answers)).toEqual(new Set(['subscribe']));
    expect(visibleAnswers(d, answers)).toEqual({ subscribe: false });
  });

  it('keeps a hidden answer locally but restores it once shown again', () => {
    const answers = { subscribe: true, newsletterEmail: 'a@b.com' };
    expect(visibleAnswers(d, answers)).toEqual(answers);
  });
});

describe('text validation matrix', () => {
  it('min/max length', () => {
    const d = doc([field({ type: 'text', key: 't', text: { minLength: 3, maxLength: 5 } })]);
    expect(validateAll(d, { t: 'ab' }).t).toContain('at least 3');
    expect(validateAll(d, { t: 'abcdef' }).t).toContain('at most 5');
    expect(validateAll(d, { t: 'abcd' })).toEqual({});
  });

  it('pattern with custom message', () => {
    const d = doc([
      field({ type: 'text', key: 't', text: { pattern: '^[A-Z]+$', patternMessage: 'Caps only.' } }),
    ]);
    expect(validateAll(d, { t: 'abc' }).t).toBe('Caps only.');
    expect(validateAll(d, { t: 'ABC' })).toEqual({});
  });
});

describe('format validation', () => {
  it('email', () => {
    const d = doc([field({ type: 'email', key: 'e' })]);
    expect(validateAll(d, { e: 'nope' }).e).toContain('valid email');
    expect(validateAll(d, { e: 'x@y.com' })).toEqual({});
  });
  it('url', () => {
    const d = doc([field({ type: 'url', key: 'u' })]);
    expect(validateAll(d, { u: 'not a url' }).u).toContain('valid URL');
    expect(validateAll(d, { u: 'https://x.com' })).toEqual({});
  });
  it('phone', () => {
    const d = doc([field({ type: 'phone', key: 'p' })]);
    expect(validateAll(d, { p: '123' }).p).toContain('valid phone');
    expect(validateAll(d, { p: '+14155552671' })).toEqual({});
  });
});

describe('number validation', () => {
  it('min/max/step', () => {
    const d = doc([field({ type: 'number', key: 'n', number: { min: 0, max: 10, step: 2 } })]);
    expect(validateAll(d, { n: -1 }).n).toContain('at least 0');
    expect(validateAll(d, { n: 11 }).n).toContain('at most 10');
    expect(validateAll(d, { n: 3 }).n).toContain('steps of 2');
    expect(validateAll(d, { n: 4 })).toEqual({});
  });
  it('rejects non-numeric', () => {
    const d = doc([field({ type: 'number', key: 'n' })]);
    expect(validateAll(d, { n: 'abc' }).n).toContain('valid number');
  });
});

describe('choice membership', () => {
  const options = { kind: 'static' as const, items: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }] };
  it('select rejects an off-list value', () => {
    const d = doc([field({ type: 'select', key: 's', options })]);
    expect(validateAll(d, { s: 'zzz' }).s).toContain('valid option');
    expect(validateAll(d, { s: 'a' })).toEqual({});
  });
  it('multiselect rejects any off-list value', () => {
    const d = doc([field({ type: 'multiselect', key: 'm', options })]);
    expect(validateAll(d, { m: ['a', 'zzz'] }).m).toContain('valid option');
    expect(validateAll(d, { m: ['a', 'b'] })).toEqual({});
  });
});

describe('rating + yesno + date', () => {
  it('rating bounds', () => {
    const d = doc([field({ type: 'rating', key: 'r', rating: { max: 5 } })]);
    expect(validateAll(d, { r: 6 }).r).toContain('rating');
    expect(validateAll(d, { r: 4 })).toEqual({});
  });
  it('date parses', () => {
    const d = doc([field({ type: 'date', key: 'd' })]);
    expect(validateAll(d, { d: 'not-a-date' }).d).toContain('valid date');
    expect(validateAll(d, { d: '2026-06-10' })).toEqual({});
  });
});

describe('address validation', () => {
  it('requires line1/city/country when required', () => {
    const d = doc([field({ type: 'address', key: 'a', required: true })]);
    expect(validateAll(d, { a: {} }).a).toContain('required');
    expect(validateAll(d, { a: { line1: 'x' } }).a).toContain('City');
    expect(validateAll(d, { a: { line1: 'x', city: 'y' } }).a).toContain('Country');
    expect(validateAll(d, { a: { line1: 'x', city: 'y', country: 'GB' } })).toEqual({});
  });
});

describe('repeater validation', () => {
  const repeater = {
    fields: [
      { id: 's1', type: 'text' as const, key: 'name', label: 'Name', required: true },
      { id: 's2', type: 'number' as const, key: 'qty', label: 'Qty' },
    ],
    minRows: 1,
    maxRows: 2,
  };

  it('enforces row bounds', () => {
    const d = doc([field({ type: 'repeater', key: 'items', repeater })]);
    expect(validateAll(d, { items: [] }).items).toContain('at least 1');
    expect(
      validateAll(d, {
        items: [{ name: 'a' }, { name: 'b' }, { name: 'c' }],
      }).items,
    ).toContain('at most 2');
  });

  it('keys sub-field errors by key.row.subKey', () => {
    const d = doc([field({ type: 'repeater', key: 'items', repeater })]);
    const errors = validateAll(d, { items: [{ name: '', qty: 'x' }] });
    expect(errors['items.0.name']).toContain('required');
    expect(errors['items.0.qty']).toContain('valid number');
  });
});

describe('file validation', () => {
  it('maxCount client check', () => {
    const d = doc([field({ type: 'file', key: 'f', file: { maxCount: 1 } })]);
    const two = [
      { key: 'local:1', name: 'a.pdf', size: 10, mime: 'application/pdf' },
      { key: 'local:2', name: 'b.pdf', size: 10, mime: 'application/pdf' },
    ];
    expect(validateAll(d, { f: two }).f).toContain('at most 1');
  });
});

describe('computed fields', () => {
  const d = doc([
    field({ type: 'number', key: 'qty' }),
    field({ type: 'number', key: 'unitPrice' }),
    field({ type: 'computed', key: 'total', computed: { expression: 'qty * unitPrice' } }),
  ]);

  it('recomputes live and is never validated', () => {
    expect(validateAll(d, { qty: 2, unitPrice: 3 })).toEqual({});
    const total = computeValue(d.pages[0].sections[0].fields[2], { qty: 2, unitPrice: 3 });
    expect(total).toBe(6);
  });

  it('appears in visibleAnswers recomputed; excludes hidden ref contributions', () => {
    const out = visibleAnswers(d, { qty: 4, unitPrice: 5 });
    expect(out.total).toBe(20);
  });

  it('computed referencing a hidden field is null when that ref is absent', () => {
    const cond = doc([
      field({ type: 'yesno', key: 'apply' }),
      field({
        type: 'number',
        key: 'amount',
        conditionsJson: {
          kind: 'group',
          combinator: 'and',
          rules: [{ kind: 'condition', fact: 'answers.apply', operator: 'is_true', value: true, valueKind: 'literal' }],
        },
      }),
      field({ type: 'computed', key: 'fee', computed: { expression: 'amount * 2' } }),
    ]);
    // amount hidden + absent → fee null in the visible set.
    const out = visibleAnswers(cond, { apply: false });
    expect(out).toEqual({ apply: false, fee: null });
  });
});

describe('paged validation + pageOfKey', () => {
  const d = doc([], [
    [field({ type: 'text', key: 'a', required: true })],
    [field({ type: 'text', key: 'b', required: true })],
  ]);

  it('validatePage scopes to one page', () => {
    expect(validatePage(d, 0, {})).toEqual({ a: 'This field is required.' });
    expect(validatePage(d, 1, {})).toEqual({ b: 'This field is required.' });
  });

  it('pageOfKey finds the right page incl. repeater nested keys', () => {
    expect(pageOfKey(d, 'a')).toBe(0);
    expect(pageOfKey(d, 'b')).toBe(1);
    expect(pageOfKey(d, 'b.0.x')).toBe(1);
    expect(pageOfKey(d, 'missing')).toBe(-1);
  });
});
