/**
 * The New migration form must always say why it cannot be saved. When the
 * preflight is running, failed or blocked the channel map stays empty, so
 * Save has to be disabled, and a failed preflight / an empty-map validation
 * error must be visible under the connection field.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useEffect } from 'react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { MigrationJob, MigrationPreflight } from '@/types/respondio-migration';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/omnichannel/settings/migration/new',
  useSearchParams: () => new URLSearchParams(),
}));
const toastError = vi.hoisted(() => vi.fn());
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: toastError } }));

vi.mock('@/services/integration-service', () => ({
  integrationService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/user-service', () => ({ userService: { list: vi.fn(async () => ({ data: [], total: 0 })) } }));
vi.mock('@/services/team-service', () => ({ teamService: { list: vi.fn(async () => ({ data: [], total: 0 })) } }));

const preflightMock = vi.fn();
const createJobMock = vi.fn();
const getJobMock = vi.fn();
vi.mock('@/services/respondio-migration-service', () => ({
  respondioMigrationService: {
    preflight: (...args: unknown[]) => preflightMock(...args),
    createJob: (...args: unknown[]) => createJobMock(...args),
    getJob: (...args: unknown[]) => getJobMock(...args),
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
      <button type="button" onClick={() => config.onCancel()}>
        Cancel
      </button>
    </div>
  ),
}));

// Drive the form values the way a user would have, without clicking through
// the pickers: seed connection + workspace once, optionally inject a
// channelMap validation error. Everything else is the real hook.
const seed = {
  source: 'api' as 'api' | 'csv',
  connectionId: null as string | null,
  workspaceId: '',
  channelMapError: null as string | null,
};
let current: ReturnType<typeof import('./use-migration-form').useMigrationForm> | null = null;
vi.mock('./use-migration-form', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./use-migration-form')>();
  return {
    ...actual,
    useMigrationForm: () => {
      const hook = actual.useMigrationForm();
      const { form } = hook;
      current = hook;
      useEffect(() => {
        if (seed.source === 'csv') form.setValue('source', 'csv');
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
  createJobMock.mockReset();
  getJobMock.mockReset();
  toastError.mockReset();
  current = null;
  seed.source = 'api';
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
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    render(<MigrationFormView />);
    expect(await screen.findByText('The respond.io key was refused.')).toBeInTheDocument();
    expect(save()).toBeDisabled();
  });

  it('shows a channelMap validation error under the connection when there is no Channels card', async () => {
    // No preflight ever settles, so there is no Channels card to host the field.
    preflightMock.mockReturnValue(new Promise(() => {}));
    seed.channelMapError = 'Add a channel to map.';
    render(<MigrationFormView />);
    expect(await screen.findByText('Add a channel to map.')).toBeInTheDocument();
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

function seedNothing() {
  seed.connectionId = null;
  seed.workspaceId = '';
}

describe('MigrationFormView - missing picks go back to validation', () => {
  it('fresh form: Save is enabled and shows the fields own messages, not a bare toast', async () => {
    seedNothing();
    render(<MigrationFormView />);
    expect(save()).toBeEnabled();
    fireEvent.click(save());
    expect(await screen.findByText('Choose a connection.')).toBeInTheDocument();
    expect(screen.getByText('Choose a target workspace.')).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('connection without workspace: Save is enabled and names the workspace', async () => {
    seed.workspaceId = '';
    render(<MigrationFormView />);
    expect(save()).toBeEnabled();
    fireEvent.click(save());
    expect(await screen.findByText('Choose a target workspace.')).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('workspace without connection: Save is enabled and names the connection', async () => {
    seed.connectionId = null;
    render(<MigrationFormView />);
    expect(save()).toBeEnabled();
    fireEvent.click(save());
    expect(await screen.findByText('Choose a connection.')).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('CSV without an upload: Save and Run dry run are enabled and name the upload', async () => {
    seedNothing();
    seed.source = 'csv';
    seed.workspaceId = 'wsp-1';
    render(<MigrationFormView />);
    expect(save()).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Run dry run' })).toBeEnabled();
    fireEvent.click(save());
    expect(await screen.findByText('Upload a contacts CSV.')).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('CSV with an upload: Save and Run dry run are enabled', async () => {
    seedNothing();
    seed.source = 'csv';
    seed.workspaceId = 'wsp-1';
    render(<MigrationFormView />);
    await waitFor(() => expect(current).not.toBeNull());
    act(() => current?.onContactsUploaded({ id: 'up-1', rowCount: 2, headers: ['Name'] }, 'contacts.csv'));
    expect(save()).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Run dry run' })).toBeEnabled();
  });

  it('pressing Save with no channels loaded never tells the user to run a preflight', async () => {
    seed.workspaceId = '';
    render(<MigrationFormView />);
    fireEvent.click(save());
    await screen.findByText('Choose a target workspace.');
    expect(screen.queryByText(/run preflight/i)).not.toBeInTheDocument();
  });
});

describe('MigrationFormView - connection and workspace chosen', () => {
  it('Run dry run follows Save: disabled while the preflight is running', async () => {
    preflightMock.mockReturnValue(new Promise(() => {}));
    render(<MigrationFormView />);
    await waitFor(() => expect(preflightMock).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'Run dry run' })).toBeDisabled();
  });

  it('shows the blocked warning and disables Save and Run dry run', async () => {
    preflightMock.mockResolvedValueOnce(
      preflight({ apiAvailable: false, channels: [], targetChannels: [], warnings: ['Could not reach respond.io.'] }),
    );
    render(<MigrationFormView />);
    expect(await screen.findByText('Could not reach respond.io.')).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Run dry run' })).toBeDisabled();
  });

  it('a reachable source with zero channels: Save disabled and a visible reason', async () => {
    preflightMock.mockResolvedValueOnce(preflight({ channels: [], targetChannels: [] }));
    render(<MigrationFormView />);
    expect(await screen.findByText(/no channels/i)).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Run dry run' })).toBeDisabled();
  });

  it('a failed preflight disables Run dry run too', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    render(<MigrationFormView />);
    await screen.findByText('The respond.io key was refused.');
    expect(screen.getByRole('button', { name: 'Run dry run' })).toBeDisabled();
  });

  it('control: a channel left on Skip (null target) keeps Save and Run dry run enabled', async () => {
    preflightMock.mockResolvedValueOnce(preflight({ targetChannels: [] }));
    render(<MigrationFormView />);
    expect(await screen.findByText('Channels')).toBeInTheDocument();
    await waitFor(() => expect(save()).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Run dry run' })).toBeEnabled();
  });

  it('a server error shows the plain text, not its message', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('Internal Server Error', 500));
    render(<MigrationFormView />);
    expect(await screen.findByText('Could not check the connection.')).toBeInTheDocument();
    expect(screen.queryByText('Internal Server Error')).not.toBeInTheDocument();
  });

  it('a client error shows its own message', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 403));
    render(<MigrationFormView />);
    expect(await screen.findByText('The respond.io key was refused.')).toBeInTheDocument();
  });

  it('the same text from preflight and channelMap shows once', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('Same words.', 400));
    seed.channelMapError = 'Same words.';
    render(<MigrationFormView />);
    await waitFor(() => expect(preflightMock).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.getByText('Same words.')).toBeInTheDocument();
  });
});

describe('MigrationFormView - clearing', () => {
  it('a failed preflight then Cancel: the error is gone', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    render(<MigrationFormView />);
    await screen.findByText('The respond.io key was refused.');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByText('The respond.io key was refused.')).not.toBeInTheDocument());
  });

  it('a failed preflight then clearing the connection: the error is gone', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    render(<MigrationFormView />);
    await screen.findByText('The respond.io key was refused.');
    act(() => current?.form.setValue('connectionId', null));
    await waitFor(() => expect(screen.queryByText('The respond.io key was refused.')).not.toBeInTheDocument());
  });

  it('a successful preflight then clearing the connection: the Channels card is gone', async () => {
    preflightMock.mockResolvedValueOnce(preflight());
    render(<MigrationFormView />);
    await screen.findByText('Channels');
    act(() => current?.form.setValue('connectionId', null));
    await waitFor(() => expect(screen.queryByText('Channels')).not.toBeInTheDocument());
  });

  it('in flight then clearing the connection: no stuck spinner', async () => {
    preflightMock.mockReturnValue(new Promise(() => {}));
    render(<MigrationFormView />);
    await screen.findByText(/checking the connection/i);
    act(() => current?.form.setValue('connectionId', null));
    await waitFor(() => expect(screen.queryByText(/checking the connection/i)).not.toBeInTheDocument());
  });
});


// ── Plan 44 - source channels that could not be read (AC-44-23 / 24) ───────

const BAD_ID = 'src-bad-7011';

function unreadablePreflight(overrides: Partial<MigrationPreflight> = {}): MigrationPreflight {
  return preflight({
    channels: [{ id: 'ch-1', name: 'Support line', source: 'whatsapp_cloud' }],
    targetChannels: [
      { id: 'tc-1', name: 'Main WhatsApp', channelType: 'WHATSAPP' },
      { id: 'tc-2', name: 'Second WhatsApp', channelType: 'WHATSAPP' },
    ],
    unreadableChannelIds: [BAD_ID],
    ...overrides,
  } as Partial<MigrationPreflight>);
}

function doneJob(mode: 'dry_run' | 'run', blockers: string[] = []): MigrationJob {
  const zero = { fetched: 0, wouldCreate: 0, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
  return {
    id: 'mig-job-1',
    mode,
    source: 'api',
    connectionId: 'conn-1',
    spaceLabel: 'Acme Support',
    workspaceId: 'wsp-1',
    workspaceName: 'Main',
    status: 'done',
    progressTotal: 1,
    progressDone: 1,
    progressFailed: 0,
    entityCounts: { contacts: 1, messages: 0 },
    report: {
      entities: {
        contacts: { ...zero },
        fields: { ...zero },
        tags: { ...zero },
        identities: { ...zero },
        messages: { ...zero },
        media: { ...zero },
        events: { ...zero },
        quickReplies: { ...zero },
      },
      messagesWithInferredTimestamp: 0,
      messagesSkippedBeforeFloor: 0,
      blockers,
      samples: { contacts: [], messages: [] },
    },
    failureCount: 0,
    failureSample: [],
    startedAt: '2026-01-01T00:00:00Z',
    finishedAt: '2026-01-01T00:00:01Z',
    createdAt: '2026-01-01T00:00:00Z',
    actorUserName: 'You',
    logs: [],
  } as MigrationJob;
}

/** The select inside the row that shows `text` (walks up to the nearest
 *  ancestor holding exactly one combobox). */
