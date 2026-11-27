import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useForm } from 'react-hook-form';
import { Form } from '@/components/ui/form';
import { ConfigurationTab } from './connection-form-fields';
import { defaultsForProvider, type ConnectionFormValues } from './connection-schema';
import type { Connection, IntegrationProvider } from '@/types/integration';

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

// SS-STOCK-PAGE-PAUSE-CONFIG - a provider's per-connection hint under a field.
const PAUSE_PROVIDER: IntegrationProvider = {
  ...PROVIDER,
  fields: [{ key: 'pagePauseSeconds', label: 'Pause between pages (seconds)', type: 'number', required: false, defaultValue: '0' }],
};

const PAUSE_CONNECTION: Connection = {
  id: 'c1',
  tenantId: 't1',
  provider: 'fixture',
  type: 'erp',
  name: 'REST',
  config: { pagePauseSeconds: '1' },
  status: 'ACTIVE',
  isActive: true,
  lastTestedAt: null,
  lastError: null,
  rateLimitPerMinute: 30,
  createdAt: '2026-11-27T00:00:00Z',
  updatedAt: '2026-11-27T00:00:00Z',
  fieldHints: {
    pagePauseSeconds: { kind: 'pageRun', pages: 70, lastRunSeconds: 129, lastPauseSeconds: 1, maxRunSeconds: 7200 },
  },
};

function PauseWrapper({ editing, connection }: { editing: boolean; connection: Connection }) {
  const form = useForm<ConnectionFormValues>({
    defaultValues: { ...defaultsForProvider(PAUSE_PROVIDER), config: { ...connection.config } },
  });
  return (
    <Form {...form}>
      <ConfigurationTab
        form={form}
        editing={editing}
        creating={false}
        providers={[PAUSE_PROVIDER]}
        provider={PAUSE_PROVIDER}
        onProviderChange={vi.fn()}
        connection={connection}
      />
    </Form>
  );
}

describe('ConfigurationTab - field hint (SS-STOCK-PAGE-PAUSE-CONFIG)', () => {
  it('shows the run estimate under the saved value', () => {
    render(<PauseWrapper editing={false} connection={PAUSE_CONNECTION} />);
    expect(screen.getByText('About 70 pages per run → about 2 min per run')).toBeInTheDocument();
  });

  it('recomputes the estimate while the pause is typed', () => {
    render(<PauseWrapper editing connection={PAUSE_CONNECTION} />);
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '60' } });
    expect(screen.getByText('About 70 pages per run → about 70 min per run')).toBeInTheDocument();
  });

  it('shows no hint before any run is known', () => {
    const { container } = render(
      <PauseWrapper editing connection={{ ...PAUSE_CONNECTION, fieldHints: {} }} />,
    );
    expect(container.querySelector('[data-field-hint]')).toBeNull();
  });
});
