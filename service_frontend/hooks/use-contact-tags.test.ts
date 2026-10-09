/**
 * F8 (plan-25 round-3 codex triage): same class of bug as F7 for tags -
 * switching between two non-null workspace ids used to leave the PREVIOUS
 * workspace's tags visible until the new fetch resolved.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ContactTag } from '@/types/omnichannel';

const list = vi.fn<(workspaceId: string) => Promise<ContactTag[]>>();
vi.mock('@/services/contact-tag-service', () => ({
  contactTagService: {
    list: (workspaceId: string) => list(workspaceId),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function tag(over: Partial<ContactTag> = {}): ContactTag {
  return {
    id: 't-1',
    workspaceId: 'wsp-1',
    name: 'VIP',
    emoji: null,
    color: null,
    description: null,
    contactsCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('useContactTags', () => {
  it('F8: clears state immediately on workspace switch (never shows the previous workspace stale)', async () => {
    const { useContactTags } = await import('./use-contact-tags');
    let resolveA!: (tags: ContactTag[]) => void;
    list.mockImplementation((workspaceId) => {
      if (workspaceId === 'wsp-a') return new Promise((resolve) => (resolveA = resolve));
      return Promise.resolve([]);
    });

    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useContactTags(id), {
      initialProps: { id: 'wsp-a' },
    });
    resolveA([tag({ workspaceId: 'wsp-a', name: 'aOnly' })]);
    await waitFor(() => expect(result.current.tags.map((t) => t.name)).toEqual(['aOnly']));

    let resolveB!: (tags: ContactTag[]) => void;
    list.mockImplementation((workspaceId) => {
      if (workspaceId === 'wsp-b') return new Promise((resolve) => (resolveB = resolve));
      return Promise.resolve([]);
    });
    rerender({ id: 'wsp-b' });

    await waitFor(() => expect(result.current.tags).toEqual([]));

    resolveB([tag({ workspaceId: 'wsp-b', name: 'bOnly' })]);
    await waitFor(() => expect(result.current.tags.map((t) => t.name)).toEqual(['bOnly']));
  });

  it('F8: an out-of-order response from the OLD workspace never clobbers the new one', async () => {
    const { useContactTags } = await import('./use-contact-tags');
    let resolveA!: (tags: ContactTag[]) => void;
    let resolveB!: (tags: ContactTag[]) => void;
    list.mockImplementation((workspaceId) => {
      if (workspaceId === 'wsp-a') return new Promise((resolve) => (resolveA = resolve));
      if (workspaceId === 'wsp-b') return new Promise((resolve) => (resolveB = resolve));
      return Promise.resolve([]);
    });

    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useContactTags(id), {
      initialProps: { id: 'wsp-a' },
    });
    rerender({ id: 'wsp-b' });

    resolveB([tag({ workspaceId: 'wsp-b', name: 'bOnly' })]);
    await waitFor(() => expect(result.current.tags.map((t) => t.name)).toEqual(['bOnly']));

    resolveA([tag({ workspaceId: 'wsp-a', name: 'aOnly' })]);
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.tags.map((t) => t.name)).toEqual(['bOnly']);
  });
});
