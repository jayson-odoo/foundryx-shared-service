/**
 * The role permission grid under the Foundryx UIUX switch (W3-USERS): the
 * tick logic mirrors today's dropdown (pure functions), the grid shows a
 * mixed All tick, greys a read that the other ticks keep on, and shows only
 * the granted actions as chips in read mode. What both looks send is compared
 * in user-management/__parity__/writes-both-looks.test.tsx.
 */
import { useForm } from 'react-hook-form';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Form } from '@/components/ui/form';
import { CATALOG, Look } from '../../__parity__/um-kit';
import { FxPermissionsTab } from './fx-permissions-tab';
import {
  allResourceActionsOn,
  isImpliedRead,
  toggleAllResourceActions,
  toggleResourceAction,
} from './permission-ticks';
import type { RoleFormValues } from './role-schema';

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

const users = CATALOG[0];
const contacts = CATALOG[2];

describe('permission ticks', () => {
  it('ticking a write adds it after the selection and brings read in', () => {
    expect(toggleResourceAction(['contacts.read'], users, 'users.update')).toEqual([
      'contacts.read',
      'users.update',
      'users.read',
    ]);
  });

  it('unticking a write keeps read', () => {
    expect(toggleResourceAction(['users.read', 'users.update'], users, 'users.update')).toEqual(['users.read']);
  });

  it('All turns every action on in catalog order, then off', () => {
    const on = toggleAllResourceActions(['users.read'], contacts);
    expect(on).toEqual(['users.read', 'contacts.read', 'contacts.create', 'contacts.export']);
    expect(allResourceActionsOn(on, contacts)).toBe(true);
    expect(toggleAllResourceActions(on, contacts)).toEqual(['users.read']);
  });

  it('read is implied only while another action of that resource is on', () => {
    expect(isImpliedRead(['users.read', 'users.create'], users, 'users.read')).toBe(true);
    expect(isImpliedRead(['users.read', 'contacts.create'], users, 'users.read')).toBe(false);
    expect(isImpliedRead(['users.read', 'users.create'], users, 'users.create')).toBe(false);
  });
});

function Harness({ keys, editing }: { keys: string[]; editing: boolean }) {
  const form = useForm<RoleFormValues>({
    defaultValues: { name: 'Desk', description: '', permissionKeys: keys, isSystem: false },
  });
  return (
    <Form {...form}>
      <FxPermissionsTab form={form} editing={editing} catalog={CATALOG} />
      <output data-testid="keys">{form.watch('permissionKeys').join(',')}</output>
    </Form>
  );
}

function renderGrid(keys: string[], editing: boolean) {
  render(
    <Look fx>
      <Harness keys={keys} editing={editing} />
    </Look>,
  );
}

describe('FxPermissionsTab', () => {
  it('one card per module with how many actions are on', () => {
    renderGrid(['users.read', 'users.update', 'contacts.read'], false);
    expect(within(screen.getByRole('region', { name: 'Core' })).getByText('2 of 9')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Omnichannel' })).getByText('1 of 3')).toBeInTheDocument();
  });

  it('read mode shows only the granted actions, or No access', () => {
    renderGrid(['users.read', 'users.update'], false);
    const row = screen.getByRole('group', { name: 'Users' });
    expect(within(row).getByText('Read')).toBeInTheDocument();
    expect(within(row).getByText('Update')).toBeInTheDocument();
    expect(within(row).queryByText('Delete')).toBeNull();
    expect(within(row).queryByRole('checkbox')).toBeNull();
    expect(within(screen.getByRole('group', { name: 'Contacts' })).getByText('No access')).toBeInTheDocument();
  });

  it('editing: All is mixed while some are on, and read is greyed while a write is on', async () => {
    const u = userEvent.setup();
    renderGrid(['users.read', 'users.update'], true);
    const row = screen.getByRole('group', { name: 'Users' });
    expect(within(row).getByRole('checkbox', { name: 'All' })).toHaveAttribute('data-state', 'indeterminate');
    expect(within(row).getByRole('checkbox', { name: 'Read' })).toBeDisabled();

    await u.click(within(row).getByRole('checkbox', { name: 'Update' }));
    expect(screen.getByTestId('keys')).toHaveTextContent(/^users\.read$/);
    expect(within(row).getByRole('checkbox', { name: 'Read' })).toBeEnabled();

    await u.click(within(row).getByRole('checkbox', { name: 'All' }));
    expect(within(row).getByRole('checkbox', { name: 'All' })).toHaveAttribute('data-state', 'checked');
    expect(screen.getByTestId('keys')).toHaveTextContent(
      'users.read,users.create,users.update,users.delete,users.impersonate',
    );
  });
});
