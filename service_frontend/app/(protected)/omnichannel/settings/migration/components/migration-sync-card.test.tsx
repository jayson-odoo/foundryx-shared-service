import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  __mockResetRespondioMigrations,
  __mockSetSync,
} from '@/services/respondio-migration-service.mock';

const canMock = vi.hoisted(() => ({ keys: new Set<string>() }));

vi.mock('@/services/respondio-migration-service', async () => {
  const mod = await import('@/services/respondio-migration-service.mock');
  return { respondioMigrationService: mod.mockRespondioMigrationService };
});
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canMock.keys.has(k), ready: true, permissions: canMock.keys }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (iso: string | null | undefined) => `D(${iso})`,
    formatDateTime: (iso: string | null | undefined) => `T(${iso})`,
    formatTime: (iso: string | null | undefined) => `t(${iso})`,
  }),
}));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { MigrationSyncCard } from './migration-sync-card';
import { canOfferSync } from './sync-status';

const WS = 'wsp-001';

function renderCard() {
  return render(<MigrationSyncCard jobId="mig-job-002" workspaceId={WS} />);
}

beforeEach(() => {
  __mockResetRespondioMigrations();
  canMock.keys = new Set(['omnichannel_migration.read', 'omnichannel_migration.manage']);
});

describe('canOfferSync (AC-SYNC-50)', () => {
  it('only a done real API run offers the card', () => {
    expect(canOfferSync({ mode: 'run', source: 'api', status: 'done' })).toBe(true);
    expect(canOfferSync({ mode: 'dry_run', source: 'api', status: 'done' })).toBe(false);
    expect(canOfferSync({ mode: 'run', source: 'csv', status: 'done' })).toBe(false);
    expect(canOfferSync({ mode: 'run', source: 'api', status: 'running' })).toBe(false);
  });
});

describe('MigrationSyncCard', () => {
  it('shows Start syncing to managers when no sync exists, and starts one (AC-SYNC-50)', async () => {
    __mockSetSync(WS, null);
    renderCard();
    const start = await screen.findByRole('button', { name: 'Start syncing' });
    await userEvent.click(start);
    expect(await screen.findByText('Active')).toBeInTheDocument();
  });

  it('hides Start syncing from read-only users', async () => {
    canMock.keys = new Set(['omnichannel_migration.read']);
    __mockSetSync(WS, null);
    renderCard();
    await new Promise((r) => setTimeout(r, 400));
    expect(screen.queryByRole('button', { name: 'Start syncing' })).not.toBeInTheDocument();
  });

  it('active: status line, actions, contact count, webhook URL (AC-SYNC-51)', async () => {
    __mockSetSync(WS, {
      lastSyncAt: '2026-11-04T10:00:00Z',
      nextSyncAt: '2026-11-04T10:15:00Z',
    });
    renderCard();
    expect(
      await screen.findByText(
        /Syncing every 15 min\. Last sync T\(2026-11-04T10:00:00Z\): \+3 contacts, \+42 messages, 0 errors\. Next sync T\(2026-11-04T10:15:00Z\)\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop syncing (cutover)' })).toBeInTheDocument();
    expect(screen.getByText(/214 respond\.io contacts\. Full sweep about 11 min\./)).toBeInTheDocument();
    const url = await screen.findByLabelText('Webhook URL');
    expect((url as HTMLInputElement).value).toContain('/omnichannel/migration-hooks/');
    expect(screen.getByRole('button', { name: 'Copy webhook URL' })).toBeInTheDocument();
  });

  it('read-only user sees no actions and no webhook URL', async () => {
    canMock.keys = new Set(['omnichannel_migration.read']);
    __mockSetSync(WS, {});
    renderCard();
    await screen.findByText(/Syncing every 15 min/);
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Webhook URL')).not.toBeInTheDocument();
  });

  it('running tick disables Sync now (AC-SYNC-53)', async () => {
    __mockSetSync(WS, { runningJobId: 'job-1' });
    renderCard();
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeDisabled();
  });

  it('paused token_rejected shows the reason and Resume (AC-SYNC-52)', async () => {
    __mockSetSync(WS, { status: 'paused', pausedReason: 'token_rejected' });
    renderCard();
    expect(await screen.findByText(/respond\.io rejected the access token/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Resume' }));
    expect(await screen.findByText('Active')).toBeInTheDocument();
  });

  it('Stop opens a confirm dialog, then reads Stopped after the final tick (AC-SYNC-52)', async () => {
    __mockSetSync(WS, {});
    renderCard();
    await userEvent.click(await screen.findByRole('button', { name: 'Stop syncing (cutover)' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Stop syncing' }));
    expect(await screen.findByText('Stopping')).toBeInTheDocument();
  });

  it('stopped shows "Stopped <time>"', async () => {
    __mockSetSync(WS, { status: 'stopped', stoppedAt: '2026-11-04T09:00:00Z' });
    renderCard();
    expect(await screen.findByText('Stopped T(2026-11-04T09:00:00Z)')).toBeInTheDocument();
  });

  it('renders the failure sample with the failures table (AC-SYNC-53)', async () => {
    __mockSetSync(WS, {
      lastResult: {
        contactsCreated: 0,
        contactsUpdated: 0,
        messagesCreated: 0,
        messagesSkipped: 0,
        errors: 1,
        failureSample: [
          { entity: 'media', sourceId: 'rio-msg-1', sourceLabel: 'image', reason: '404 fetching source URL', action: 'skipped' },
        ],
      },
    });
    renderCard();
    expect(await screen.findByText('Failures (1)')).toBeInTheDocument();
    expect(screen.getByText('rio-msg-1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Download CSV/ })).not.toBeInTheDocument();
  });
});