function rowSelect(text: RegExp | string): HTMLElement {
  let node: HTMLElement | null = screen.getByText(text);
  while (node) {
    const boxes = within(node).queryAllByRole('combobox');
    if (boxes.length === 1) return boxes[0];
    node = node.parentElement;
  }
  throw new Error(`no select found near ${String(text)}`);
}

function channelEntries() {
  return current?.form.getValues('channelMap') ?? [];
}

async function chooseSkipFor(text: RegExp | string) {
  fireEvent.click(rowSelect(text));
  const options = await screen.findAllByRole('option');
  fireEvent.click(options.find((o) => o.textContent === 'Skip this channel') as HTMLElement);
}

async function renderWithUnreadable(pf: MigrationPreflight = unreadablePreflight()) {
  preflightMock.mockResolvedValueOnce(pf);
  render(<MigrationFormView />);
  await screen.findByText('Channels');
  await waitFor(() => expect(save()).toBeEnabled());
}

describe('MigrationFormView - unreadable source channels (AC-44-23)', () => {
  it('shows a row per unreadable id whose select offers exactly "Skip this channel"', async () => {
    await renderWithUnreadable();
    expect(screen.getByText(new RegExp(BAD_ID))).toBeInTheDocument();
    fireEvent.click(rowSelect(new RegExp(BAD_ID)));
    const options = await screen.findAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(['Skip this channel']);
  });

  it('does not show Skip as chosen by default and the map has no entry for the id', async () => {
    await renderWithUnreadable();
    expect(rowSelect(new RegExp(BAD_ID))).not.toHaveTextContent('Skip this channel');
    expect(channelEntries().map((e) => e.sourceChannelId)).toEqual(['ch-1']);
    expect(channelEntries().some((e) => e.sourceChannelId === BAD_ID)).toBe(false);
  });

  it('choosing Skip adds the id with a null target and leaves the readable entries alone', async () => {
    await renderWithUnreadable();
    const before = channelEntries().filter((e) => e.sourceChannelId === 'ch-1');
    await chooseSkipFor(new RegExp(BAD_ID));
    await waitFor(() =>
      expect(channelEntries()).toContainEqual({ sourceChannelId: BAD_ID, targetChannelId: null }),
    );
    expect(channelEntries().filter((e) => e.sourceChannelId === 'ch-1')).toEqual(before);
    expect(rowSelect(new RegExp(BAD_ID))).toHaveTextContent('Skip this channel');
  });

  it('changing a readable channel target afterwards keeps the Skip entry', async () => {
    await renderWithUnreadable();
    await chooseSkipFor(new RegExp(BAD_ID));
    await waitFor(() => expect(channelEntries().some((e) => e.sourceChannelId === BAD_ID)).toBe(true));
    fireEvent.click(screen.getByRole('combobox', { name: 'Target channel for Support line' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Second WhatsApp' }));
    await waitFor(() =>
      expect(channelEntries()).toContainEqual({ sourceChannelId: 'ch-1', targetChannelId: 'tc-2' }),
    );
    expect(channelEntries()).toContainEqual({ sourceChannelId: BAD_ID, targetChannelId: null });
  });

  it('a dry run goes ahead with no Skip chosen and its payload has no entry for the id', async () => {
    createJobMock.mockResolvedValue(doneJob('dry_run'));
    getJobMock.mockResolvedValue(doneJob('dry_run'));
    await renderWithUnreadable();
    fireEvent.click(screen.getByRole('button', { name: 'Run dry run' }));
    await waitFor(() => expect(createJobMock).toHaveBeenCalledTimes(1));
    const input = createJobMock.mock.calls[0][0] as {
      mode: string;
      channelMap: { sourceChannelId: string }[];
    };
    expect(input.mode).toBe('dry_run');
    expect(input.channelMap.some((e) => e.sourceChannelId === BAD_ID)).toBe(false);
  });

  describe('the real run is refused for an unreadable channel', () => {
    const REFUSAL = `1 source channel(s) could not be read and would be lost (source ids: ${BAD_ID}).`;

    async function refuseStart() {
      createJobMock.mockResolvedValueOnce(doneJob('dry_run'));
      getJobMock.mockResolvedValue(doneJob('dry_run'));
      await renderWithUnreadable();
      fireEvent.click(screen.getByRole('button', { name: 'Run dry run' }));
      const start = screen.getByRole('button', { name: 'Start migration' });
      await waitFor(() => expect(start).toBeEnabled());
      createJobMock.mockRejectedValueOnce(new ApiError('Unprocessable', 422, null, { fieldErrors: { channelMap: REFUSAL } }));
      fireEvent.click(start);
      await waitFor(() => expect(createJobMock).toHaveBeenCalledTimes(2));
      expect((createJobMock.mock.calls[1][0] as { mode: string }).mode).toBe('run');
    }

    it('shows the message under the Channels card, exactly once, with a preflight loaded', async () => {
      await refuseStart();
      expect(await screen.findByText(REFUSAL)).toBeInTheDocument();
      expect(screen.getAllByText(REFUSAL)).toHaveLength(1);
      const card = screen.getByText('Channels').closest('[data-slot="card"]') as HTMLElement;
      expect(within(card).getByText(REFUSAL)).toBeInTheDocument();
    });

    it('choosing Skip clears that message', async () => {
      await refuseStart();
      await screen.findByText(REFUSAL);
      await chooseSkipFor(new RegExp(BAD_ID));
      await waitFor(() => expect(screen.queryByText(REFUSAL)).not.toBeInTheDocument());
    });
  });

  it('a new preflight (changing workspace) drops the Skip choice', async () => {
    await renderWithUnreadable();
    await chooseSkipFor(new RegExp(BAD_ID));
    await waitFor(() => expect(channelEntries().some((e) => e.sourceChannelId === BAD_ID)).toBe(true));
    preflightMock.mockResolvedValueOnce(unreadablePreflight());
    act(() => current?.form.setValue('workspaceId', 'wsp-2'));
    await waitFor(() => expect(preflightMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(channelEntries().some((e) => e.sourceChannelId === BAD_ID)).toBe(false));
    expect(rowSelect(new RegExp(BAD_ID))).not.toHaveTextContent('Skip this channel');
  });

  it('does not say the space has no channels while an unreadable id is listed', async () => {
    preflightMock.mockResolvedValueOnce(unreadablePreflight({ channels: [] }));
    render(<MigrationFormView />);
    expect(await screen.findByText(new RegExp(BAD_ID))).toBeInTheDocument();
    expect(screen.queryByText('This space has no channels to migrate.')).not.toBeInTheDocument();
  });

  it('control: with no channels and nothing unreadable the message still shows', async () => {
    preflightMock.mockResolvedValueOnce(preflight({ channels: [], targetChannels: [] }));
    render(<MigrationFormView />);
    expect(await screen.findByText('This space has no channels to migrate.')).toBeInTheDocument();
  });

  it('control: no unreadable ids means no extra row', async () => {
    await renderWithUnreadable(unreadablePreflight({ unreadableChannelIds: [] }));
    expect(screen.queryByText(new RegExp(BAD_ID))).not.toBeInTheDocument();
    expect(screen.getAllByRole('combobox', { name: /^Target channel for / })).toHaveLength(1);
  });

  it('a response from an older server without the field is treated as empty', async () => {
    const older = unreadablePreflight() as Partial<MigrationPreflight>;
    delete older.unreadableChannelIds;
    await renderWithUnreadable(older as MigrationPreflight);
    expect(screen.getAllByRole('combobox', { name: /^Target channel for / })).toHaveLength(1);
    expect(channelEntries().map((e) => e.sourceChannelId)).toEqual(['ch-1']);
  });
});

describe('MigrationFormView - review shows the dry run counts before Start (AC-44-24, pin)', () => {
  it('shows all four blocker lines, before the Start button', async () => {
    const lines = [
      '1 source channel(s) could not be read and were skipped.',
      '2 source user(s) could not be read and were skipped.',
      '3 source custom field(s) could not be read and were skipped.',
      '4 source contact(s) could not be read and were skipped.',
    ];
    createJobMock.mockResolvedValueOnce(doneJob('dry_run', lines));
    getJobMock.mockResolvedValue(doneJob('dry_run', lines));
    await renderWithUnreadable();
    fireEvent.click(screen.getByRole('button', { name: 'Run dry run' }));
    const start = screen.getByRole('button', { name: 'Start migration' });
    for (const line of lines) {
      const el = await screen.findByText(line);
      expect(el.compareDocumentPosition(start) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });
});
