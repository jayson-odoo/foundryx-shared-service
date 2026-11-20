/**
 * The board under the Foundryx UIUX switch: a drag does the same thing in both
 * looks (same status request, same ordering payload, same refusal), and the
 * board keeps its legacy look inside the components-off boundary (the embed).
 * The drag gesture itself is replaced by a stand-in that calls the board's own
 * move handler, since jsdom cannot drag.
 */
import type { ReactNode } from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FxComponentsOff } from '@/components/fx/fx-components-off';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { TriageBoard } from '../board/triage-board';
import { IdeaFormView } from '../components/idea-form-view';
import { SecretReveal } from '../embed-connections/secret-reveal';
import { Look, writes, ALL_PERMISSIONS, type RecordedWrite } from './fb-kit';

const perms = vi.hoisted(() => [] as string[]);
const move = vi.hoisted(() => ({
  onMove: null as null | ((e: unknown) => Promise<void>),
}));

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/feedback/board'),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { id: 'me', name: 'Demo Admin', permissions: perms } },
    status: 'authenticated',
  }),
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  const kit = await import('./fb-kit');
  return {
    ...actual,
    apiFetch: vi.fn(kit.fakeApiFetch),
    apiFetchText: vi.fn(async () => ''),
    apiFetchBlob: vi.fn(async () => new Blob()),
  };
});
// A stand-in for the drag library: renders the board's own markup and lets a
// test fire the board's move handler.
vi.mock('@/components/ui/kanban', () => {
  const pass = ({ children, className }: { children?: ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  );
  return {
    Kanban: ({ children, onMove }: { children?: ReactNode; onMove: (e: unknown) => Promise<void> }) => {
      move.onMove = onMove;
      return <div>{children}</div>;
    },
    KanbanBoard: pass,
    KanbanColumn: pass,
    KanbanColumnContent: pass,
    KanbanItem: pass,
    KanbanItemHandle: ({ children }: { children?: ReactNode }) => <>{children}</>,
    KanbanOverlay: () => null,
  };
});

perms.push(...ALL_PERMISSIONS);

afterEach(() => {
  writes.length = 0;
  move.onMove = null;
  document.body.innerHTML = '';
});

async function drag(fx: boolean, id: string, from: string, to: string): Promise<RecordedWrite[]> {
  writes.length = 0;
  let unmount!: () => void;
  await act(async () => {
    unmount = render(
      <Look fx={fx}>
        <TriageBoard />
      </Look>,
    ).unmount;
  });
  await waitFor(() => expect(document.body.textContent).toContain('Linked to BR'));
  await act(async () => {
    await move.onMove?.({
      event: { active: { id } },
      activeContainer: from,
      overContainer: to,
    });
  });
  const out = writes.map((w) => ({ ...w }));
  unmount();
  document.body.innerHTML = '';
  return out;
}

describe('a drag does the same in both looks', () => {
  it('an allowed move sends the status request then the ordering payload', async () => {
    const off = await drag(false, 'idea-1', 'idea-status-captured', 'idea-status-triaged');
    const on = await drag(true, 'idea-1', 'idea-status-captured', 'idea-status-triaged');
    expect(off.map((w) => w.path)).toEqual(['/ideation/ideas/idea-1/status', '/ideation/ideas/reorder']);
    expect(on).toEqual(off);
  });

  it('a reorder inside one column sends only the ordering payload', async () => {
    const off = await drag(false, 'idea-1', 'idea-status-captured', 'idea-status-captured');
    const on = await drag(true, 'idea-1', 'idea-status-captured', 'idea-status-captured');
    expect(off.map((w) => w.path)).toEqual(['/ideation/ideas/reorder']);
    expect(on).toEqual(off);
  });

  it('a move the card cannot make is refused with no request in both looks', async () => {
    const off = await drag(false, 'idea-1', 'idea-status-captured', 'idea-status-linked');
    const on = await drag(true, 'idea-1', 'idea-status-captured', 'idea-status-linked');
    expect(off).toEqual([]);
    expect(on).toEqual([]);
  });
});

describe('shared pieces keep the legacy look outside the switch', () => {
  async function html(ui: ReactNode): Promise<string> {
    let utils!: ReturnType<typeof render>;
    await act(async () => {
      utils = render(ui as React.ReactElement);
    });
    await waitFor(() => expect(utils.container.textContent?.length).toBeGreaterThan(5));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    // React ids differ between two renders in one file; mask them.
    const out = parityHtml(utils.container).replace(/_r_[0-9a-z]+_/g, '_r_N_');
    utils.unmount();
    return out;
  }

  it('the board renders the legacy look under the components-off boundary', async () => {
    const off = await html(
      <Look fx={false}>
        <TriageBoard />
      </Look>,
    );
    const guarded = await html(
      <Look fx>
        <FxComponentsOff>
          <TriageBoard />
        </FxComponentsOff>
      </Look>,
    );
    expect(guarded).toBe(off);
    const on = await html(
      <Look fx>
        <TriageBoard />
      </Look>,
    );
    expect(on).not.toBe(off);
  });

  it('the idea record renders the legacy look under the components-off boundary', async () => {
    const off = await html(
      <Look fx={false}>
        <IdeaFormView ideaId="idea-1" initialEditing={false} />
      </Look>,
    );
    const guarded = await html(
      <Look fx>
        <FxComponentsOff>
          <IdeaFormView ideaId="idea-1" initialEditing={false} />
        </FxComponentsOff>
      </Look>,
    );
    expect(guarded).toBe(off);
  });

  it('the secret field renders the legacy look under the components-off boundary', async () => {
    const off = await html(
      <Look fx={false}>
        <SecretReveal secret="abcdefgh12345678" />
      </Look>,
    );
    const guarded = await html(
      <Look fx>
        <FxComponentsOff>
          <SecretReveal secret="abcdefgh12345678" />
        </FxComponentsOff>
      </Look>,
    );
    expect(guarded).toBe(off);
    const on = await html(
      <Look fx>
        <SecretReveal secret="abcdefgh12345678" />
      </Look>,
    );
    expect(on).not.toBe(off);
  });
});
