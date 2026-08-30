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
    formula: null,
    sorentoField: null,
    canonicalField: 'last_modified',
    scope: 'header',
    isRequired: false,
    isEnabled: true,
  },
];

function rows(): MappingEditableRow[] {
  return [
    { sourcePath: 'AccNo', transform: 'string', formula: null, sorentoField: 'code' },
    { sourcePath: 'CompanyName', transform: 'string', formula: null, sorentoField: 'name' },
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
      onBuildRow={vi.fn()}
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
    const full = [
      ...rows(),
      { sourcePath: 'IsActive', transform: 't_f_bool', formula: null, sorentoField: 'is_active' },
    ];
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
    // The already-used `name` target is NOT offered again - no duplicate possible.
    expect(items.some((t) => t === 'Name *')).toBe(false);
  });

  it('disables Add field once every accepted target is used', () => {
    const full = [
      { sourcePath: 'AccNo', transform: 'string', formula: null, sorentoField: 'code' },
      { sourcePath: 'CompanyName', transform: 'string', formula: null, sorentoField: 'name' },
      { sourcePath: 'IsActive', transform: 't_f_bool', formula: null, sorentoField: 'is_active' },
      { sourcePath: 'EmailAddress', transform: 'string', formula: null, sorentoField: 'email' },
      { sourcePath: 'Mobile', transform: 'string', formula: null, sorentoField: 'phone_number' },
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

  it('opens the formula builder for a row (AC-16-11)', () => {
    const onBuildRow = vi.fn();
    renderTable(true, { onBuildRow });
    fireEvent.click(screen.getAllByRole('button', { name: /build formula for row/i })[1]);
    expect(onBuildRow).toHaveBeenCalledWith(1);
  });
});

describe('MappingTable formula display (AC-16-10)', () => {
  it('shows an authored formula under its preset in read mode', () => {
    renderTable(false, {
      rows: [
        {
          sourcePath: 'IsActive',
          transform: 't_f_bool',
          formula: 'if(value == "T", true, false)',
          sorentoField: 'is_active',
        },
      ],
    });
    expect(screen.getByText('Boolean')).toBeInTheDocument();
    expect(screen.getByText('if(value == "T", true, false)')).toBeInTheDocument();
  });

  it('keeps a passthrough row simple - preset label, no formula clutter', () => {
    renderTable(false, {
      rows: [{ sourcePath: 'AccNo', transform: 'string', formula: null, sorentoField: 'code' }],
    });
    expect(screen.getByText('Text')).toBeInTheDocument();
  });
});

describe('column source mode (plan 22 S2, AC-22-09)', () => {
  it('offers ONLY the result columns - no free-typed path, no custom item', () => {
    renderTable(true, { sourceMode: 'column', acFields: ['AccNo', 'CompanyName'] });
    expect(screen.getByText('Source column')).toBeInTheDocument();
    const picker = screen.getByRole('combobox', { name: 'Source column for row 1' });
    fireEvent.click(picker);
    fireEvent.change(screen.getByPlaceholderText('Search columns'), {
      target: { value: 'Data.0.Nope' },
    });
    expect(screen.queryByText(/Use "Data\.0\.Nope"/)).not.toBeInTheDocument();
  });

  it('is disabled until the task has result columns to offer', () => {
    renderTable(true, { sourceMode: 'column', acFields: [] });
    expect(screen.getByRole('combobox', { name: 'Source column for row 1' })).toBeDisabled();
  });

  it('keeps the API path mode unchanged by default', () => {
    renderTable(true);
    expect(screen.getByText('AutoCount field')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'AutoCount source for row 1' })).toBeInTheDocument();
  });
});
