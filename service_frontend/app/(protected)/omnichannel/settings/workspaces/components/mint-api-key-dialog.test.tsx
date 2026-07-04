import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MintApiKeyDialog } from './mint-api-key-dialog';

const mint = vi.fn();

vi.mock('@/services/api-keys-service', () => ({
  apiKeysService: {
    mint: (...a: unknown[]) => mint(...a),
    revoke: vi.fn(),
    list: vi.fn(),
  },
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const FULL_KEY = 'fxw_live_abcd1234thisisthesecrettail';

beforeEach(() => {
  vi.clearAllMocks();
  mint.mockResolvedValue({
    key: {
      id: 'key-001',
      workspaceId: 'wsp-001',
      name: 'Production',
      keyPrefix: 'abcd1234',
      maskedKey: 'fxw_live_abcd1234••••',
      status: 'ACTIVE',
      lastUsedAt: null,
      revokedAt: null,
      createdAt: '2026-07-04T00:00:00Z',
    },
    fullKey: FULL_KEY,
  });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

/** Controlled harness so we can toggle `open` (to test clear-on-close). */
function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(true)}>reopen</button>
      <MintApiKeyDialog
        workspaceId="wsp-001"
        open={open}
        onOpenChange={setOpen}
        onMinted={() => {}}
      />
    </>
  );
}

describe('MintApiKeyDialog (omnichannel Slice 3)', () => {
  it('mint button is disabled until a name is entered', () => {
    render(<Harness />);
    const mintBtn = screen.getByRole('button', { name: /mint key/i });
    expect(mintBtn).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/key name/i), { target: { value: 'Production' } });
    expect(mintBtn).not.toBeDisabled();
  });

  it('reveals the full key ONCE with a copy affordance + a "won\'t be shown again" line', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/key name/i), { target: { value: 'Production' } });
    fireEvent.click(screen.getByRole('button', { name: /mint key/i }));

    await waitFor(() => {
      expect(screen.getByDisplayValue(FULL_KEY)).toBeInTheDocument();
    });
    expect(mint).toHaveBeenCalledWith('wsp-001', 'Production');
    expect(screen.getByText(/won.t be shown again/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy api key/i })).toBeInTheDocument();
  });

  it('copy writes the full key to the clipboard', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/key name/i), { target: { value: 'Production' } });
    fireEvent.click(screen.getByRole('button', { name: /mint key/i }));
    await waitFor(() => screen.getByDisplayValue(FULL_KEY));

    fireEvent.click(screen.getByRole('button', { name: /copy api key/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(FULL_KEY);
    });
  });

  it('closing the dialog clears the revealed key (never persisted)', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/key name/i), { target: { value: 'Production' } });
    fireEvent.click(screen.getByRole('button', { name: /mint key/i }));
    await waitFor(() => screen.getByDisplayValue(FULL_KEY));

    // Done closes the dialog.
    fireEvent.click(screen.getByRole('button', { name: /done/i }));
    await waitFor(() => {
      expect(screen.queryByDisplayValue(FULL_KEY)).not.toBeInTheDocument();
    });

    // Reopening shows the fresh input state, not the old key.
    fireEvent.click(screen.getByRole('button', { name: /reopen/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/key name/i)).toHaveValue('');
    });
    expect(screen.queryByDisplayValue(FULL_KEY)).not.toBeInTheDocument();
  });
});
