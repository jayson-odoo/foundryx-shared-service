/**
 * Contact panel - Details form (plan 25, F15 review finding). Covers typed
 * custom-field inputs, phone-is-read-only (never sent - the backend 422s the
 * wire key even unchanged), 422 `fieldErrors` mapping onto the right input,
 * and the Edit button gated by `contacts.manage` (F16).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-client';
import type { ContactField, ConversationThread } from '@/types/omnichannel';
import { ContactDetailsForm } from './contact-details-form';

let can: (key: string) => boolean = () => true;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => can(key) }),
}));

function thread(over: Partial<ConversationThread> = {}): ConversationThread {
  return {
    id: 'cnt-001',
    tenantId: 'ten-1',
    workspaceId: 'wsp-1',
    name: 'Sarah Chen',
    firstName: 'Sarah',
    lastName: 'Chen',
    phone: '+60123456789',
    email: 'sarah@example.com',
    language: 'en',
    countryCode: 'MY',
    avatarUrl: null,
    assignedUserId: null,
    assignedUserName: null,
    status: 'OPEN',
    priority: 'MEDIUM',
    channelId: 'chn-demo',
    channelType: 'WHATSAPP',
    cswExpiresAt: null,
    lastIncomingMessageAt: null,
    lastMessageAt: null,
    lastMessagePreview: null,
    unreadCount: 0,
    customFields: { leadSource: 'Referral' },
    tags: [],
    lifecycle: null,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

const LEAD_SOURCE_FIELD: ContactField = {
  id: 'cf-1',
  workspaceId: 'wsp-1',
  key: 'leadSource',
  label: 'Lead Source',
  description: null,
  type: 'list',
  options: ['Referral', 'Website'],
  visibility: 'always',
  sortOrder: 0,
  valuesCount: 1,
  createdAt: '2026-01-01T00:00:00Z',
};

describe('ContactDetailsForm', () => {
  it('shows phone as read-only text, never an input, even while editing', async () => {
    can = () => true;
    const user = userEvent.setup();
    render(<ContactDetailsForm thread={thread()} fields={[]} onSave={vi.fn()} />);

    await user.click(screen.getByTestId('contact-details-edit'));
    expect(screen.getByText('+60123456789')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /phone/i })).not.toBeInTheDocument();
  });

  it('hides the Edit button without contacts.manage (F16)', () => {
    can = () => false;
    render(<ContactDetailsForm thread={thread()} fields={[]} onSave={vi.fn()} />);
    expect(screen.queryByTestId('contact-details-edit')).not.toBeInTheDocument();
  });

  it('renders a typed list input for a registered custom field and never sends phone', async () => {
    can = () => true;
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ContactDetailsForm thread={thread()} fields={[LEAD_SOURCE_FIELD]} onSave={onSave} />);

    await user.click(screen.getByTestId('contact-details-edit'));
    await user.click(screen.getByRole('combobox', { name: 'Lead Source' }));
    await user.click(await screen.findByRole('option', { name: 'Website' }));
    await user.click(screen.getByTestId('contact-details-save'));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const patch = onSave.mock.calls[0][0];
    expect(patch).not.toHaveProperty('phone');
    expect(patch.customFields).toEqual({ leadSource: 'Website' });
  });

  it('maps a 422 fieldErrors onto customFields.<key>', async () => {
    can = () => true;
    const onSave = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, {
        fieldErrors: { 'customFields.leadSource': 'Unknown custom field.' },
      }),
    );
    const user = userEvent.setup();
    render(<ContactDetailsForm thread={thread()} fields={[LEAD_SOURCE_FIELD]} onSave={onSave} />);

    await user.click(screen.getByTestId('contact-details-edit'));
    await user.click(screen.getByRole('combobox', { name: 'Lead Source' }));
    await user.click(await screen.findByRole('option', { name: 'Website' }));
    await user.click(screen.getByTestId('contact-details-save'));

    expect(await screen.findByText('Unknown custom field.')).toBeInTheDocument();
  });

  it('maps a system-field 422 error onto its own input', async () => {
    can = () => true;
    const onSave = vi.fn().mockRejectedValue(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { email: 'Invalid email address.' } }),
    );
    const user = userEvent.setup();
    render(<ContactDetailsForm thread={thread()} fields={[]} onSave={onSave} />);

    await user.click(screen.getByTestId('contact-details-edit'));
    await user.clear(screen.getByLabelText('Email'));
    await user.type(screen.getByLabelText('Email'), 'not-an-email');
    await user.click(screen.getByTestId('contact-details-save'));

    expect(await screen.findByText('Invalid email address.')).toBeInTheDocument();
  });
});
