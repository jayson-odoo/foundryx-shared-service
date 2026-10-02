import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutocountCompany } from '@/types/autocount';
import { IssueKeyDialog } from './issue-key-dialog';

const issuePullKey = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: { issuePullKey: (...a: unknown[]) => issuePullKey(...a) },
}));

// Stub the MultiSelect popover with a flat set of toggle buttons - the
// popover internals aren't under test here, the dialog's issue/reveal/clear
// flow is (mirrors `webhook-endpoint-dialog.test.tsx`'s established pattern
// for a MultiSelect nested inside a Dialog).
vi.mock('@/components/platform/multi-select', () => ({
  MultiSelect: ({
    options,
    value,
    onChange,
  }: {
    options: { label: string; value: string }[];
    value: string[];
    onChange: (v: string[]) => void;
  }) => (
    <div>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() =>
            onChange(value.includes(o.value) ? value.filter((x) => x !== o.value) : [...value, o.value])
          }
        >
          {`toggle ${o.label}`}
        </button>
      ))}
    </div>
  ),
}));

const FULL_KEY = 'fxa_live_abcdefabcdefabcdefabcdefabcdefabcd';

const COMPANIES: AutocountCompany[] = [
  {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED',
    companyName: 'AED',
    name: 'AED Sorento',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-2',
    sorentoCompanyCode: 'SRT',
    createdAt: null,
    sourceKind: 'http',
    documentPrerequisites: [],
  },
];

beforeEach(() => {
  issuePullKey.mockReset();
  issuePullKey.mockResolvedValue({
    key: {
      id: 'pull-key-1',
      name: 'Production',
      companyIds: ['c1'],
      keyPrefix: 'fxa_live_ab',
      createdAt: '2026-09-20T00:00:00Z',
      lastUsedAt: null,
      revokedAt: null,
    },
    plaintext: FULL_KEY,
  });
});

/** Controlled harness so a Cancel/Done close, then a reopen, is observable. */
function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(true)}>reopen</button>
      <IssueKeyDialog open={open} onOpenChange={setOpen} companies={COMPANIES} onIssued={() => {}} />
    </>
  );
}

describe('IssueKeyDialog (AC-10-28/38)', () => {
  it('mint is disabled until a name AND at least one company are picked', () => {
    render(<Harness />);
    const issueBtn = screen.getByRole('button', { name: 'Issue key' });
    expect(issueBtn).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Production' } });
    expect(issueBtn).toBeDisabled();
    fireEvent.click(screen.getByText('toggle AED Sorento'));
    expect(issueBtn).not.toBeDisabled();
  });

  it('reveals the plaintext exactly once with a copy control', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Production' } });
    fireEvent.click(screen.getByText('toggle AED Sorento'));
    fireEvent.click(screen.getByRole('button', { name: 'Issue key' }));

    await waitFor(() => expect(screen.getByDisplayValue(FULL_KEY)).toBeInTheDocument());
    expect(issuePullKey).toHaveBeenCalledWith({ name: 'Production', companyIds: ['c1'] });
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument();
  });

  it('closing the dialog clears the revealed plaintext from state (never persisted)', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Production' } });
    fireEvent.click(screen.getByText('toggle AED Sorento'));
    fireEvent.click(screen.getByRole('button', { name: 'Issue key' }));
    await waitFor(() => screen.getByDisplayValue(FULL_KEY));

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByDisplayValue(FULL_KEY)).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'reopen' }));
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue(''));
    expect(screen.queryByDisplayValue(FULL_KEY)).not.toBeInTheDocument();
  });
});
