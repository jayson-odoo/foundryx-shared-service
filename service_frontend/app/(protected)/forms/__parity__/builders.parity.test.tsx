/**
 * Switch-off parity for the workflows and forms pages (see
 * components/fx/__parity__/parity-utils.ts). Recorded on the code before the
 * W6-BUILDERS slice: the two lists, each record read and editing, the new
 * forms, the fill page and a submission, rendered with the Foundryx UIUX
 * switch off. The workflow canvas, the form builder and the flow editor are
 * stood in for (they stay as they are). A change that needs one of these
 * snapshots updated changes what a user sees today: fix the code, never the
 * snapshot.
 */
import type { ReactElement } from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import WorkflowsPage from '../../workflows/page';
import FormsPage from '../page';
import { WorkflowFormView } from '../../workflows/components/workflow-form-view';
import { FormDetailView } from '../components/form-detail-view';
import FormFillPage from '../[id]/fill/page';
import FormSubmissionPage from '../[id]/submissions/[submissionId]/page';
import { Look, writes } from './builders-kit';

const nav = vi.hoisted(() => ({
  path: '/forms',
  params: {} as Record<string, string>,
  search: '' as string,
}));

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => nav.path),
  useSearchParams: vi.fn(() => new URLSearchParams(nav.search)),
  useParams: vi.fn(() => nav.params),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));
vi.mock('next-auth/react', async () => {
  const kit = await import('./builders-kit');
  return {
    useSession: () => ({
      data: { user: { id: 'me', name: 'Demo Admin', permissions: kit.ALL_PERMISSIONS } },
      status: 'authenticated',
    }),
  };
});
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
// The canvases and editors stay as they are; they are stood in for here.
vi.mock('../../workflows/components/workflow-editor-tab', () => ({
  WorkflowEditorTab: () => <div data-testid="workflow-canvas" />,
}));
vi.mock('../components/form-builder-tab', () => ({
  FormBuilderTab: () => <div data-testid="form-builder" />,
}));
vi.mock('../components/form-flow-tab', () => ({
  FormFlowTab: () => <div data-testid="form-flow" />,
}));
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  const kit = await import('./builders-kit');
  return {
    ...actual,
    apiFetch: vi.fn(kit.fakeApiFetch),
    apiFetchText: vi.fn(async () => ''),
    apiFetchBlob: vi.fn(async () => new Blob()),
  };
});

afterEach(() => {
  writes.length = 0;
});

/** React's `_r_N_` ids renamed in order of first appearance. */
function maskIds(html: string): string {
  const seen = new Map<string, string>();
  return html.replace(/_r_[0-9a-z]+_/g, (id) => {
    if (!seen.has(id)) seen.set(id, `_r_id${seen.size}_`);
    return seen.get(id)!;
  });
}

async function snapOff(
  path: string,
  ui: ReactElement,
  ready: (root: HTMLElement) => boolean,
  params: Record<string, string> = {},
) {
  nav.path = path;
  nav.params = params;
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Look fx={false}>{ui}</Look>);
  });
  await waitFor(() => expect(ready(utils.container)).toBe(true));
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  const html = maskIds(parityHtml(utils.container));
  utils.unmount();
  return html;
}

const hasText = (text: string) => (root: HTMLElement) => root.textContent?.includes(text) ?? false;

describe('workflows and forms switch-off parity', () => {
  it('workflows list', async () => {
    expect(await snapOff('/workflows', <WorkflowsPage />, hasText('Reply to new chats'))).toMatchSnapshot();
  });

  it('forms list', async () => {
    expect(await snapOff('/forms', <FormsPage />, hasText('Site visit'))).toMatchSnapshot();
  });

  it('workflow record, read', async () => {
    expect(
      await snapOff('/workflows/w-1', <WorkflowFormView workflowId="w-1" initialEditing={false} />, hasText('Reply to new chats')),
    ).toMatchSnapshot();
  });

  it('workflow record, editing', async () => {
    expect(
      await snapOff('/workflows/w-1', <WorkflowFormView workflowId="w-1" initialEditing />, hasText('Reply to new chats')),
    ).toMatchSnapshot();
  });

  it('new workflow', async () => {
    expect(await snapOff('/workflows/new', <WorkflowFormView initialEditing />, hasText('New workflow'))).toMatchSnapshot();
  });

  it('form record, read', async () => {
    expect(await snapOff('/forms/f-1', <FormDetailView formId="f-1" initialEditing={false} />, hasText('Site visit'))).toMatchSnapshot();
  });

  it('form record, editing', async () => {
    expect(await snapOff('/forms/f-1', <FormDetailView formId="f-1" initialEditing />, hasText('Site visit'))).toMatchSnapshot();
  });

  it('new form', async () => {
    expect(await snapOff('/forms/new', <FormDetailView initialEditing />, hasText('New form'))).toMatchSnapshot();
  });

  it('fill page', async () => {
    expect(await snapOff('/forms/f-1/fill', <FormFillPage />, hasText('Full name'), { id: 'f-1' })).toMatchSnapshot();
  });

  it('submission', async () => {
    expect(
      await snapOff('/forms/f-1/submissions/s-1', <FormSubmissionPage />, hasText('Raw answers'), { id: 'f-1', submissionId: 's-1' }),
    ).toMatchSnapshot();
  });
});
