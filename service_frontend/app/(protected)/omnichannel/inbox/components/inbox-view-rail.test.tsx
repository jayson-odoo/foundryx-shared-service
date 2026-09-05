/**
 * AC-IVE-20/22/48 - the view rail's per-view manage control: own view (by
 * REAL session user id, not a hardcoded id) always offers Rename/Delete;
 * someone else's non-shared view only does with `inbox_views.manage`.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ConversationFilters } from '@/hooks/use-conversations';
import { DEFAULT_FILTERS } from '@/hooks/use-conversations';
import type { InboxView } from '@/types/omnichannel';

import { InboxViewRail } from './inbox-view-rail';

const { useSessionMock } = vi.hoisted(() => ({ useSessionMock: vi.fn() }));
vi.mock('next-auth/react', () => ({ useSession: useSessionMock }));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

const { useInboxViewsMock } = vi.hoisted(() => ({ useInboxViewsMock: vi.fn() }));
vi.mock('@/hooks/use-inbox-views', () => ({ useInboxViews: useInboxViewsMock }));

const { useStatusGraphMock } = vi.hoisted(() => ({ useStatusGraphMock: vi.fn() }));
vi.mock('@/hooks/use-status-engine', () => ({ useStatusGraph: useStatusGraphMock }));

function withSession(userId: string, perms: string[] = []) {
  useSessionMock.mockReturnValue({
    status: 'authenticated',
    data: { user: { id: userId, permissions: perms } },
  });
}

function view(over: Partial<InboxView> = {}): InboxView {
  return {
    id: 'view-1',
    workspaceId: 'wsp-001',
    name: 'My view',
    ownerUserId: 'usr-owner',
    ownerName: 'Owner',
    isShared: false,
    filter: {},
    sortOrder: 0,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

function renderRail(views: InboxView[], filters: ConversationFilters = DEFAULT_FILTERS) {
  useInboxViewsMock.mockReturnValue({
    views,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  });
  useStatusGraphMock.mockReturnValue({ graph: null });
  render(
    <InboxViewRail workspaceId="wsp-001" filters={filters} setFilters={vi.fn()} variant="sidebar" />,
  );
}

describe('InboxViewRail - manage control by real owner', () => {
  it('shows Manage for the caller\'s OWN view (matched by the real session user id)', () => {
    withSession('usr-owner', []);
    renderRail([view({ ownerUserId: 'usr-owner' })]);
    expect(screen.getByTestId('rail-view-menu-view-1')).toBeInTheDocument();
  });

  it('hides Manage for another user\'s view without inbox_views.manage', () => {
    withSession('usr-other', []);
    renderRail([view({ ownerUserId: 'usr-owner' })]);
    expect(screen.queryByTestId('rail-view-menu-view-1')).not.toBeInTheDocument();
  });

  it('shows Manage for another user\'s view WITH inbox_views.manage', () => {
    withSession('usr-other', ['inbox_views.manage']);
    renderRail([view({ ownerUserId: 'usr-owner' })]);
    expect(screen.getByTestId('rail-view-menu-view-1')).toBeInTheDocument();
  });

  it('hides Manage for a SHARED view the caller does not own, without the permission', () => {
    withSession('usr-other', []);
    renderRail([view({ ownerUserId: 'usr-owner', isShared: true })]);
    expect(screen.queryByTestId('rail-view-menu-view-1')).not.toBeInTheDocument();
  });
});
