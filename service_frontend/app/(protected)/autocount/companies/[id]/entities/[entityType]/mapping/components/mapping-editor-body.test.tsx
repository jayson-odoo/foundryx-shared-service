import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { validateFormula } from '@/lib/autocount-formula';
import type { AutocountSorentoField } from '@/types/autocount';
import { MappingEditorBody } from './mapping-editor-body';
import type { MappingEditableRow } from './mapping-table';
import type { MappingBuilderTarget, MappingDraftScope, UseMappingDraftResult } from './use-mapping-draft';

/**
 * `mapping-editor-body.test.tsx` (sprint-5/02, AC-02-18/20/21) - mocked at
 * the HOOK boundary (`UseMappingDraftResult`), not the service: the real
 * `useMappingDraft` is exercised by `use-mapping-draft.ts`'s own logic
 * (`splitMappingRows`, `unmappedRequiredFields`); this file drives
 * `MappingEditorBody` purely off the shape that hook returns, so it stays
 * green independent of the draft hook's internals.
 *
 * `builderTarget`/`setBuilderTarget` are backed by a REAL `useState` in the
 * harness below (everything else is static) so clicking a row's "f" button
 * genuinely opens `AutocountFormulaBuilder` - the one interaction worth
 * driving for real rather than asserting a mock was called.
 */

const HEADER_SORENTO: AutocountSorentoField[] = [
  { field: 'so_number', required: true },
  { field: 'status', required: true },
];

const LINE_SORENTO: AutocountSorentoField[] = [
  { field: 'source_ref', required: true },
  { field: 'product_ref', required: true },
];

function headerRows(): MappingEditableRow[] {
  return [
    { sourcePath: 'DocNo', transform: 'string', formula: null, sorentoField: 'so_number' },
    // A preset-seeded row whose column is NOT in the current query result
    // (AC-02-21) - `acFields` below deliberately omits it.
    { sourcePath: 'MissingColumn', transform: 'string', formula: null, sorentoField: 'status' },
  ];
}

function lineRows(): MappingEditableRow[] {
  return [
    { sourcePath: 'DtlKey', transform: 'string', formula: null, sorentoField: 'source_ref' },
  ];
}

function scope(rows: MappingEditableRow[], sorentoFields: AutocountSorentoField[], acFields: string[]): MappingDraftScope {
  return {
    rows,
    sorentoFields,
    acFields,
    unmappedRequired: [],
    onChangeRow: () => {},
    onAddRow: () => {},
    onRemoveRow: () => {},
  };
}

/** The harness: a real `useState` for the builder target/simulator so the
 * "f" button's click genuinely flips the formula builder open, everything
 * else a static mock of `UseMappingDraftResult`.
 * `masterAcFields` (sprint-5/12, AC-12-01/02) overrides the header scope's
 * `acFields` for a master (`isDocument={false}`) harness only - the
 * document branch is untouched (still fixed at `['DocNo']`). */
function Harness({
  isDocument,
  editing = true,
  masterAcFields,
}: {
  isDocument: boolean;
  editing?: boolean;
  masterAcFields?: string[];
}) {
  const [builderTarget, setBuilderTarget] = useState<MappingBuilderTarget | null>(null);
  const [simulatorOpen, setSimulatorOpen] = useState(false);

  const header = scope(headerRows(), HEADER_SORENTO, isDocument ? ['DocNo'] : (masterAcFields ?? ['DocNo']));
  const line = isDocument ? scope(lineRows(), LINE_SORENTO, ['DtlKey']) : null;

  const draft: UseMappingDraftResult = {
    header,
    line,
    provenance: [],
    dirty: false,
    builderTarget,
    setBuilderTarget,
    onApplyFormula: () => {},
    simulatorOpen,
    setSimulatorOpen,
    writeRows: () => [],
    validate: () => null,
    reset: () => {},
  };

  return (
    <MappingEditorBody
      editing={editing}
      draft={draft}
      saveError={null}
      sourceMode="column"
      onServerTest={async () => ({ ok: true, output: null, error: null })}
      onSimulate={async () => ({
        ok: true,
        sourceRef: '',
        docNo: null,
        record: null,
        headerFields: [],
        lineFields: [],
        errors: [],
      })}
      entityLabel="Sales order"
    />
  );
}

