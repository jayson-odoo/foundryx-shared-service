/**
 * Contact panel - Tags section (plan 25, F15/F16 review findings). Optimistic
 * add/remove that reverts the chip set on a failed PATCH, "Add tag" offers
 * ONLY tags the contact doesn't already carry (foolproof-UI), and add/remove
 * controls are gated by `contacts.manage` (F16 - UX only, the API is the gate).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ContactTag, ContactTagRef } from '@/types/omnichannel';
import { TagChips } from './tag-chips';

let can: (key: string) => boolean = () => true;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => can(key) }),
}));

const WORKSPACE_TAGS: ContactTag[] = [
  { id: 'tag-1', workspaceId: 'wsp-1', name: 'VIP', emoji: '⭐', color: '#FF5A00', description: null, contactsCount: 2, createdAt: '2026-01-01T00:00:00Z' },
  { id: 'tag-2', workspaceId: 'wsp-1', name: 'Follow up', emoji: null, color: '#0EA5E9', description: null, contactsCount: 1, createdAt: '2026-01-01T00:00:00Z' },
];

const NO_TAGS: ContactTagRef[] = [];
const VIP_TAG: ContactTagRef[] = [{ id: 'tag-1', name: 'VIP', emoji: '⭐', color: '#FF5A00' }];

describe('TagChips', () => {
  it('offers only tags the contact does not already carry', async () => {
    const user = userEvent.setup();
    render(<TagChips tags={VIP_TAG} workspaceTags={WORKSPACE_TAGS} onChange={vi.fn()} />);

    await user.click(screen.getByRole('combobox', { name: 'Add tag' }));
    expect(await screen.findByRole('option', { name: /Follow up/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /VIP/ })).not.toBeInTheDocument();
  });

  it('adds a tag optimistically then reconciles', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<TagChips tags={NO_TAGS} workspaceTags={WORKSPACE_TAGS} onChange={onChange} />);

    await user.click(screen.getByRole('combobox', { name: 'Add tag' }));
    await user.click(await screen.findByRole('option', { name: /VIP/ }));

    expect(screen.getByText('VIP')).toBeInTheDocument(); // optimistic chip shows immediately
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(['tag-1']));
  });

  it('reverts the chip set when the PATCH fails', async () => {
    const onChange = vi.fn().mockRejectedValue(new Error('nope'));
    const user = userEvent.setup();
    render(<TagChips tags={NO_TAGS} workspaceTags={WORKSPACE_TAGS} onChange={onChange} />);

    await user.click(screen.getByRole('combobox', { name: 'Add tag' }));
    await user.click(await screen.findByRole('option', { name: /VIP/ }));

    // Reverts to the original (empty) set once the rejection settles.
    await waitFor(() => expect(screen.getByText('No tags yet.')).toBeInTheDocument());
  });

  it('removes a tag optimistically', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<TagChips tags={VIP_TAG} workspaceTags={WORKSPACE_TAGS} onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Remove VIP' }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([]));
  });

  it('hides add/remove controls without contacts.manage (F16)', () => {
    can = () => false;
    render(<TagChips tags={VIP_TAG} workspaceTags={WORKSPACE_TAGS} onChange={vi.fn()} />);

    expect(screen.getByText('VIP')).toBeInTheDocument(); // chip still shown, read-only
    expect(screen.queryByRole('button', { name: 'Remove VIP' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Add tag' })).not.toBeInTheDocument();
    can = () => true;
  });
});
