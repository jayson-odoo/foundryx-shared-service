/**
 * F10 (plan-25 round-3 codex triage): same class of bug as F9 for
 * ContactTagDialog - only `name` had an error slot; `emoji`/`color`/
 * `description` (and any truly unmapped key) silently swallowed their 422.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-client';
import { ContactTagDialog } from './contact-tag-dialog';

describe('ContactTagDialog 422 error mapping', () => {
  it('F10: renders an emoji 422 under the Emoji input', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { emoji: 'Use a single emoji.' } }),
    );
    const user = userEvent.setup();
    render(<ContactTagDialog open tag={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'VIP');
    await user.click(screen.getByRole('button', { name: 'Create tag' }));

    expect(await screen.findByText('Use a single emoji.')).toBeInTheDocument();
  });

  it('F10: renders a color 422 under the Colour control', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { color: 'Invalid colour value.' } }),
    );
    const user = userEvent.setup();
    render(<ContactTagDialog open tag={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'VIP');
    await user.click(screen.getByRole('button', { name: 'Create tag' }));

    expect(await screen.findByText('Invalid colour value.')).toBeInTheDocument();
  });

  it('F10: renders a description 422 under the Description input', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { description: 'Description is too long.' } }),
    );
    const user = userEvent.setup();
    render(<ContactTagDialog open tag={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'VIP');
    await user.click(screen.getByRole('button', { name: 'Create tag' }));

    expect(await screen.findByText('Description is too long.')).toBeInTheDocument();
  });

  it('F10: an UNMAPPED 422 key falls back to a dialog-level error, never silently dropped', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { somethingUnexpected: 'A server-only rule failed.' } }),
    );
    const user = userEvent.setup();
    render(<ContactTagDialog open tag={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'VIP');
    await user.click(screen.getByRole('button', { name: 'Create tag' }));

    expect(await screen.findByText('A server-only rule failed.')).toBeInTheDocument();
  });

  it('clears stale unmapped errors when the dialog reopens', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { somethingUnexpected: 'Stale error.' } }),
    );
    const user = userEvent.setup();
    const { rerender } = render(
      <ContactTagDialog open tag={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />,
    );
    await user.type(screen.getByLabelText('Name'), 'VIP');
    await user.click(screen.getByRole('button', { name: 'Create tag' }));
    await waitFor(() => expect(screen.getByText('Stale error.')).toBeInTheDocument());

    rerender(<ContactTagDialog open={false} tag={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);
    rerender(<ContactTagDialog open tag={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    expect(screen.queryByText('Stale error.')).not.toBeInTheDocument();
  });
});
