/**
 * F9 (plan-25 round-3 codex triage): AC-CDM-31/32 promise every 422
 * `fieldErrors` key maps onto a visible input error. Only `label`/`key`/
 * `options` had an error slot - `description`/`type`/`visibility` (and any
 * truly unmapped key) silently swallowed their 422, blocking submit with no
 * feedback at all.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-client';
import { ContactFieldDialog } from './contact-field-dialog';

describe('ContactFieldDialog 422 error mapping', () => {
  it('F9: renders a description 422 under the Description input', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { description: 'Description is too long.' } }),
    );
    const user = userEvent.setup();
    render(<ContactFieldDialog open field={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'Source');
    await user.click(screen.getByRole('button', { name: 'Add field' }));

    expect(await screen.findByText('Description is too long.')).toBeInTheDocument();
  });

  it('F9: renders a type 422 under the Type picker', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { type: 'Unknown field type.' } }),
    );
    const user = userEvent.setup();
    render(<ContactFieldDialog open field={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'Source');
    await user.click(screen.getByRole('button', { name: 'Add field' }));

    expect(await screen.findByText('Unknown field type.')).toBeInTheDocument();
  });

  it('F9: renders a visibility 422 under the Visibility picker', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { visibility: 'Unknown visibility value.' } }),
    );
    const user = userEvent.setup();
    render(<ContactFieldDialog open field={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'Source');
    await user.click(screen.getByRole('button', { name: 'Add field' }));

    expect(await screen.findByText('Unknown visibility value.')).toBeInTheDocument();
  });

  it('F9: an UNMAPPED 422 key falls back to a dialog-level error, never silently dropped', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { somethingUnexpected: 'A server-only rule failed.' } }),
    );
    const user = userEvent.setup();
    render(<ContactFieldDialog open field={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    await user.type(screen.getByLabelText('Name'), 'Source');
    await user.click(screen.getByRole('button', { name: 'Add field' }));

    expect(await screen.findByText('A server-only rule failed.')).toBeInTheDocument();
  });

  it('clears stale unmapped errors when the dialog reopens', async () => {
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { somethingUnexpected: 'Stale error.' } }),
    );
    const user = userEvent.setup();
    const { rerender } = render(
      <ContactFieldDialog open field={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />,
    );
    await user.type(screen.getByLabelText('Name'), 'Source');
    await user.click(screen.getByRole('button', { name: 'Add field' }));
    await waitFor(() => expect(screen.getByText('Stale error.')).toBeInTheDocument());

    rerender(<ContactFieldDialog open={false} field={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);
    rerender(<ContactFieldDialog open field={null} onOpenChange={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} />);

    expect(screen.queryByText('Stale error.')).not.toBeInTheDocument();
  });
});
