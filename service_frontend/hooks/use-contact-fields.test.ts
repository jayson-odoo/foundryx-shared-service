/**
 * F7 (plan-25 round-3 codex triage): switching between two non-null
 * workspace ids used to leave the PREVIOUS workspace's fields visible until
 * the new fetch resolved (state wasn't cleared on switch), and an
 * out-of-order response (an earlier workspace's slow fetch resolving AFTER a
 * later one) could clobber the newer workspace's data.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ContactField } from '@/types/omnichannel';

const list = vi.fn<(workspaceId: string) => Promise<ContactField[]>>();
vi.mock('@/services/contact-field-service', () => ({
  contactFieldService: {
    list: (workspaceId: string) => list(workspaceId),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function field(over: Partial<ContactField> = {}): ContactField {
  return {
    id: 'f-1',
    workspaceId: 'wsp-1',
    key: 'source',
    label: 'Source',
    description: null,
    type: 'text',
    options: null,
    visibility: 'always',
    sortOrder: 0,
    valuesCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('useContactFields', () => {
  it('F7: clears state immediately on workspace switch (never shows the previous workspace stale)', async () => {
    const { useContactFields } = await import('./use-contact-fields');
    let resolveA!: (fields: ContactField[]) => void;
    list.mockImplementation((workspaceId) => {
      if (workspaceId === 'wsp-a') return new Promise((resolve) => (resolveA = resolve));
      return Promise.resolve([]);
    });

    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useContactFields(id), {
      initialProps: { id: 'wsp-a' },
    });
    resolveA([field({ workspaceId: 'wsp-a', key: 'aOnly' })]);
    await waitFor(() => expect(result.current.fields.map((f) => f.key)).toEqual(['aOnly']));

    // Switch to a DIFFERENT workspace whose fetch hasn't resolved yet.
    let resolveB!: (fields: ContactField[]) => void;
    list.mockImplementation((workspaceId) => {
      if (workspaceId === 'wsp-b') return new Promise((resolve) => (resolveB = resolve));
      return Promise.resolve([]);
    });
    rerender({ id: 'wsp-b' });

    // wsp-a's fields must NOT still be showing for wsp-b.
    await waitFor(() => expect(result.current.fields).toEqual([]));

    resolveB([field({ workspaceId: 'wsp-b', key: 'bOnly' })]);
    await waitFor(() => expect(result.current.fields.map((f) => f.key)).toEqual(['bOnly']));
  });

  it('F7: an out-of-order response from the OLD workspace never clobbers the new one', async () => {
    const { useContactFields } = await import('./use-contact-fields');
    let resolveA!: (fields: ContactField[]) => void;
    let resolveB!: (fields: ContactField[]) => void;
    list.mockImplementation((workspaceId) => {
      if (workspaceId === 'wsp-a') return new Promise((resolve) => (resolveA = resolve));
      if (workspaceId === 'wsp-b') return new Promise((resolve) => (resolveB = resolve));
      return Promise.resolve([]);
    });

    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useContactFields(id), {
      initialProps: { id: 'wsp-a' },
    });
    rerender({ id: 'wsp-b' });

    // wsp-b resolves FIRST, then the stale wsp-a response arrives LATE.
    resolveB([field({ workspaceId: 'wsp-b', key: 'bOnly' })]);
    await waitFor(() => expect(result.current.fields.map((f) => f.key)).toEqual(['bOnly']));

    resolveA([field({ workspaceId: 'wsp-a', key: 'aOnly' })]);
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.fields.map((f) => f.key)).toEqual(['bOnly']); // unchanged
  });
});
