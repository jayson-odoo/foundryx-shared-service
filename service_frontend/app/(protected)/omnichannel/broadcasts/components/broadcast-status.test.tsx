/**
 * Broadcast status registry + counts rendering (plan 29 S4, AC-BRD-10) - the
 * registry must carry EVERY status/recipient-state key the wire can send (a
 * forgotten key renders a blank/broken badge on real data), and the
 * Overview `StatusSummary` card must render the live counts + status pill
 * off a real `Broadcast` row (no polling - this is what the WS handler
 * refreshes into).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Broadcast, BroadcastRecipientState, BroadcastStatus } from '@/types/omnichannel';
import { BROADCAST_STATUS_REGISTRY, BROADCAST_STATUS_SEGMENTS, RECIPIENT_STATE_REGISTRY } from './broadcast-status';
import { StatusSummary } from './broadcast-form-sections';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (v: string) => v, formatDate: (v: string) => v }),
}));

const ALL_STATUSES: BroadcastStatus[] = ['DRAFT', 'SCHEDULED', 'SENDING', 'SENT', 'CANCELLED', 'FAILED'];
const ALL_RECIPIENT_STATES: BroadcastRecipientState[] = ['queued', 'sent', 'delivered', 'read', 'failed', 'skipped'];

describe('BROADCAST_STATUS_REGISTRY', () => {
  it('carries an entry for every wire status key', () => {
    for (const status of ALL_STATUSES) {
      expect(BROADCAST_STATUS_REGISTRY[status]).toBeTruthy();
      expect(BROADCAST_STATUS_REGISTRY[status].label).toBeTruthy();
    }
  });

  it('the list segments mirror the registry keys plus the "all" sentinel', () => {
    const ids = BROADCAST_STATUS_SEGMENTS.map((s) => s.id);
    expect(ids).toEqual(['all', ...ALL_STATUSES]);
  });
});

describe('RECIPIENT_STATE_REGISTRY', () => {
  it('carries an entry for every recipient state the state machine can reach', () => {
    for (const state of ALL_RECIPIENT_STATES) {
      expect(RECIPIENT_STATE_REGISTRY[state]).toBeTruthy();
      expect(RECIPIENT_STATE_REGISTRY[state].label).toBeTruthy();
    }
  });
});

function broadcast(overrides: Partial<Broadcast> = {}): Broadcast {
  return {
    id: 'bcst-1',
    workspaceId: 'wsp-1',
    name: 'Flash sale blast',
    labels: [],
    channelId: 'chn-1',
    channelName: 'Demo WhatsApp',
    audience: { kind: 'contacts', contactIds: ['cnt-1'] },
    templateId: 'tpl-1',
    templateName: 'booking_update',
    templateLanguage: 'en_US',
    bindings: { header: [], body: [], buttons: [] },
    status: 'SENDING',
    statusLabel: 'Sending',
    scheduledAt: null,
    startedAt: '2026-01-01T00:00:00Z',
    finishedAt: null,
    counts: { total: 40, sent: 12, delivered: 8, read: 4, failed: 1, skipped: 1 },
    jobId: 'job-1',
    error: null,
    createdByUserId: 'usr-1',
    createdByName: 'You',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('StatusSummary', () => {
  it('renders the status pill and every count from the live broadcast row', () => {
    render(<StatusSummary broadcast={broadcast()} />);
    expect(screen.getByText('Sending')).toBeInTheDocument();
    expect(screen.getByText('40')).toBeInTheDocument(); // total
    expect(screen.getByText('12')).toBeInTheDocument(); // sent
    expect(screen.getByText('8')).toBeInTheDocument(); // delivered
    expect(screen.getByText('4')).toBeInTheDocument(); // read
    // failed and skipped are both "1" - assert the labelled stat exists twice.
    expect(screen.getAllByText('1')).toHaveLength(2);
  });

  it('renders the error banner only when the broadcast actually failed', () => {
    const { rerender } = render(<StatusSummary broadcast={broadcast()} />);
    expect(screen.queryByText(/no longer approved/)).not.toBeInTheDocument();

    rerender(
      <StatusSummary
        broadcast={broadcast({ status: 'FAILED', statusLabel: 'Failed', error: 'Template is no longer approved on this channel.' })}
      />,
    );
    expect(screen.getByText('Template is no longer approved on this channel.')).toBeInTheDocument();
  });
});
