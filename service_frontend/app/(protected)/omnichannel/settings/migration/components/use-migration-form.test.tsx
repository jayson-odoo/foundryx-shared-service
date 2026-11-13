/**
 * Setup form data + submit orchestration (plan 33 S6, AC-MIG-46/47/58) - CSV
 * mode skips preflight entirely (no source-vendor space data exists without
 * an API), the "ready" gate is source-aware (API needs a settled preflight,
 * CSV needs only an uploaded contacts file), the CSV-mode fields are folded
 * into the Start-migration mapping hash, and a 422 `{fieldErrors}` maps onto
 * the RHF fields this form has a slot for (with a toast fallback for the
 * rest).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { MigrationJob, MigrationPreflight } from '@/types/respondio-migration';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/omnichannel/settings/migration/new',
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/services/integration-service', () => ({
  integrationService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/user-service', () => ({
  userService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/team-service', () => ({
  teamService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));

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

let useMigrationForm: typeof import('./use-migration-form').useMigrationForm;

beforeAll(async () => {
  ({ useMigrationForm } = await import('./use-migration-form'));
});

beforeEach(() => {
  preflightMock.mockReset();
  createJobMock.mockReset();
  getJobMock.mockReset();
});

function preflight(overrides: Partial<MigrationPreflight> = {}): MigrationPreflight {
  return {
    apiAvailable: true,
    spaceLabel: 'Acme Support',
    channels: [],
    users: [],
    teams: [],
    fields: [],
    lifecycles: [],
    targetChannels: [],
    targetStages: [],
    warnings: [],
    ...overrides,
  };
}

async function setup() {
  const { result } = renderHook(() => useMigrationForm());
  await waitFor(() => expect(result.current.connections).toEqual([]));
  return result;
}

describe('useMigrationForm - CSV mode skips preflight (AC-MIG-46)', () => {
  it('never calls preflight when source is csv, even with a connection AND workspace chosen', async () => {
    const result = await setup();
    act(() => {
      result.current.form.setValue('source', 'csv');
      result.current.form.setValue('connectionId', 'conn-1');
      result.current.form.setValue('workspaceId', 'wsp-1');
    });
    await waitFor(() => expect(result.current.preflight).toBeNull());
    expect(preflightMock).not.toHaveBeenCalled();
  });

  it('calls preflight when source is api with a connection AND workspace', async () => {
    preflightMock.mockResolvedValueOnce(preflight());
    const result = await setup();
    act(() => {
      result.current.form.setValue('connectionId', 'conn-1');
      result.current.form.setValue('workspaceId', 'wsp-1');
    });
    await waitFor(() => expect(preflightMock).toHaveBeenCalledWith('conn-1', 'wsp-1'));
  });
});

describe('useMigrationForm - "ready" is source-aware (AC-MIG-46/47)', () => {
  it('API mode: ready only once connectionId + workspaceId are both set and preflight settled', async () => {
    preflightMock.mockResolvedValueOnce(preflight());
    const result = await setup();
    expect(result.current.ready).toBe(false);
    act(() => {
      result.current.form.setValue('connectionId', 'conn-1');
      result.current.form.setValue('workspaceId', 'wsp-1');
    });
    await waitFor(() => expect(result.current.ready).toBe(true));
  });

  it('CSV mode: ready only once workspaceId AND contactsUploadId are both set - no connection required', async () => {
    const result = await setup();
    act(() => {
      result.current.form.setValue('source', 'csv');
      result.current.form.setValue('workspaceId', 'wsp-1');
    });
    expect(result.current.ready).toBe(false);
    act(() => {
      result.current.onContactsUploaded({ id: 'upload-a', rowCount: 2, headers: ['First Name'] }, 'contacts.csv');
    });
    await waitFor(() => expect(result.current.ready).toBe(true));
  });
});

describe('useMigrationForm - CSV upload handlers', () => {
  it('onContactsUploaded sets contactsUploadId + headers and clears the field error', async () => {
    const result = await setup();
    act(() => {
      result.current.form.setError('contactsUploadId', { type: 'server', message: 'Upload a contacts CSV.' });
    });
    act(() => {
      result.current.onContactsUploaded({ id: 'upload-a', rowCount: 2, headers: ['First Name', 'Phone'] }, 'contacts.csv');
    });
    expect(result.current.form.getValues('contactsUploadId')).toBe('upload-a');
    expect(result.current.contactsCsvHeaders).toEqual(['First Name', 'Phone']);
    expect(result.current.form.getFieldState('contactsUploadId').error).toBeUndefined();
  });

  it('onContactsCleared resets the key, headers and header map', async () => {
    const result = await setup();
    act(() => {
      result.current.onContactsUploaded({ id: 'upload-a', rowCount: 2, headers: ['First Name'] }, 'contacts.csv');
    });
    act(() => {
      result.current.onContactsCleared();
    });
    expect(result.current.form.getValues('contactsUploadId')).toBeNull();
    expect(result.current.contactsCsvHeaders).toEqual([]);
    expect(result.current.contactsUpload).toBeNull();
  });

  it('switching source back to api clears any CSV-mode upload state', async () => {
    const result = await setup();
    act(() => {
      result.current.form.setValue('source', 'csv');
      result.current.onContactsUploaded({ id: 'upload-a', rowCount: 2, headers: ['First Name'] }, 'contacts.csv');
    });
    act(() => {
      result.current.form.setValue('source', 'api');
    });
    await waitFor(() => expect(result.current.contactsUpload).toBeNull());
    expect(result.current.form.getValues('contactsUploadId')).toBeNull();
  });
});

describe('useMigrationForm - 422 fieldErrors map onto the form (S6)', () => {
  it('a fieldError for a rendered field (connectionId) sets a form error; the rest fall back to a toast', async () => {
    // CSV mode so the CLIENT zod schema passes (workspaceId + contactsUploadId
    // are all it needs) and `runDryRun` actually reaches the server call -
    // the server's own fieldErrors shape is otherwise identical either way.
    const { toast } = await import('@/lib/toast');
    createJobMock.mockRejectedValueOnce(
      new ApiError('Unprocessable', 422, null, {
        fieldErrors: { connectionId: 'A respond.io connection is required.', 'channelMap.0': 'bad target' },
      }),
    );
    const result = await setup();
    act(() => {
      result.current.form.setValue('source', 'csv');
      result.current.form.setValue('workspaceId', 'wsp-1');
      result.current.onContactsUploaded({ id: 'upload-a', rowCount: 1, headers: ['First Name'] }, 'contacts.csv');
    });
    await act(async () => {
      await result.current.runDryRun();
    });
    // `getFieldState` reads RHF's LIVE internal formState directly (unlike
    // `form.formState.errors`, whose exposed Proxy only refreshes on a React
    // re-render of a component that actually reads it - nothing in this
    // bare-hook render does; the `use-team-form.test.tsx` precedent).
    expect(result.current.form.getFieldState('connectionId').error?.message).toBe(
      'A respond.io connection is required.',
    );
    expect(toast.error).toHaveBeenCalledWith('bad target');
  });

  it('a 409 dry_run_required maps to a friendly toast, not a raw "Conflict"', async () => {
    const { toast } = await import('@/lib/toast');
    createJobMock.mockRejectedValueOnce(new ApiError('Conflict', 409, null, { reason: 'dry_run_required' }));
    const result = await setup();
    act(() => {
      result.current.form.setValue('source', 'csv');
      result.current.form.setValue('workspaceId', 'wsp-1');
      result.current.onContactsUploaded({ id: 'upload-a', rowCount: 1, headers: ['First Name'] }, 'contacts.csv');
    });
    await act(async () => {
      await result.current.runDryRun();
    });
    expect(toast.error).toHaveBeenCalledWith('Run a dry run for this exact mapping first.');
  });
});

describe('useMigrationForm - Start-migration mapping hash includes CSV fields', () => {
  it('a successful dry run for a CSV mapping unlocks Start ONLY for that exact contactsUploadId/csvHeaderMap', async () => {
    const dryJob: MigrationJob = {
      id: 'mig-job-1',
      mode: 'dry_run',
      source: 'csv',
      connectionId: '',
      spaceLabel: '',
      workspaceId: 'wsp-1',
      workspaceName: 'Main',
      status: 'done',
      progressTotal: 1,
      progressDone: 1,
      progressFailed: 0,
      entityCounts: { contacts: 1, messages: 0 },
      report: null,
      failureCount: 0,
      failureSample: [],
      startedAt: '2026-01-01T00:00:00Z',
      finishedAt: '2026-01-01T00:00:01Z',
      createdAt: '2026-01-01T00:00:00Z',
      actorUserName: 'You',
      logs: [],
    };
    createJobMock.mockResolvedValueOnce(dryJob);
    // `runDryRun` polls `getJob` once for its status; the "Start unlocked"
    // gate flips on the poll tick that first observes `status === 'done'`
    // (mirrors the mock service's own settle-on-poll design), not on the
    // create response itself.
    getJobMock.mockResolvedValue(dryJob);
    const result = await setup();
    act(() => {
      result.current.form.setValue('source', 'csv');
      result.current.form.setValue('workspaceId', 'wsp-1');
      result.current.onContactsUploaded({ id: 'upload-a', rowCount: 1, headers: ['First Name'] }, 'contacts.csv');
    });
    await act(async () => {
      await result.current.runDryRun();
    });
    await waitFor(() => expect(result.current.canStartMigration).toBe(true));

    // Re-uploading a DIFFERENT file (a new key) re-locks Start immediately.
    act(() => {
      result.current.onContactsUploaded({ id: 'upload-b', rowCount: 5, headers: ['First Name'] }, 'contacts-v2.csv');
    });
    expect(result.current.canStartMigration).toBe(false);
  });
});

describe('useMigrationForm - a failed preflight is exposed, not swallowed', () => {
  function choose(result: Awaited<ReturnType<typeof setup>>, connectionId = 'conn-1') {
    act(() => {
      result.current.form.setValue('connectionId', connectionId);
      result.current.form.setValue('workspaceId', 'wsp-1');
    });
  }

  it('exposes the error when the preflight request rejects', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    const result = await setup();
    expect(result.current.preflightError).toBeNull();
    choose(result);
    await waitFor(() => expect(result.current.preflightError).toBe('The respond.io key was refused.'));
    expect(result.current.preflight).toBeNull();
    expect(result.current.preflightLoading).toBe(false);
  });

  it('exposes a plain message when the rejection is not an ApiError', async () => {
    preflightMock.mockRejectedValueOnce(new Error('socket hang up'));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflightError).toBeTruthy());
  });

  it('clears the error as soon as the next preflight starts', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflightError).not.toBeNull());
    preflightMock.mockReturnValueOnce(new Promise(() => {}));
    choose(result, 'conn-2');
    await waitFor(() => expect(result.current.preflightLoading).toBe(true));
    expect(result.current.preflightError).toBeNull();
  });

  it('clears the error when a later preflight succeeds', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflightError).not.toBeNull());
    preflightMock.mockResolvedValueOnce(preflight());
    choose(result, 'conn-2');
    await waitFor(() => expect(result.current.preflight).not.toBeNull());
    expect(result.current.preflightError).toBeNull();
  });

  it('a rejection that lands after the inputs changed (active false) sets nothing', async () => {
    let rejectFirst: (reason: unknown) => void = () => {};
    preflightMock.mockReturnValueOnce(new Promise((_, reject) => (rejectFirst = reject)));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(preflightMock).toHaveBeenCalledTimes(1));
    preflightMock.mockReturnValueOnce(new Promise(() => {}));
    choose(result, 'conn-2');
    await waitFor(() => expect(preflightMock).toHaveBeenCalledTimes(2));
    await act(async () => {
      rejectFirst(new ApiError('stale failure', 502));
    });
    expect(result.current.preflightError).toBeNull();
    expect(result.current.preflightLoading).toBe(true);
  });

  it('a rejection that lands after unmount sets nothing', async () => {
    let rejectFirst: (reason: unknown) => void = () => {};
    preflightMock.mockReturnValueOnce(new Promise((_, reject) => (rejectFirst = reject)));
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { result, unmount } = renderHook(() => useMigrationForm());
    await waitFor(() => expect(result.current.connections).toEqual([]));
    act(() => {
      result.current.form.setValue('connectionId', 'conn-1');
      result.current.form.setValue('workspaceId', 'wsp-1');
    });
    await waitFor(() => expect(preflightMock).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => {
      rejectFirst(new ApiError('late failure', 502));
    });
    expect(result.current.preflightError).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});

describe('useMigrationForm - clearing and re-running the preflight', () => {
  function choose(result: Awaited<ReturnType<typeof setup>>, connectionId: string | null = 'conn-1') {
    act(() => {
      result.current.form.setValue('connectionId', connectionId);
      result.current.form.setValue('workspaceId', 'wsp-1');
    });
  }

  it('clearing the connection after a failure clears the error', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('The respond.io key was refused.', 400));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflightError).not.toBeNull());
    choose(result, null);
    await waitFor(() => expect(result.current.preflightError).toBeNull());
  });

  it('clearing the connection after a success clears the preflight and the maps', async () => {
    preflightMock.mockResolvedValueOnce(preflight({ channels: [{ id: 'ch-1', name: 'A', source: 'whatsapp_cloud' }] }));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflight).not.toBeNull());
    choose(result, null);
    await waitFor(() => expect(result.current.preflight).toBeNull());
    expect(result.current.form.getValues('channelMap')).toEqual([]);
  });

  it('clearing the connection while in flight stops the loading flag', async () => {
    preflightMock.mockReturnValueOnce(new Promise(() => {}));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflightLoading).toBe(true));
    choose(result, null);
    await waitFor(() => expect(result.current.preflightLoading).toBe(false));
  });

  it('a second preflight after a success replaces the channel map', async () => {
    preflightMock.mockResolvedValueOnce(preflight({ channels: [{ id: 'ch-1', name: 'A', source: 'whatsapp_cloud' }] }));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.form.getValues('channelMap')).toHaveLength(1));
    preflightMock.mockResolvedValueOnce(preflight({ channels: [{ id: 'ch-2', name: 'B', source: 'facebook' }] }));
    choose(result, 'conn-2');
    await waitFor(() =>
      expect(result.current.form.getValues('channelMap').map((c) => c.sourceChannelId)).toEqual(['ch-2']),
    );
  });

  it('a 5xx rejection exposes the plain text, a 4xx exposes its message', async () => {
    preflightMock.mockRejectedValueOnce(new ApiError('Internal Server Error', 503));
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflightError).toBe('Could not check the connection.'));
    preflightMock.mockRejectedValueOnce(new ApiError('Bad key.', 401));
    choose(result, 'conn-2');
    await waitFor(() => expect(result.current.preflightError).toBe('Bad key.'));
  });

  it('the channelMap validation message does not mention a preflight', async () => {
    const result = await setup();
    await act(async () => {
      await result.current.form.trigger();
    });
    const message = result.current.form.getFieldState('channelMap').error?.message ?? '';
    expect(message).not.toBe('');
    expect(message).not.toMatch(/preflight/i);
  });
});


describe('useMigrationForm - unreadable source channels (AC-44-23)', () => {
  const pf = () =>
    preflight({
      channels: [{ id: 'ch-1', name: 'A', source: 'whatsapp_cloud' }],
      unreadableChannelIds: ['src-bad-1'],
    } as Partial<MigrationPreflight>);

  function choose(result: Awaited<ReturnType<typeof setup>>, workspaceId = 'wsp-1') {
    act(() => {
      result.current.form.setValue('connectionId', 'conn-1');
      result.current.form.setValue('workspaceId', workspaceId);
    });
  }

  it('seeds no map entry for an unreadable id', async () => {
    preflightMock.mockResolvedValueOnce(pf());
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflight).not.toBeNull());
    expect(result.current.form.getValues('channelMap').map((e) => e.sourceChannelId)).toEqual(['ch-1']);
  });

  it('a 422 channelMap refusal on the real run lands on the channelMap field, not a toast', async () => {
    const { toast } = await import('@/lib/toast');
    vi.mocked(toast.error).mockClear();
    const dry = { id: 'j1', mode: 'dry_run', source: 'api', status: 'done', report: null } as unknown as MigrationJob;
    preflightMock.mockResolvedValueOnce(pf());
    createJobMock.mockResolvedValueOnce(dry);
    getJobMock.mockResolvedValue(dry);
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflight).not.toBeNull());
    await act(async () => {
      await result.current.runDryRun();
    });
    await waitFor(() => expect(result.current.canStartMigration).toBe(true));
    createJobMock.mockRejectedValueOnce(
      new ApiError('Unprocessable', 422, null, { fieldErrors: { channelMap: 'One channel could not be read.' } }),
    );
    await act(async () => {
      await result.current.startMigration();
    });
    expect(createJobMock).toHaveBeenCalledTimes(2);
    expect(result.current.form.getFieldState('channelMap').error?.message).toBe('One channel could not be read.');
    expect(toast.error).not.toHaveBeenCalledWith('One channel could not be read.');
  });

  it('a new preflight drops a chosen Skip entry', async () => {
    preflightMock.mockResolvedValueOnce(pf());
    const result = await setup();
    choose(result);
    await waitFor(() => expect(result.current.preflight).not.toBeNull());
    act(() => {
      result.current.form.setValue('channelMap', [
        ...result.current.form.getValues('channelMap'),
        { sourceChannelId: 'src-bad-1', targetChannelId: null },
      ]);
    });
    preflightMock.mockResolvedValueOnce(pf());
    choose(result, 'wsp-2');
    await waitFor(() => expect(preflightMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(result.current.form.getValues('channelMap').some((e) => e.sourceChannelId === 'src-bad-1')).toBe(false),
    );
  });
});
