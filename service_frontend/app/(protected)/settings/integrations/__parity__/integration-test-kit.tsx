/**
 * Shared fixtures and service stand-ins for the integrations pages' switch-off
 * parity tests and their switch-on request tests (Foundryx UIUX, slice
 * W4-TEMPLATES). Every service call lands in `calls` with its arguments, so a
 * test can compare what reached the backend with the switch off and with it on.
 *
 * Test files mock the services with factories that import this module:
 *   vi.mock('@/services/integration-service', async () => (await import('./integration-test-kit')).integrationServiceMock);
 */
import { act } from '@testing-library/react';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';
import type { Connection, IntegrationProvider } from '@/types/integration';

/** Every recorded service call and toast, in order. */
export const calls: unknown[][] = [];

export function resetCalls(): void {
  calls.length = 0;
}

/** Only the calls that write data or send something (no reads, no toasts). */
export const WRITE_CALLS = new Set([
  'integration.create',
  'integration.update',
  'integration.remove',
  'integration.test',
  'integration.activate',
  'pending.park',
]);

export function writeCalls(): unknown[][] {
  return calls.filter((c) => WRITE_CALLS.has(String(c[0])));
}

/** React 19's `_r_N_` ids renamed in order, and timings and mid-animation styles masked. */
export function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>')
    // Radix sets a tab's animation style only when it catches the animation
    // mid-way, so whether the attribute is filled is timing, not markup.
    .replace(/style="(animation-duration: <t>;)?"/g, 'style="<anim>"');
}

export async function settle(ms = 50): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

// --- fixtures ---------------------------------------------------------------

export const SMTP: IntegrationProvider = {
  provider: 'smtp',
  type: 'email',
  title: 'SMTP mail server',
  description: 'Send email through your own mail server.',
  icon: 'mail',
  fields: [
    { key: 'host', label: 'Host', type: 'text', required: true, placeholder: 'smtp.example.com' },
    { key: 'port', label: 'Port', type: 'number', required: true, defaultValue: '587' },
    { key: 'username', label: 'Username', type: 'text', required: true },
    { key: 'password', label: 'Password', type: 'password', required: true, secret: true, placeholder: 'App password' },
    { key: 'fromEmail', label: 'From email', type: 'text', required: true },
    {
      key: 'security',
      label: 'Security',
      type: 'select',
      required: false,
      advanced: true,
      defaultValue: 'starttls',
      options: [
        { value: 'starttls', label: 'STARTTLS' },
        { value: 'ssl', label: 'SSL' },
      ],
    },
  ],
  testLabel: 'Send test email',
  testTarget: { label: 'Send a test to', placeholder: 'you@example.com' },
};

export const S3: IntegrationProvider = {
  provider: 's3',
  type: 'storage',
  title: 'Amazon S3',
  description: 'Store files in your own bucket.',
  icon: 'cloud',
  fields: [
    { key: 'bucket', label: 'Bucket', type: 'text', required: true },
    { key: 'accessKeyId', label: 'Access key id', type: 'text', required: true },
    { key: 'secretAccessKey', label: 'Secret access key', type: 'password', required: true, secret: true },
    { key: 'sessionToken', label: 'Session token', type: 'password', required: false, secret: true, advanced: true },
  ],
  testLabel: 'Test connection',
  testTarget: null,
};

/** A provider that offers no test (the meetings notetaker account). */
export const NOTETAKER: IntegrationProvider = {
  provider: 'notetaker',
  type: 'meeting_bot',
  title: 'Meeting notetaker',
  description: 'The account the notetaker joins meetings as.',
  icon: 'bot',
  fields: [{ key: 'account', label: 'Account', type: 'text', required: true }],
  testLabel: '',
  testTarget: null,
};

export const PROVIDERS = [SMTP, S3, NOTETAKER];

