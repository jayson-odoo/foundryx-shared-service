/**
 * FX-03: a one-record undo countdown names the record when the action's
 * config says how (`deferred.fxName`), with the Foundryx UIUX switch on.
 * Without it, and with the switch off, the words are unchanged.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { fxCountdownLabel } from '@/components/fx/toast/fx-deferred-countdown';
import type { ResourceAction, ResourceActionRuntime } from '@/components/platform/resource-list/types';
import { ActionMenu } from './action-menu';
import { DeferredCountdown } from './deferred-action-button';

const deferredToast = vi.hoisted(() => vi.fn());
vi.mock('./deferred-toast', () => ({
  deferredToast,
  dismissDeferredToast: vi.fn(),
}));
vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can: () => true }) }));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({
    start: vi.fn(async (_key: string, targets: { entityId: string }[]) => ({
      commitAt: '2026-11-18T08:00:10.000Z',
      windowSeconds: 10,
      failedCount: 0,
      parkedEntityIds: targets.map((t) => t.entityId),
    })),
    cancel: vi.fn(),
  }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

interface Product {
  id: string;
  name: string;
}

const runtime = { reload: vi.fn() } as unknown as ResourceActionRuntime;

function deleteAction(withName: boolean): ResourceAction<Product> {
  return {
    id: 'delete',
    label: 'Delete',
    tone: 'destructive',
    surfaces: { row: true },
    deferred: {
      actionKey: 'products.delete',
      entityType: 'product',
      ...(withName ? { fxName: (rows: Product[]) => rows[0]?.name } : {}),
    },
  };
}

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

beforeEach(() => {
  deferredToast.mockClear();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('FX-03 one-record countdown names the record', () => {
  it('words (pure)', () => {
    expect(fxCountdownLabel('Deleting', 9200, undefined, undefined, 'Barcode scanner')).toBe(
      'Deleting Barcode scanner in 10 s',
    );
    expect(fxCountdownLabel('Deleting', 9200)).toBe('Deleting in 10 s');
    expect(fxCountdownLabel('Deleting', 9200, 12, 'contacts', 'Barcode scanner')).toBe(
      'Deleting 12 contacts in 10 s',
    );
  });

  it('a row delete hands the name to its countdown', async () => {
    render(
      <ActionMenu
        actions={[deleteAction(true)]}
        rows={[{ id: 'p1', name: 'Barcode scanner' }]}
        runtime={runtime}
        surface="row"
        defaultOpen
      />,
      { wrapper: On },
    );
    fireEvent.click(await screen.findByRole('menuitem', { name: /Delete/ }));
    await waitFor(() => expect(deferredToast).toHaveBeenCalledTimes(1));
    expect(deferredToast.mock.calls[0][0]).toMatchObject({ fxName: 'Barcode scanner' });
  });

  it('without fxName the countdown gets no name', async () => {
    render(
      <ActionMenu
        actions={[deleteAction(false)]}
        rows={[{ id: 'p1', name: 'Barcode scanner' }]}
        runtime={runtime}
        surface="row"
        defaultOpen
      />,
      { wrapper: On },
    );
    fireEvent.click(await screen.findByRole('menuitem', { name: /Delete/ }));
    await waitFor(() => expect(deferredToast).toHaveBeenCalledTimes(1));
    expect(deferredToast.mock.calls[0][0].fxName).toBeUndefined();
  });

  it.each([
    ['on', true, 'Deleting Barcode scanner in 10 s'],
    ['off', false, 'Deleting in 10s'],
  ])('the countdown with the switch %s', (_label, fx, words) => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'setInterval', 'requestAnimationFrame', 'Date'] });
    vi.setSystemTime(new Date('2026-11-18T08:00:00.000Z'));
    const countdown = (
      <DeferredCountdown
        verb="Deleting"
        commitAt="2026-11-18T08:00:10.000Z"
        windowSeconds={10}
        fxName="Barcode scanner"
        onCancel={vi.fn()}
      />
    );
    render(fx ? <On>{countdown}</On> : countdown);
    act(() => {});
    expect(screen.getByRole('timer')).toHaveTextContent(words);
  });
});
