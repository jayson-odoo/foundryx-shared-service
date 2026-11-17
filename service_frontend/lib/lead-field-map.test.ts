import { describe, expect, it } from 'vitest';
import type { LeadField, LeadSourceItem } from '@/types/lead-capture';
import {
  fieldMapPayload,
  formMapRows,
  initialTargets,
  isFormId,
  storedMapQuestions,
  targetOptions,
  validateLeadFields,
} from './lead-field-map';

const fields: LeadField[] = [
  { key: 'name', label: 'Name', type: 'name' },
  { key: 'phone', label: 'Phone', type: 'phone' },
  { key: 'budget', label: 'Budget', type: 'text' },
  { key: 'notes', label: 'Lead notes', type: 'notes' },
];

const source = (over: Partial<LeadSourceItem> = {}): LeadSourceItem => ({
  id: 'src1',
  platform: 'facebook',
  name: 'Facebook Page',
  status: 'LIVE',
  pageId: '1',
  pageName: 'Sample Home Page',
  formsMode: 'all',
  needsMapping: [],
  fieldMap: {},
  lastLeadAt: null,
  createdAt: '2026-11-17T00:00:00Z',
  ...over,
});

describe('validateLeadFields', () => {
  it('flags bad and duplicate keys', () => {
    expect(validateLeadFields([...fields])).toEqual({});
    const errs = validateLeadFields([
      { key: '1bad', label: 'x', type: 'text' },
      { key: 'budget', label: 'a', type: 'text' },
      { key: 'budget', label: 'b', type: 'text' },
    ]);
    expect(Object.keys(errs)).toEqual(['0', '2']);
  });
});

describe('isFormId', () => {
  it('accepts digits only', () => {
    expect(isFormId(' 1234567890 ')).toBe(true);
    expect(isFormId('abc')).toBe(false);
    expect(isFormId('')).toBe(false);
  });
});

describe('formMapRows', () => {
  it('lists mapped forms and forms needing a map, with plain names', () => {
    const rows = formMapRows([
      source({
        fieldMap: { '*': { budget_q: 'budget' }, '111': { a: 'budget', b: 'phone' } },
        needsMapping: [{ formId: '222', formName: 'Show unit enquiry', unmappedCount: 3 }],
      }),
    ]);
    expect(rows.map((r) => [r.formName, r.mappedCount, r.status, r.unmappedCount])).toEqual([
      ['All forms', 1, 'MAPPED', null],
      ['Instant Form 111', 2, 'MAPPED', null],
      ['Show unit enquiry', 0, 'NEEDS_MAPPING', 3],
    ]);
    expect(rows[0].pageName).toBe('Sample Home Page');
  });
});

describe('initialTargets + targetOptions + payload', () => {
  const questions = [
    { key: 'full_name', label: 'Full name', type: 'FULL_NAME' },
    { key: 'what_is_your_budget', label: 'What is your budget?', type: 'CUSTOM' },
    { key: 'best_time', label: 'Best time to call', type: 'CUSTOM' },
  ];

  it('starts from the form map, then the all-forms map, else automatic / notes', () => {
    const start = initialTargets(
      questions,
      { '*': { best_time: 'budget' }, '222': { what_is_your_budget: 'budget' } },
      '222',
      fields,
    );
    expect(start).toEqual({ full_name: '', what_is_your_budget: 'budget', best_time: 'budget' });
  });

  it('shows an explicit map to the automatic field as that field, not blank', () => {
    const start = initialTargets(questions, { '222': { full_name: 'name' } }, '222', fields);
    expect(start.full_name).toBe('name');
    expect(targetOptions(questions[0], fields).map((o) => o.value)).toContain('name');
  });

  it('All forms lines are the stored question keys', () => {
    expect(storedMapQuestions({ '*': { budget_q: 'budget', best: 'budget' } }, '*').map((q) => q.key)).toEqual([
      'budget_q',
      'best',
    ]);
    expect(storedMapQuestions({}, '*')).toEqual([]);
  });

  it('drops a mapped target that is no longer a product field', () => {
    expect(initialTargets(questions, { '222': { best_time: 'gone' } }, '222', fields).best_time).toBe('');
  });

  it('names the default after what happens with no map', () => {
    expect(targetOptions(questions[0], fields)[0].label).toBe('Name (automatic)');
    expect(targetOptions(questions[0], fields).map((o) => o.value)).toEqual(['', 'name', 'phone', 'budget']);
    expect(targetOptions(questions[2], fields)[0].label).toBe('Leave in lead notes');
    expect(targetOptions(questions[2], fields).map((o) => o.value)).toEqual(['', 'name', 'phone', 'budget']);
  });

  it('sends every question, blank as null', () => {
    expect(fieldMapPayload(questions, { what_is_your_budget: 'budget' })).toEqual({
      full_name: null,
      what_is_your_budget: 'budget',
      best_time: null,
    });
  });
});
