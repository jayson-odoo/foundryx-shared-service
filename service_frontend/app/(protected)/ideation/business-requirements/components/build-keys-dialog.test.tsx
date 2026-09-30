import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BuildKeysDialog } from './build-keys-dialog';

const listBuildKeys = vi.fn();
const mintBuildKey = vi.fn();
const revokeBuildKey = vi.fn();
vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: {
    listBuildKeys: (...a: unknown[]) => listBuildKeys(...a),
    mintBuildKey: (...a: unknown[]) => mintBuildKey(...a),
    revokeBuildKey: (...a: unknown[]) => revokeBuildKey(...a),
  },
}));

// The dialog renders created/last-used through useDatetime (house rule), which
// reads the NextAuth session; the test has no SessionProvider.
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => `T(${v})`,
    formatTime: (v: string) => v ?? '',
  }),
}));

const FULL_KEY = 'fxb_live_abcdefabcdefabcdefabcdefabcdefabcd';

const KEY = {
  id: 'k1',
  name: 'Crew daemon',
  keyPrefix: 'fxb_live_ab',
  createdAt: '2026-09-20T00:00:00Z',
  lastUsedAt: null,
};

beforeEach(() => {
  listBuildKeys.mockReset().mockResolvedValue([KEY]);
  mintBuildKey.mockReset().mockResolvedValue({ ...KEY, id: 'k2', name: 'New key', plaintext: FULL_KEY });
  revokeBuildKey.mockReset().mockResolvedValue(undefined);
});

function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(true)}>reopen</button>
      <BuildKeysDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

describe('BuildKeysDialog (AC-STB-15)', () => {
  it('AC-STB-15 lists existing keys by name and prefix', async () => {
    render(<Harness />);
    expect(await screen.findByText('Crew daemon')).toBeInTheDocument();
    expect(screen.getByText(/fxb_live_ab/)).toBeInTheDocument();
  });

  it('AC-STB-15 Mint calls mintBuildKey(name) and shows the plaintext once with a Copy button', async () => {
    render(<Harness />);
    await screen.findByText('Crew daemon');
    fireEvent.change(screen.getByRole('textbox', { name: /name/i }), { target: { value: 'New key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mint' }));
    await waitFor(() => expect(screen.getByDisplayValue(FULL_KEY)).toBeInTheDocument());
    expect(mintBuildKey).toHaveBeenCalledWith('New key');
    expect(screen.getByDisplayValue(FULL_KEY)).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: /copy/i })).toBeInTheDocument();
  });

  it('AC-STB-15 closing clears the plaintext; reopening never shows it again', async () => {
    render(<Harness />);
    await screen.findByText('Crew daemon');
    fireEvent.change(screen.getByRole('textbox', { name: /name/i }), { target: { value: 'New key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mint' }));
    await waitFor(() => screen.getByDisplayValue(FULL_KEY));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByDisplayValue(FULL_KEY)).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'reopen' }));
    await screen.findByText('Crew daemon');
    expect(screen.queryByDisplayValue(FULL_KEY)).not.toBeInTheDocument();
  });

  it('AC-STB-15 Revoke asks for confirmation before calling revokeBuildKey(id)', async () => {
    render(<Harness />);
    await screen.findByText('Crew daemon');
    fireEvent.click(screen.getByRole('button', { name: /revoke/i }));
    expect(revokeBuildKey).not.toHaveBeenCalled();
    // The confirm (AlertDialog) exposes its own Revoke action button.
    const confirms = await screen.findAllByRole('button', { name: /^revoke$/i });
    fireEvent.click(confirms[confirms.length - 1]);
    await waitFor(() => expect(revokeBuildKey).toHaveBeenCalledWith('k1'));
  });
});
