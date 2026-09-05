/**
 * Workspace form tab gating (plan 25, F15 review finding + round-3 F6 fix) -
 * the Contact fields / Tags tabs hang off a real workspace id AND are gated
 * by the SAME read permission the backend GETs require (`conversations.read`
 * OR `contacts.read`). The Lifecycle tab is a STATUS-ENGINE surface (its
 * canvas reads via `statuses.read` and edits via `statuses.manage`, same as
 * every other `EntityFlow` embed) - it is gated SEPARATELY on `statuses.read`,
 * not on `conversations.read`/`contacts.read`, and its canvas is only
 * editable (even while the FORM's own Edit toggle is on) with
 * `statuses.manage`. A user with neither the right read perm nor
 * `statuses.read` never sees a tab that would just 403 (foolproof-UI,
 * UX-only; the API is the real gate).
 */
import { renderHook, waitFor } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import type { Workspace } from '@/types/omnichannel';
import type { useWorkspaceForm as UseWorkspaceForm } from './use-workspace-form';

let can: (key: string) => boolean = () => true;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => can(key) }),
}));

function ws(over: Partial<Workspace> = {}): Workspace {
  return {
    id: 'wsp-1',
    tenantId: 'ten-1',
    name: 'General',
    status: 'ACTIVE',
    channelCount: 0,
    memberCount: 0,
    isDefault: false,
    isTrashed: false,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    get: vi.fn(async () => ws()),
    trash: vi.fn(),
    restore: vi.fn(),
  },
}));

// Dynamic import (not a top-level `await`, which needs an ES2022+ module
// target this project's tsconfig doesn't set) so the `vi.mock` calls above
// are hoisted and applied before `./use-workspace-form` (and its
// `workspace-service`/`use-can` imports) is evaluated.
let useWorkspaceForm: typeof UseWorkspaceForm;

beforeAll(async () => {
  ({ useWorkspaceForm } = await import('./use-workspace-form'));
});

async function loadedConfig(workspaceId = 'wsp-1') {
  const { result } = renderHook(() => useWorkspaceForm(workspaceId, false));
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  return result.current.config!;
}

describe('useWorkspaceForm tab gating', () => {
  it('shows Contact fields/Tags (not Lifecycle) with contacts.read alone', async () => {
    can = (key) => key === 'contacts.read';
    const config = await loadedConfig();
    const ids = config.tabs.map((t) => t.id);
    expect(ids).toContain('contact-fields');
    expect(ids).toContain('tags');
    expect(ids).not.toContain('lifecycle'); // F6 - needs statuses.read, not contacts.read
  });

  it('shows Contact fields/Tags with conversations.read instead', async () => {
    can = (key) => key === 'conversations.read';
    const config = await loadedConfig();
    const ids = config.tabs.map((t) => t.id);
    expect(ids).toContain('contact-fields');
    expect(ids).toContain('tags');
    expect(ids).not.toContain('lifecycle');
  });

  it('F6: shows Lifecycle with statuses.read alone (no contacts/conversations.read)', async () => {
    can = (key) => key === 'statuses.read';
    const config = await loadedConfig();
    const ids = config.tabs.map((t) => t.id);
    expect(ids).toContain('lifecycle');
    expect(ids).not.toContain('contact-fields');
    expect(ids).not.toContain('tags');
  });

  it('hides all four when the user holds none of the permissions', async () => {
    can = () => false;
    const config = await loadedConfig();
    const ids = config.tabs.map((t) => t.id);
    expect(ids).not.toContain('lifecycle');
    expect(ids).not.toContain('contact-fields');
    expect(ids).not.toContain('tags');
    // The always-visible tabs stay.
    expect(ids).toContain('settings');
    expect(ids).toContain('channels');
    expect(ids).toContain('members');
  });

  it('still hides them while creating (AC-CDM-29), even with the permission', async () => {
    can = () => true;
    const { result } = renderHook(() => useWorkspaceForm(undefined, true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const ids = result.current.config!.tabs.map((t) => t.id);
    expect(ids).not.toContain('lifecycle');
    expect(ids).not.toContain('contact-fields');
    expect(ids).not.toContain('tags');
  });

  it('F6: the Lifecycle canvas is READ-ONLY without statuses.manage even while the form is in Edit mode', async () => {
    can = (key) => key === 'statuses.read'; // read, not manage
    const config = await loadedConfig();
    const tab = config.tabs.find((t) => t.id === 'lifecycle')!;
    const el = tab.render({ editing: true }) as { props: { editing: boolean } } | null;
    expect(el?.props.editing).toBe(false);
  });

  it('F6: the Lifecycle canvas is editable with statuses.manage while the form is in Edit mode', async () => {
    can = (key) => key === 'statuses.read' || key === 'statuses.manage';
    const config = await loadedConfig();
    const tab = config.tabs.find((t) => t.id === 'lifecycle')!;
    const el = tab.render({ editing: true }) as { props: { editing: boolean } } | null;
    expect(el?.props.editing).toBe(true);
  });
});
