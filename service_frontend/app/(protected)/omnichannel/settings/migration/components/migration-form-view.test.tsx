/**
 * The New migration form must always say why it cannot be saved. When the
 * preflight is running, failed or blocked the channel map stays empty, so
 * Save has to be disabled, and a failed preflight / an empty-map validation
 * error must be visible under the connection field.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { MigrationPreflight } from '@/types/respondio-migration';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/services/integration-service', () => ({
  integrationService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/user-service', () => ({ userService: { list: vi.fn(async () => ({ data: [], total: 0 })) } }));
vi.mock('@/services/team-service', () => ({ teamService: { list: vi.fn(async () => ({ data: [], total: 0 })) } }));

const preflightMock = vi.fn();
vi.mock('@/services/respondio-migration-service', () => ({
  respondioMigrationService: {
    preflight: (...args: unknown[]) => preflightMock(...args),
    createJob: vi.fn(),
    getJob: vi.fn(),
  },
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => v ?? '',
    formatTime: (v: string) => v ?? '',
  }),
}));

vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// The shell is covered by its own suite: reduce it to what the view wires in,
// the first tab's body and the Save button with its `saveDisabled` gate.
vi.mock('@/components/platform/resource-form', () => ({
  FormRow: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ResourceForm: ({ config }: { config: ResourceFormConfig<unknown> }) => (
    <div>
      {config.tabs[0].render({ editing: true })}
      <button type="button" disabled={config.saveDisabled} onClick={() => void config.onSave()}>
        Save
      </button>
    </div>
  ),
}));

// Drive the form values the way a user would have, without clicking through
// the pickers: seed connection + workspace once, optionally inject a
// channelMap validation error. Everything else is the real hook.
const seed = { connectionId: null as string | null, workspaceId: '', channelMapError: null as string | null };
vi.mock('./use-migration-form', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./use-migration-form')>();
  return {
    ...actual,
    useMigrationForm: () => {
      const hook = actual.useMigrationForm();
      const { form } = hook;
      useEffect(() => {
        if (seed.connectionId) form.setValue('connectionId', seed.connectionId);
        if (seed.workspaceId) form.setValue('workspaceId', seed.workspaceId);
        if (seed.channelMapError) form.setError('channelMap', { type: 'custom', message: seed.channelMapError });
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, []);
      return hook;
    },
  };
});

let MigrationFormView: typeof import('./migration-form-view').MigrationFormView;

beforeAll(async () => {
  ({ MigrationFormView } = await import('./migration-form-view'));
});

beforeEach(() => {
  preflightMock.mockReset();
  seed.connectionId = 'conn-1';
  seed.workspaceId = 'wsp-1';
  seed.channelMapError = null;
});

function preflight(overrides: Partial<MigrationPreflight> = {}): MigrationPreflight {
  return {
    apiAvailable: true,
    spaceLabel: 'Acme Support',
    channels: [{ id: 'ch-1', name: 'Support line', source: 'whatsapp_cloud' }],
    users: [],
    teams: [],
    fields: [],
    lifecycles: [],
    targetChannels: [{ id: 'tc-1', name: 'Main WhatsApp', channelType: 'WHATSAPP' }],
    targetStages: [],
    warnings: [],
    ...overrides,
  };
}

function save() {
  return screen.getByRole('button', { name: 'Save' });
}

describe('MigrationFormView - why the form cannot be saved', () => {
  it('shows the preflight failure under the connection field and disables Save', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 502));
    render(<MigrationFormView />);
    expect(await screen.findByText('The respond.io key was refused.')).toBeInTheDocument();
    expect(save()).toBeDisabled();
  });

  it('shows a channelMap validation error under the connection when there is no Channels card', async () => {
    // No preflight ever settles, so there is no Channels card to host the field.
    preflightMock.mockReturnValue(new Promise(() => {}));
    seed.channelMapError = 'Run preflight to load the source channels.';
    render(<MigrationFormView />);
    expect(await screen.findByText('Run preflight to load the source channels.')).toBeInTheDocument();
    expect(screen.queryByText('Channels')).not.toBeInTheDocument();
  });

  it('keeps Save disabled while the preflight is running', async () => {
    preflightMock.mockReturnValue(new Promise(() => {}));
    render(<MigrationFormView />);
    await waitFor(() => expect(preflightMock).toHaveBeenCalled());
    expect(save()).toBeDisabled();
  });

  it('keeps Save disabled when the preflight is blocked (source API not reachable)', async () => {
    preflightMock.mockResolvedValueOnce(
      preflight({ apiAvailable: false, channels: [], targetChannels: [], warnings: ['Could not reach respond.io.'] }),
    );
    render(<MigrationFormView />);
    expect(await screen.findByText('Could not reach respond.io.')).toBeInTheDocument();
    expect(save()).toBeDisabled();
  });

  it('control: Save is enabled once the preflight is ok and a channel is mapped', async () => {
    preflightMock.mockResolvedValueOnce(preflight());
    render(<MigrationFormView />);
    expect(await screen.findByText('Channels')).toBeInTheDocument();
    await waitFor(() => expect(save()).toBeEnabled());
  });
});
