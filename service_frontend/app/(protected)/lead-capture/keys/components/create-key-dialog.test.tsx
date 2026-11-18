import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CreateKeyDialog } from './create-key-dialog';

const createKey = vi.fn();
vi.mock('@/services/lead-capture-service', () => ({
  leadCaptureService: { createKey: (...a: unknown[]) => createKey(...a) },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const FULL = 'fxl_live_secretvalue1234';

function Harness({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(true)}>reopen</button>
      <CreateKeyDialog open={open} onOpenChange={setOpen} onCreated={onCreated} />
    </>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  createKey.mockResolvedValue({
    id: 'k1',
    name: 'CRM sync',
    keyMasked: 'fxl_live_****1234',
    createdAt: '2026-11-17T00:00:00Z',
    lastUsedAt: null,
    revokedAt: null,
    key: FULL,
  });
});

describe('CreateKeyDialog', () => {
  it('creates with the name and shows the full key once', async () => {
    const onCreated = vi.fn();
    render(<Harness onCreated={onCreated} />);
    const create = screen.getByRole('button', { name: 'Create' });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Name *'), { target: { value: ' CRM sync ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(screen.getByLabelText('Key')).toHaveValue(FULL));
    expect(createKey).toHaveBeenCalledWith('CRM sync');
    expect(onCreated).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByDisplayValue(FULL)).not.toBeInTheDocument());
    fireEvent.click(screen.getByText('reopen'));
    await waitFor(() => expect(screen.getByLabelText('Name *')).toHaveValue(''));
    expect(screen.queryByDisplayValue(FULL)).not.toBeInTheDocument();
  });
});
