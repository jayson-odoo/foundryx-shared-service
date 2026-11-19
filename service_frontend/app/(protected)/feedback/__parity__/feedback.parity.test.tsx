/**
 * Switch-off parity for the feedback pages (see
 * components/fx/__parity__/parity-utils.ts). Recorded on the code before the
 * W6-FEEDBACK slice: the ideas list, the board, an idea record (read, editing,
 * new), its comments, the business requirements list and the embed
 * connections page, rendered with the Foundryx UIUX switch off. A change that
 * needs one of these snapshots updated changes what a user sees today: fix
 * the code, never the snapshot.
 */
import type { ReactElement } from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import IdeasPage from '../page';
import BoardPage from '../board/page';
import BrPage from '../business-requirements/page';
import EmbedConnectionsPage from '../embed-connections/page';
import { IdeaFormView } from '../components/idea-form-view';
import { IdeaComments } from '../components/idea-comments';
import { Look, writes, ALL_PERMISSIONS } from './fb-kit';

const nav = vi.hoisted(() => ({ path: '/feedback' }));
const perms = vi.hoisted(() => [] as string[]);

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => nav.path),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { id: 'me', name: 'Demo Admin', permissions: perms } },
    status: 'authenticated',
  }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ state: { status: 'idle' }, start: vi.fn(async () => ({})), cancel: vi.fn() }),
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

perms.push(...ALL_PERMISSIONS);

afterEach(() => {
  writes.length = 0;
});

async function snapOff(path: string, ui: ReactElement, ready: (root: HTMLElement) => boolean) {
  nav.path = path;
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Look fx={false}>{ui}</Look>);
  });
  await waitFor(() => expect(ready(utils.container)).toBe(true));
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  const html = parityHtml(utils.container);
  utils.unmount();
  return html;
}

const hasText = (text: string) => (root: HTMLElement) => root.textContent?.includes(text) ?? false;

describe('feedback switch-off parity', () => {
  it('ideas list', async () => {
    expect(await snapOff('/feedback', <IdeasPage />, hasText('Dark mode for the dashboard'))).toMatchSnapshot();
  });

  it('board', async () => {
    expect(await snapOff('/feedback/board', <BoardPage />, hasText('Linked to BR'))).toMatchSnapshot();
  });

  it('idea record, read', async () => {
    expect(
      await snapOff('/feedback/idea-1', <IdeaFormView ideaId="idea-1" initialEditing={false} />, hasText('Export orders to Excel')),
    ).toMatchSnapshot();
  });

  it('idea record, editing', async () => {
    expect(
      await snapOff('/feedback/idea-1', <IdeaFormView ideaId="idea-1" initialEditing />, hasText('Export orders to Excel')),
    ).toMatchSnapshot();
  });

  it('new idea', async () => {
    expect(await snapOff('/feedback/new', <IdeaFormView initialEditing />, hasText('New feedback'))).toMatchSnapshot();
  });

  it('idea comments', async () => {
    expect(await snapOff('/feedback/idea-1', <IdeaComments ideaId="idea-1" canComment />, hasText('Looks good to me'))).toMatchSnapshot();
  });

  it('business requirements list', async () => {
    expect(await snapOff('/feedback/business-requirements', <BrPage />, hasText('Order export to Excel'))).toMatchSnapshot();
  });

  it('embed connections', async () => {
    expect(await snapOff('/feedback/embed-connections', <EmbedConnectionsPage />, hasText('sorento-feedback'))).toMatchSnapshot();
  });
});
