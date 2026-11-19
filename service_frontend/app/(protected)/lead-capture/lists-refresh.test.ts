/**
 * Crew pass 041306ae: after an Add the list was remounted (`key={nonce}`), and a
 * remount re-reads the address bar as it was at page load, so a cleared search
 * came back. The pages now refresh the list through its fetcher instead.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useLeadKeyList } from './keys/components/use-lead-key-list';
import { useReceiverList } from './delivery/components/use-receiver-list';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/services/lead-capture-service', () => ({
  leadCaptureService: { listReceivers: vi.fn().mockResolvedValue([]), listKeys: vi.fn().mockResolvedValue([]), sendTestPush: vi.fn() },
}));

describe('Lead Capture lists refresh without a remount', () => {
  it('a new refresh key gives the receivers list a new fetcher (it refetches, keeping its query)', () => {
    const onCreate = vi.fn();
    const onChanged = vi.fn();
    const { result, rerender } = renderHook(({ k }) => useReceiverList(onCreate, onChanged, k), {
      initialProps: { k: 0 },
    });
    const first = result.current.fetcher;
    rerender({ k: 0 });
    expect(result.current.fetcher).toBe(first);
    rerender({ k: 1 });
    expect(result.current.fetcher).not.toBe(first);
  });

  it('a new refresh key gives the keys list a new fetcher', () => {
    const onCreate = vi.fn();
    const { result, rerender } = renderHook(({ k }) => useLeadKeyList(onCreate, k), { initialProps: { k: 0 } });
    const first = result.current.fetcher;
    rerender({ k: 1 });
    expect(result.current.fetcher).not.toBe(first);
  });

  it.each(['delivery/page.tsx', 'keys/page.tsx'])('%s never remounts its list with a key', (file) => {
    const src = readFileSync(join(__dirname, file), 'utf8');
    expect(src).not.toMatch(/<ResourceList\s+key=/);
  });
});