export function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'con-1',
    tenantId: 'ten-1',
    provider: 'smtp',
    type: 'email',
    name: 'Company mail',
    config: { host: 'smtp.maju.my', port: '587', username: 'mailer', fromEmail: 'hello@maju.my', security: 'starttls' },
    status: 'ACTIVE',
    isActive: false,
    lastTestedAt: '2026-11-12T06:14:00Z',
    lastError: null,
    rateLimitPerMinute: 60,
    createdAt: '2026-10-01T02:00:00Z',
    updatedAt: '2026-11-12T06:14:00Z',
    ...overrides,
  };
}

export function storageConnection(overrides: Partial<Connection> = {}): Connection {
  return connection({
    id: 'con-2',
    provider: 's3',
    type: 'storage',
    name: 'Files bucket',
    config: { bucket: 'maju-files', accessKeyId: 'AKIAEXAMPLE' },
    status: 'ERROR',
    lastError: 'The access key was refused.',
    isActive: true,
    ...overrides,
  });
}

/** What the stand-in services answer; tests change these per scenario. */
export const answers = {
  connection: connection(),
  list: [connection(), storageConnection()] as Connection[],
  testOk: true,
  createFails: false,
};

const ok = <T,>(value: T) => Promise.resolve(value);

function rec<A extends unknown[], R>(name: string, fn: (...args: A) => R) {
  return (...args: A): R => {
    // Deep copy so a later mutation cannot rewrite what was recorded.
    calls.push([name, ...JSON.parse(JSON.stringify(args ?? []))]);
    return fn(...args);
  };
}

export const integrationServiceMock = {
  integrationService: {
    providers: () => ok(PROVIDERS),
    list: () => ok({ data: answers.list, total: answers.list.length }),
    get: (id: string) => {
      calls.push(['integration.get', id]);
      const found = [answers.connection, ...answers.list].find((c) => c.id === id);
      return found ? ok(found) : Promise.reject(new Error('Not found'));
    },
    getAt: () => ok({ connection: answers.connection, total: 2 }),
    exportCsv: rec('integration.exportCsv', () => ok('')),
    create: rec('integration.create', (input: { name: string; provider: string; config: Record<string, string> }) =>
      answers.createFails
        ? Promise.reject(new Error('A storage connection already exists. Disconnect Files bucket first.'))
        : ok(
            connection({
              id: 'con-9',
              name: input.name,
              provider: input.provider,
              config: input.config,
              status: 'UNVERIFIED',
              lastTestedAt: null,
            }),
          ),
    ),
    update: rec('integration.update', (id: string, input: { name?: string; config?: Record<string, string> }) =>
      ok({ ...answers.connection, id, name: input.name ?? answers.connection.name, config: input.config ?? answers.connection.config }),
    ),
    remove: rec('integration.remove', () => ok(undefined)),
    test: rec('integration.test', () =>
      ok(
        answers.testOk
          ? { ok: true, message: 'Connected and signed in.', checkedAt: '2026-11-19T03:00:00Z' }
          : { ok: false, message: 'The server refused the password.', checkedAt: '2026-11-19T03:00:00Z' },
      ),
    ),
    activate: rec('integration.activate', () => ok(answers.connection)),
  },
};

export const pendingActionsServiceMock = {
  pendingActionsService: {
    park: rec('pending.park', () =>
      ok({ id: 'pa-1', status: 'PENDING', executeAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10 }),
    ),
    cancel: () => ok({ id: 'pa-1', status: 'CANCELLED' }),
    current: () => ok({ pending: null }),
  },
};

export const preferencesServiceMock = {
  preferencesService: {
    get: () => ok(null),
    save: () => ok(undefined),
  },
};

const toastFn = (kind: string) => (...args: unknown[]) => {
  calls.push([`toast.${kind}`, ...args]);
  return 'toast-id';
};

export const toastMock = {
  toast: {
    success: toastFn('success'),
    error: toastFn('error'),
    info: toastFn('info'),
    warning: toastFn('warning'),
    message: toastFn('message'),
    custom: toastFn('custom'),
    dismiss: toastFn('dismiss'),
    fxDone: toastFn('fxDone'),
  },
};