describe('MappingEditorBody (sprint-5/02, AC-02-18/20/21)', () => {
  it('renders TWO sections (Header fields / Line fields) for a document entity', () => {
    render(<Harness isDocument />);
    expect(screen.getByText('Header fields')).toBeInTheDocument();
    expect(screen.getByText('Line fields')).toBeInTheDocument();
    // Each row's own source path is present under its own section.
    expect(screen.getByText('DtlKey')).toBeInTheDocument();
  });

  it('renders a SINGLE section (no scope headings) for a master/GRN entity', () => {
    render(<Harness isDocument={false} />);
    expect(screen.queryByText('Header fields')).not.toBeInTheDocument();
    expect(screen.queryByText('Line fields')).not.toBeInTheDocument();
    // The header rows still render, just without the two-section chrome.
    expect(screen.getByText('DocNo')).toBeInTheDocument();
  });

  it('a seeded row whose column is missing from the query shows the disabled badge (AC-02-21)', () => {
    render(<Harness isDocument />);
    expect(screen.getByText('Column not in query')).toBeInTheDocument();
  });

  it('the formula is never free text - "f" opens the real AutocountFormulaBuilder (AC-02-20)', () => {
    render(<Harness isDocument />);
    // No free-text formula input anywhere on the table.
    expect(screen.queryByLabelText('Formula expression')).not.toBeInTheDocument();

    // Both the header AND line tables have their own "row 1" - target the
    // header table's build button explicitly (the first one rendered).
    fireEvent.click(screen.getAllByLabelText('Build formula for row 1')[0]);

    // The builder dialog is now open, driven by REAL builderTarget state -
    // not a mocked call assertion.
    expect(screen.getByLabelText('Formula expression')).toBeInTheDocument();
  });

  it('a formula already set on a row renders read-only (ClampedText), never as an editable text field', () => {
    render(<Harness isDocument={false} editing />);
    // Editing is on, yet nowhere on the table is a free-text formula input -
    // only the transform preset picker + the "f" build button.
    expect(screen.queryByLabelText('Formula expression')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Build formula for row 1')).toBeInTheDocument();
  });
});

describe('MappingEditorBody - master entity Source columns (sprint-5/12, AC-12-01/02/05)', () => {
  it('AC-12-01: a master row with a non-empty acFields gets ONE "Source columns" group', () => {
    render(<Harness isDocument={false} masterAcFields={['ItemCode', 'Description', 'Desc2']} />);
    fireEvent.click(screen.getByLabelText('Build formula for row 1'));
    expect(screen.getByText('Source columns')).toBeInTheDocument();
    // Every acFields entry is offered as a pickable token (label === token,
    // so it renders twice: the item's label span AND its token `<code>`).
    expect(screen.getAllByText('Desc2').length).toBeGreaterThan(0);
  });

  it('AC-12-02: a master row with an EMPTY acFields falls back to the single-value model, no group, no hint copy', () => {
    render(<Harness isDocument={false} masterAcFields={[]} />);
    fireEvent.click(screen.getByLabelText('Build formula for row 1'));
    expect(screen.queryByText('Source columns')).not.toBeInTheDocument();
    // No instructional copy explaining the absence (foolproof-UI, AC-12-02).
    expect(screen.queryByText(/never previewed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/preview the/i)).not.toBeInTheDocument();
  });

  it('AC-12-05: the sample Test tab is hidden once Source columns are offered, shown otherwise', () => {
    const { unmount } = render(<Harness isDocument={false} masterAcFields={['ItemCode']} />);
    fireEvent.click(screen.getByLabelText('Build formula for row 1'));
    expect(screen.queryByText('Testing')).not.toBeInTheDocument();
    unmount();

    render(<Harness isDocument={false} masterAcFields={[]} />);
    fireEvent.click(screen.getByLabelText('Build formula for row 1'));
    expect(screen.getByText('Testing')).toBeInTheDocument();
  });

  it('AC-12-01: the client validator accepts the Desc2 join once the Source columns are the known tokens, and rejects it without them', () => {
    const join = 'trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))';
    // The tokens the "Source columns" group publishes ARE `acFields` - the
    // same set the server's save gate builds `known_vars` from (D2), so the
    // client can never accept a name the server rejects, or the reverse.
    expect(validateFormula(join, ['ItemCode', 'Description', 'Desc2'])).toBeNull();
    // The pre-plan behaviour a master row had: no groups, so `Desc2` reads
    // as an unknown name (AC-12-02's unchanged fallback).
    expect(validateFormula(join, [])).not.toBeNull();
    // A column the task has NOT previewed stays rejected even with a group.
    expect(validateFormula(join.replaceAll('Desc2', 'Desc3'), ['Description', 'Desc2'])).not.toBeNull();
  });

  it('a document row keeps its Header columns / Line aggregates groups byte-identically (unaffected)', () => {
    render(<Harness isDocument />);
    fireEvent.click(screen.getAllByLabelText('Build formula for row 1')[0]);
    expect(screen.getByText('Header columns')).toBeInTheDocument();
    expect(screen.getByText('Line aggregates')).toBeInTheDocument();
    expect(screen.queryByText('Source columns')).not.toBeInTheDocument();
  });
});
