/**
 * TeamDetailsTab (plan 28, roadmap A8, AC-TEM-40): the Leads picker only ever
 * offers users currently selected as Members (foolproof-UI); read mode shows
 * pills, never the pickers.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { useForm } from 'react-hook-form';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));

import { Form } from '@/components/ui/form';
import type { User } from '@/types/user';
import { TeamDetailsTab } from './team-form-fields';
import type { TeamFormValues } from './team-schema';

const USERS: User[] = [
  { id: 'u1', tenantId: 't1', name: 'Ada Lovelace', email: 'ada@example.com', status: 'ACTIVE', avatar: null, roles: [], createdAt: '', lastSignInAt: null, emailVerifiedAt: null, isTrashed: false },
  { id: 'u2', tenantId: 't1', name: 'Grace Hopper', email: 'grace@example.com', status: 'ACTIVE', avatar: null, roles: [], createdAt: '', lastSignInAt: null, emailVerifiedAt: null, isTrashed: false },
];

function Harness({ editing, defaults }: { editing: boolean; defaults?: Partial<TeamFormValues> }) {
  const form = useForm<TeamFormValues>({
    defaultValues: { name: 'Support', description: '', isActive: true, memberIds: [], leadIds: [], ...defaults },
  });
  return (
    <Form {...form}>
      <TeamDetailsTab form={form} editing={editing} creating={false} team={null} users={USERS} />
    </Form>
  );
}

describe('TeamDetailsTab', () => {
  it('the Leads picker is disabled (no options) until a Member is selected', async () => {
    render(<Harness editing />);
    const leadsTrigger = screen.getAllByRole('combobox')[1]; // [0] = Members, [1] = Leads
    expect(leadsTrigger).toBeDisabled();
  });

  it('the Leads picker only offers users currently selected as Members', async () => {
    const user = userEvent.setup();
    render(<Harness editing defaults={{ memberIds: ['u1'] }} />);

    const leadsTrigger = screen.getAllByRole('combobox')[1];
    expect(leadsTrigger).not.toBeDisabled();
    await user.click(leadsTrigger);

    // `getByRole('option', ...)` (cmdk items) rather than `getByText` - Ada
    // also renders as a selected PILL on the Members trigger, outside any
    // popover, so a text query would be ambiguous.
    expect(screen.getByRole('option', { name: 'Ada Lovelace' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Grace Hopper' })).not.toBeInTheDocument();
  });

  it('removing a Member also removes them from Leads', async () => {
    const user = userEvent.setup();
    render(<Harness editing defaults={{ memberIds: ['u1', 'u2'], leadIds: ['u1'] }} />);

    // Remove Ada (a lead) via her Members pill's own remove control - no
    // popover needed. She also renders as a pill on the Leads trigger (she's
    // a lead too), so pick the FIRST match (Members renders first).
    await user.click(screen.getAllByText('Ada Lovelace')[0]);

    const leadsTrigger = screen.getAllByRole('combobox')[1];
    await user.click(leadsTrigger);
    expect(screen.queryByRole('option', { name: 'Ada Lovelace' })).not.toBeInTheDocument();
  });

  it('read mode (editing=false) shows pills, not pickers', () => {
    render(<Harness editing={false} defaults={{ memberIds: ['u1'] }} />);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
  });
});
