/**
 * `bindingSlotErrors` (tester O-4, plan 29 post-approval) - reads a server
 * 422's `{fieldErrors: {"bindings.body.0.text": "..."}}`, mapped by
 * `applyFieldErrors` onto RHF's nested error tree, back out as a flat,
 * index-aligned array `BindingEditor` can render per row. `TemplateBinding`
 * is a discriminated union (static | contactField), so a slot's error can
 * land on `.text`, `.fallback` or `.field` depending on which variant is
 * currently selected.
 */
import { describe, expect, it } from 'vitest';
import { bindingSlotErrors } from './broadcast-form-view';

describe('bindingSlotErrors', () => {
  it('reads a static-slot .text error at the matching index', () => {
    const errors = { bindings: { body: [{ text: { message: 'Static text is required.' } }, undefined] } };
    expect(bindingSlotErrors(errors, 'body', 2)).toEqual(['Static text is required.', undefined]);
  });

  it('reads a contactField-slot .fallback error', () => {
    const errors = { bindings: { body: [{ fallback: { message: 'A fallback value is required.' } }] } };
    expect(bindingSlotErrors(errors, 'body', 1)).toEqual(['A fallback value is required.']);
  });

  it('reads a contactField-slot .field error', () => {
    const errors = { bindings: { header: [{ field: { message: 'Unknown contact field.' } }] } };
    expect(bindingSlotErrors(errors, 'header', 1)).toEqual(['Unknown contact field.']);
  });

  it('returns an all-undefined array of the right length when there are no errors', () => {
    expect(bindingSlotErrors(undefined, 'buttons', 3)).toEqual([undefined, undefined, undefined]);
  });

  it('returns an all-undefined array when bindings errors exist for a DIFFERENT group', () => {
    const errors = { bindings: { body: [{ text: { message: 'x' } }] } };
    expect(bindingSlotErrors(errors, 'header', 1)).toEqual([undefined]);
  });
});
