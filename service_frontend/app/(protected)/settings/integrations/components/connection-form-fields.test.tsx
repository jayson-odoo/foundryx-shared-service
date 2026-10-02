import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useForm } from 'react-hook-form';
import { Form } from '@/components/ui/form';
import { ConfigurationTab } from './connection-form-fields';
import { defaultsForProvider, type ConnectionFormValues } from './connection-schema';
import type { IntegrationProvider } from '@/types/integration';

// The shell's own dropdown; a bare provider-field `select` control is
// exercised directly here, no need for the real Radix Select internals.
vi.mock('@/components/platform/search-select', () => ({
  SearchSelect: ({
    value,
    onChange,
    ariaLabel,
  }: {
    value: string | null;
    onChange: (v: string) => void;
    ariaLabel?: string;
  }) => <input aria-label={ariaLabel} value={value ?? ''} onChange={(e) => onChange(e.target.value)} />,
}));

/**
 * A fabricated provider with a `showWhen`-gated field (sprint-5/08, D11/
 * AC-08-04) - the generic mechanism is provider-agnostic, so this stands in
 * for the real `autocount` provider's `auth` select (S2 backend, not yet
 * wired) and proves the field COMPONENT half of the contract (the schema
 * half is `connection-schema.test.ts`).
 */
const PROVIDER: IntegrationProvider = {
  provider: 'fixture',
  type: 'erp',
  title: 'Fixture',
  description: '',
  icon: null,
  testLabel: 'Test',
  testTarget: null,
  fields: [
    {
      key: 'auth',
      label: 'Auth',
      type: 'select',
      required: true,
      defaultValue: 'basic',
      options: [
        { value: 'basic', label: 'Basic auth' },
        { value: 'none', label: 'No auth' },
      ],
    },
    { key: 'baseUrl', label: 'Base URL', type: 'text', required: true },
    {
      key: 'appId',
      label: 'AppId',
      type: 'text',
      required: true,
      showWhen: { field: 'auth', values: ['basic'] },
    },
    {
      key: 'password',
      label: 'Password',
      type: 'password',
      required: true,
      secret: true,
      showWhen: { field: 'auth', values: ['basic'] },
    },
  ],
};

function Wrapper({ editing, defaultAuth = 'basic' }: { editing: boolean; defaultAuth?: string }) {
  const form = useForm<ConnectionFormValues>({
    defaultValues: { ...defaultsForProvider(PROVIDER), config: { auth: defaultAuth, baseUrl: '', appId: '' } },
  });
  return (
    <Form {...form}>
      <ConfigurationTab
        form={form}
        editing={editing}
        creating
        providers={[PROVIDER]}
        provider={PROVIDER}
        onProviderChange={vi.fn()}
        connection={null}
      />
    </Form>
  );
}

describe('ConfigurationTab - showWhen (sprint-5/08, D11/AC-08-04)', () => {
  it('shows the gated fields when the driver select is on their value', () => {
    render(<Wrapper editing defaultAuth="basic" />);
    expect(screen.getByText('AppId')).toBeInTheDocument();
    expect(screen.getByText('Password')).toBeInTheDocument();
  });

  it('hides the gated fields when the driver select is off their value', () => {
    render(<Wrapper editing defaultAuth="none" />);
    expect(screen.queryByText('AppId')).not.toBeInTheDocument();
    expect(screen.queryByText('Password')).not.toBeInTheDocument();
    // The always-shown field stays.
    expect(screen.getByText('Base URL')).toBeInTheDocument();
  });

  it('re-shows/hides reactively as the driver select changes', async () => {
    render(<Wrapper editing defaultAuth="basic" />);
    expect(screen.getByText('AppId')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(await screen.findByText('No auth'));
    expect(screen.queryByText('AppId')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(await screen.findByText('Basic auth', { selector: '[role="option"] *' }));
    expect(screen.getByText('AppId')).toBeInTheDocument();
  });

  it('a field with no showWhen is always shown, unaffected by any driver value', () => {
    render(<Wrapper editing defaultAuth="none" />);
    expect(screen.getByText('Base URL')).toBeInTheDocument();
  });
});
