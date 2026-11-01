/**
 * Replace token dialog - plan 42 (AC-42-20, AC-42-21, AC-42-22). RED tests:
 * the component does not exist yet. Mocked at the service boundary
 * (`channelService.replaceChannelToken`), as the layering requires.
 *
 * Assumed seam (the coder matches it): `ReplaceTokenDialog` exported from
 * `./replace-token-dialog`, props `{ channel, open, onOpenChange, onReplaced }`.
 */
import type React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Channel } from '@/types/omnichannel';

const replaceChannelToken = vi.fn();
vi.mock('@/services/channel-service', () => ({
  channelService: {
    replaceChannelToken: (...args: unknown[]) => replaceChannelToken(...args),
  },
}));

const toastSuccess = vi.fn();
const toastWarning = vi.fn();
const toastInfo = vi.fn();
const toastError = vi.fn();
vi.mock('@/lib/toast', () => ({
  toast: { success: toastSuccess, warning: toastWarning, info: toastInfo, error: toastError },
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (iso: string | null | undefined) => `FMT(${iso})`,
    formatDateTime: (iso: string | null | undefined) => `FMT(${iso})`,
    formatTime: (iso: string | null | undefined) => `FMT(${iso})`,
  }),
}));

const LABEL = 'Permanent access token (System User)';
const TOKEN = 'tok-under-test-1';

const CHANNEL = {
  id: 'chn-th-1',
  name: 'Support Line',
  channelType: 'WHATSAPP',
  status: 'ERROR',
  isActive: true,
  isTrashed: false,
  displayPhoneNumber: '+60 11-111 0042',
} as Channel;

async function mountDialog(props: Partial<{ onOpenChange: () => void; onReplaced: () => void }> = {}) {
  const { ReplaceTokenDialog } = await import('./replace-token-dialog');
  const onOpenChange = props.onOpenChange ?? vi.fn();
  const onReplaced = props.onReplaced ?? vi.fn();
  render(<ReplaceTokenDialog channel={CHANNEL} open onOpenChange={onOpenChange} onReplaced={onReplaced} />);
  return { onOpenChange, onReplaced };
}

function type(value: string) {
  fireEvent.change(screen.getByLabelText(LABEL), { target: { value } });
}

function save() {
  fireEvent.click(screen.getByRole('button', { name: /save/i }));
}

/** Everything a user could read after a success except the success toast. */
function shown(): string {
  const calls = [toastWarning, toastInfo, toastError].flatMap((f) => f.mock.calls.flat().map(String));
  return `${calls.join(' ')} ${document.body.textContent ?? ''}`;
}

const OK = { ...CHANNEL, status: 'ACTIVE', subscribed: true, tokenExpiresAt: null };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ReplaceTokenDialog - AC-42-20', () => {
  it('has exactly one password input with the fixed label, and Save is disabled while empty', async () => {
    await mountDialog();
    const input = screen.getByLabelText(LABEL) as HTMLInputElement;
    expect(input.type).toBe('password');
    expect(document.querySelectorAll('input')).toHaveLength(1);
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
    type(TOKEN);
    expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
    type('   ');
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
  });
});

describe('ReplaceTokenDialog - AC-42-21 success', () => {
  it('calls the service with the id and token, closes, refreshes and toasts', async () => {
    replaceChannelToken.mockResolvedValue(OK);
    const { onOpenChange, onReplaced } = await mountDialog();
    type(TOKEN);
    save();
    await waitFor(() => expect(replaceChannelToken).toHaveBeenCalledWith('chn-th-1', TOKEN));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onReplaced).toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalled();
  });

  it('control: subscribed true and no expiry shows no warning', async () => {
    replaceChannelToken.mockResolvedValue(OK);
    await mountDialog();
    type(TOKEN);
    save();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(shown()).not.toMatch(/subscri|webhook|expire/i);
  });

  it.each([false, null])('subscribed %s shows the webhook warning', async (subscribed) => {
    replaceChannelToken.mockResolvedValue({ ...OK, subscribed });
    await mountDialog();
    type(TOKEN);
    save();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(shown()).toMatch(/subscri|webhook/i);
  });

  it('tokenExpiresAt shows an expiry warning with the date through useDatetime', async () => {
    replaceChannelToken.mockResolvedValue({ ...OK, tokenExpiresAt: '2027-03-01T00:00:00Z' });
    await mountDialog();
    type(TOKEN);
    save();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(shown()).toMatch(/expire/i);
    expect(shown()).toContain('FMT(2027-03-01T00:00:00Z)');
  });
});

describe('ReplaceTokenDialog - AC-42-22 refusal', () => {
  it('a refusal keeps the dialog open, the typed value and shows the message', async () => {
    replaceChannelToken.mockRejectedValue(
      Object.assign(new Error('That token was not accepted.'), { status: 422 }),
    );
    const { onOpenChange, onReplaced } = await mountDialog();
    type(TOKEN);
    save();
    expect(await screen.findByText(/That token was not accepted\./)).toBeInTheDocument();
    expect((screen.getByLabelText(LABEL) as HTMLInputElement).value).toBe(TOKEN);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(onReplaced).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it('a failed request keeps the dialog open and the typed value too', async () => {
    replaceChannelToken.mockRejectedValue(new TypeError('Failed to fetch'));
    const { onOpenChange } = await mountDialog();
    type(TOKEN);
    save();
    await waitFor(() => expect(replaceChannelToken).toHaveBeenCalled());
    await waitFor(() => expect(document.body.textContent ?? '').toMatch(/could not|failed|try again/i));
    expect((screen.getByLabelText(LABEL) as HTMLInputElement).value).toBe(TOKEN);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
