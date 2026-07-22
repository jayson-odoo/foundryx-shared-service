import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  AutocountMappingRow,
  AutocountSorentoField,
} from '@/types/autocount';
import {
  MappingTable,
  unmappedRequiredFields,
  type MappingEditableRow,
} from './mapping-table';

const SORENTO: AutocountSorentoField[] = [
  { field: 'code', required: true },
  { field: 'name', required: true },
  { field: 'is_active', required: true },
  { field: 'email', required: false },
  { field: 'phone_number', required: false },
];

const AC_FIELDS = ['AccNo', 'CompanyName', 'EmailAddress', 'Mobile'];

const PROVENANCE: AutocountMappingRow[] = [
  {
    sourcePath: 'Data.0.LastModified',
    transform: 'slash_datetime',
    sorentoField: null,
    canonicalField: 'last_modified',
    scope: 'header',
    isRequired: false,
    isEnabled: true,
  },
];

function rows(): MappingEditableRow[] {
  return [
    { sourcePath: 'AccNo', transform: 'string', sorentoField: 'code' },
    { sourcePath: 'CompanyName', transform: 'string', sorentoField: 'name' },
  ];
}

function renderTable(editing: boolean, over: Partial<React.ComponentProps<typeof MappingTable>> = {}) {
  return render(
    <MappingTable
      editing={editing}
      rows={rows()}
      provenanceRows={PROVENANCE}
      sorentoFields={SORENTO}
      acFields={AC_FIELDS}
      onChangeRow={vi.fn()}
      onAddRow={vi.fn()}
      onRemoveRow={vi.fn()}
      {...over}
    />,
  );
}

describe('unmappedRequiredFields', () => {
  it('flags a required Sorento field with no source row (AC-15-44)', () => {
    // code + name mapped, is_active is not → warned.
    expect(unmappedRequiredFields(rows(), SORENTO)).toEqual(['is_active']);
  });

  it('is empty when every required field is mapped', () => {
    const full = [...rows(), { sourcePath: 'IsActive', transform: 't_f_bool', sorentoField: 'is_active' }];
    expect(unmappedRequiredFields(full, SORENTO)).toEqual([]);
  });

  it('never flags an optional field', () => {
    expect(unmappedRequiredFields([], [{ field: 'email', required: false }])).toEqual([]);
  });
});

describe('MappingTable read mode', () => {
  it('renders plain values, no pickers and no remove buttons', () => {
    renderTable(false);
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByRole('button', { name: /remove row/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /add field/i })).toBeNull();
    // The Sorento field shows its human label, never the raw canonical key.
    expect(screen.getByText('Code')).toBeInTheDocument();
  });

  it('always shows provenance rows as non-deliverable', () => {
    renderTable(false);
    expect(screen.getByText('Not delivered to Sorento')).toBeInTheDocument();
    expect(screen.getByText('Data.0.LastModified')).toBeInTheDocument();
  });
});

describe('MappingTable edit mode', () => {
  it('renders a searchable picker per cell and an Add field button', () => {
    renderTable(true);
    // 2 rows × 3 pickers (source, transform, target) = 6 comboboxes.
    expect(screen.getAllByRole('combobox').length).toBe(6);
    expect(screen.getByRole('button', { name: /add field/i })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /remove row/i }).length).toBe(2);
  });

  it('offers ONLY accepted Sorento targets, and never a duplicate (AC-15-42)', () => {
    renderTable(true);
    // Open the Sorento picker for row 1 (its own target `code` + the unused ones;
    // `name` is used by row 2 so it must NOT appear).
    const trigger = screen.getByRole('combobox', { name: 'Sorento field for row 1' });
    fireEvent.click(trigger);
    const listbox = screen.getByRole('listbox');
    const items = within(listbox).getAllByRole('option').map((o) => o.textContent);
    // code (own) + is_active/email/phone_number (unused). name is taken by row 2.
    expect(items).toEqual(['Code *', 'Is active *', 'Email', 'Phone number']);
    // The already-used `name` target is NOT offered again — no duplicate possible.
    expect(items.some((t) => t === 'Name *')).toBe(false);
  });

  it('disables Add field once every accepted target is used', () => {
    const full = [
      { sourcePath: 'AccNo', transform: 'string', sorentoField: 'code' },
      { sourcePath: 'CompanyName', transform: 'string', sorentoField: 'name' },
      { sourcePath: 'IsActive', transform: 't_f_bool', sorentoField: 'is_active' },
      { sourcePath: 'EmailAddress', transform: 'string', sorentoField: 'email' },
      { sourcePath: 'Mobile', transform: 'string', sorentoField: 'phone_number' },
    ];
    renderTable(true, { rows: full });
    expect(screen.getByRole('button', { name: /add field/i })).toBeDisabled();
  });

  it('fires onAddRow / onRemoveRow', () => {
    const onAddRow = vi.fn();
    const onRemoveRow = vi.fn();
    renderTable(true, { onAddRow, onRemoveRow });
    fireEvent.click(screen.getByRole('button', { name: /add field/i }));
    expect(onAddRow).toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: /remove row/i })[0]);
    expect(onRemoveRow).toHaveBeenCalledWith(0);
  });
});
