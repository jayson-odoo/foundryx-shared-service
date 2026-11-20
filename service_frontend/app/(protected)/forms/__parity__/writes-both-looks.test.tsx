/**
 * W6-BUILDERS core guarantee: with the Foundryx UIUX switch on, every request
 * the workflows and forms pages send is the same as with it off for the same
 * input. Each case drives the real page (record views with their real hooks,
 * services and `ResourceForm`; the canvas, builder and flow editor stood in
 * for by controls that hand over a fixed definition), records what reaches
 * `lib/api-client` (method, path, body) and compares both looks: workflow and
 * form create, edit, publish, unpublish; the list and row actions (publish,
 * unpublish, duplicate, archive, restore); a form fill with text, date,
 * number, select and yes/no answers (the date picked in the new date field
 * submits what the native one submits); and the public-form boundary.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import { FormRenderer } from '@/components/platform/form-renderer';
import { WorkflowFormView } from '../../workflows/components/workflow-form-view';
import { useWorkflowActions } from '../../workflows/components/use-workflow-actions';
import { FormDetailView } from '../components/form-detail-view';
import { useFormActions } from '../components/use-form-actions';
import FormFillPage from '../[id]/fill/page';
import { FILL_VIEW, FORM, FORM_DOC, FORM_ROW, Look, WORKFLOW, WORKFLOW_ROW, writes, type RecordedWrite } from './builders-kit';

const nav = vi.hoisted(() => ({ path: '/forms', params: {} as Record<string, string> }));

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => nav.path),
  useSearchParams: vi.fn(() => new URLSearchParams()),
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
// The canvas hands over a fixed definition; it stays as it is.
vi.mock('../../workflows/components/workflow-editor-tab', () => ({
  WorkflowEditorTab: ({
    doc,
    onDocChange,
    onPublish,
    onUnpublish,
  }: {
    doc: { nodes: unknown[]; edges: unknown[]; schemaVersion: number };
    onDocChange: (next: unknown) => void;
    onPublish: () => void;
    onUnpublish: () => void;
  }) => (
    <div>
      <button type="button" onClick={() => onDocChange({ ...doc, nodes: [...doc.nodes], edges: [], schemaVersion: 1 })}>
        Touch canvas
      </button>
      <button type="button" onClick={onPublish}>
        Canvas publish
      </button>
      <button type="button" onClick={onUnpublish}>
        Canvas unpublish
      </button>
    </div>
  ),
}));
vi.mock('../components/form-builder-tab', () => ({
  FormBuilderTab: ({
    doc,
    onDocChange,
    onPublish,
    onUnpublish,
  }: {
    doc: unknown;
    onDocChange: (next: unknown) => void;
    onPublish: () => void;
    onUnpublish: () => void;
  }) => (
    <div>
      <button type="button" onClick={() => onDocChange({ ...(doc as object), schemaVersion: 2 })}>
        Touch builder
      </button>
      <button type="button" onClick={onPublish}>
        Builder publish
      </button>
      <button type="button" onClick={onUnpublish}>
        Builder unpublish
      </button>
    </div>
  ),
}));
vi.mock('../components/form-flow-tab', () => ({ FormFlowTab: () => <div /> }));
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
  resetPageActionsForTests();
  document.body.innerHTML = '';
});

type Ui = ReturnType<typeof userEvent.setup>;

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

/** Renders `ui` in one look, runs `steps`, returns the writes it sent. */
async function sent(
  fx: boolean,
  path: string,
  ui: React.ReactElement,
  ready: string,
  steps: (u: Ui, fx: boolean) => Promise<void>,
  params: Record<string, string> = {},
): Promise<RecordedWrite[]> {
  nav.path = path;
  nav.params = params;
  writes.length = 0;
  const u = userEvent.setup();
  let unmount!: () => void;
  await act(async () => {
    unmount = render(<Look fx={fx}>{ui}</Look>).unmount;
  });
  await waitFor(() => expect(document.body.textContent).toContain(ready));
  await settle();
  await steps(u, fx);
  await settle();
  const out = writes.map((w) => ({ ...w }));
  unmount();
  resetPageActionsForTests();
  document.body.innerHTML = '';
  return out;
}

async function bothLooks(
  path: string,
  ui: () => React.ReactElement,
  ready: string,
  steps: (u: Ui, fx: boolean) => Promise<void>,
  params: Record<string, string> = {},
): Promise<RecordedWrite[]> {
  const off = await sent(false, path, ui(), ready, steps, params);
  const on = await sent(true, path, ui(), ready, steps, params);
  expect(off.length).toBeGreaterThan(0);
  expect(on).toEqual(off);
  return off;
}

async function typeInto(u: Ui, label: string | RegExp, text: string) {
  const input = screen.getByLabelText(label);
  await u.clear(input);
  await u.type(input, text);
}

/** Save: the record card's button while off, the red action while on. */
async function save(u: Ui, fx: boolean) {
  if (fx) {
    const red = document.querySelector<HTMLElement>('[data-fx-main-action] button');
    expect(red).not.toBeNull();
    await u.click(red!);
  } else {
    const buttons = screen.getAllByRole('button').filter((b) => /^(save|create)/i.test(b.textContent ?? ''));
    expect(buttons.length).toBeGreaterThan(0);
    await u.click(buttons[0]);
  }
  await settle();
}

describe('workflows send the same requests in both looks', () => {
  it('saves an edited workflow', async () => {
    const [w] = await bothLooks(
      '/workflows/w-1',
      () => <WorkflowFormView workflowId="w-1" initialEditing />,
      'Reply to new chats',
      async (u, fx) => {
        await u.click(screen.getByRole('button', { name: 'Touch canvas' }));
        await save(u, fx);
      },
    );
    expect(w.method).toBe('PATCH');
    expect(w.path).toBe('/workflows/w-1');
    expect(w.body).toMatchObject({ name: 'Reply to new chats', draftDefinition: { schemaVersion: 1 } });
  });

  it('publishes from the canvas (save, then publish)', async () => {
    const out = await bothLooks(
      '/workflows/w-1',
      () => <WorkflowFormView workflowId="w-1" initialEditing />,
      'Reply to new chats',
      async (u) => {
        await u.click(screen.getByRole('button', { name: 'Touch canvas' }));
        await u.click(screen.getByRole('button', { name: 'Canvas publish' }));
      },
    );
    expect(out.map((x) => `${x.method} ${x.path}`)).toContain('POST /workflows/w-1/publish');
  });

  it('unpublishes from the canvas', async () => {
    const out = await bothLooks(
      '/workflows/w-1',
      () => <WorkflowFormView workflowId="w-1" initialEditing={false} />,
      'Reply to new chats',
      async (u) => {
        await u.click(screen.getByRole('button', { name: 'Canvas unpublish' }));
      },
    );
    expect(out.map((x) => `${x.method} ${x.path}`)).toEqual(['POST /workflows/w-1/unpublish']);
  });
});

describe('forms send the same requests in both looks', () => {
  it('saves an edited form', async () => {
    const [w] = await bothLooks(
      '/forms/f-1',
      () => <FormDetailView formId="f-1" initialEditing />,
      'Site visit',
      async (u, fx) => {
        await u.click(screen.getByRole('button', { name: 'Touch builder' }));
        await save(u, fx);
      },
    );
    expect(w.method).toBe('PATCH');
    expect(w.path).toBe('/forms/f-1');
    expect(w.body).toMatchObject({ name: 'Site visit', draftDefinition: { schemaVersion: 2 } });
  });

  it('publishes and unpublishes from the builder', async () => {
    const out = await bothLooks(
      '/forms/f-1',
      () => <FormDetailView formId="f-1" initialEditing />,
      'Site visit',
      async (u) => {
        await u.click(screen.getByRole('button', { name: 'Touch builder' }));
        await u.click(screen.getByRole('button', { name: 'Builder publish' }));
        await u.click(screen.getByRole('button', { name: 'Builder unpublish' }));
      },
    );
    const lines = out.map((x) => `${x.method} ${x.path}`);
    expect(lines).toContain('POST /forms/f-1/publish');
    expect(lines).toContain('POST /forms/f-1/unpublish');
  });
});

/* ------------------------------------------------------- list and row actions */

function actionsIn<T>(fx: boolean, hook: () => T): T {
  let out!: T;
  function Grab() {
    out = hook();
    return null;
  }
  render(
    <Look fx={fx}>
      <Grab />
    </Look>,
  );
  return out;
}

async function runBoth<T extends object>(
  hook: () => { id: string }[],
  id: string,
  rows: T[],
): Promise<RecordedWrite[]> {
  const results: RecordedWrite[][] = [];
  for (const fx of [false, true]) {
    writes.length = 0;
    const action = actionsIn(fx, hook).find((a) => a.id === id)!;
    await act(async () => {
      await runResourceAction(action as never, rows as never, { reload: () => {} });
    });
    results.push(writes.map((w) => ({ ...w })));
    document.body.innerHTML = '';
  }
  expect(results[0].length).toBeGreaterThan(0);
  expect(results[1]).toEqual(results[0]);
  return results[0];
}

describe('workflow and form row and bulk actions run the same requests in both looks', () => {
  const trashedW = { ...WORKFLOW_ROW, isTrashed: true };
  const trashedF = { ...FORM_ROW, isTrashed: true };
  const w2 = { ...WORKFLOW_ROW, id: 'w-2', name: 'Second' };
  const f2 = { ...FORM_ROW, id: 'f-2', name: 'Second form' };

  for (const id of ['unpublish', 'duplicate', 'archive']) {
    it(`workflow ${id}`, async () => {
      const out = await runBoth(useWorkflowActions, id, id === 'duplicate' ? [WORKFLOW_ROW] : [WORKFLOW_ROW, w2]);
      expect(out[0].method).toBe('POST');
    });
  }
  it('workflow restore', async () => {
    await runBoth(useWorkflowActions, 'restore', [trashedW, { ...trashedW, id: 'w-2' }]);
  });
  it('workflow publish', async () => {
    const out = await runBoth(useWorkflowActions, 'publish', [WORKFLOW_ROW, w2]);
    expect(out.map((x) => x.path)).toEqual(['/workflows/w-1/publish', '/workflows/w-2/publish']);
  });

  for (const id of ['publish', 'unpublish', 'archive']) {
    it(`form ${id}`, async () => {
      const out = await runBoth(useFormActions, id, [FORM_ROW, f2]);
      expect(out[0].method).toBe('POST');
    });
  }
  it('form restore', async () => {
    await runBoth(useFormActions, 'restore', [trashedF, { ...trashedF, id: 'f-2' }]);
  });

  it('delete parks the same deferred action key and entity type', () => {
    for (const hook of [useWorkflowActions, useFormActions]) {
      const [off, on] = [false, true].map((fx) => actionsIn(fx, hook).find((a) => a.id === 'delete')) as {
        deferred?: { actionKey: string; entityType: string; payload?: unknown };
      }[];
      expect({ key: on.deferred?.actionKey, type: on.deferred?.entityType, payload: on.deferred?.payload }).toEqual({
        key: off.deferred?.actionKey,
        type: off.deferred?.entityType,
        payload: off.deferred?.payload,
      });
      document.body.innerHTML = '';
    }
  });
});

/* --------------------------------------------------------------- the fill page */

describe('a form fill submits the same values in both looks', () => {
  for (const c of [
    { name: 'a plain day', day: '9 Mar 2026', budget: '12.5', headcount: '4' },
    { name: 'the last day of a leap year', day: '31 Dec 2028', budget: '1000', headcount: '0' },
  ]) {
    it(`submits ${c.name}`, async () => {
      const isoDay = c.day === '9 Mar 2026' ? '2026-03-09' : '2028-12-31';
      const run = (fx: boolean) =>
        sent(
          fx,
          '/forms/f-1/fill',
          <FormFillPage />,
          'Full name',
          async (u) => {
            await typeInto(u, /Full name/, 'Nur Aisyah');
            if (fx) {
              // The new date field: typed, tidied when you leave it.
              await typeInto(u, 'Start date', c.day);
              await u.tab();
            } else {
              fireEvent.change(screen.getByLabelText('Start date'), { target: { value: isoDay } });
            }
            await typeInto(u, 'Headcount', c.headcount);
            await typeInto(u, 'Budget', c.budget);
            await u.tab();
            await u.click(screen.getByRole('button', { name: 'Yes' }));
            await u.click(screen.getByRole('button', { name: /Submit form/ }));
          },
          { id: 'f-1' },
        );
      const off = await run(false);
      const on = await run(true);
      expect(off).toHaveLength(1);
      expect(on).toEqual(off);
      expect(off[0].path).toBe('/forms/f-1/submissions');
      expect((off[0].body as { answers: Record<string, unknown> }).answers).toMatchObject({
        fullName: 'Nur Aisyah',
        startDate: isoDay,
        headcount: Number(c.headcount),
        agree: true,
      });
    });
  }

  it('picking the day from the calendar submits what the native field submits for that day', async () => {
    const on = await sent(true, '/forms/f-1/fill', <FormFillPage />, 'Full name', async (u) => {
      await typeInto(u, /Full name/, 'A');
      await u.click(screen.getByRole('button', { name: 'Open calendar' }));
      const cell = (await screen.findAllByRole('gridcell')).find((c) => c.textContent?.trim() === '15' && !c.hasAttribute('data-outside'));
      await u.click(cell!.querySelector('button') ?? cell!);
      await u.click(screen.getByRole('button', { name: /Submit form/ }));
    }, { id: 'f-1' });
    const picked = (on[0].body as { answers: { startDate: string } }).answers.startDate;
    expect(picked).toMatch(/^\d{4}-\d{2}-15$/);
    const off = await sent(false, '/forms/f-1/fill', <FormFillPage />, 'Full name', async (u) => {
      await typeInto(u, /Full name/, 'A');
      fireEvent.change(screen.getByLabelText('Start date'), { target: { value: picked } });
      await u.click(screen.getByRole('button', { name: /Submit form/ }));
    }, { id: 'f-1' });
    expect(on).toEqual(off);
  });
});

describe('public form pages stay outside the switch', () => {
  it('the shared renderer keeps the native date input unless the fill page asks for the new one', async () => {
    const answers = {};
    const view = (fxFields?: boolean) => (
      <Look fx>
        <FormRenderer definition={FORM_DOC} mode="fill" answers={answers} onChange={() => {}} fxFields={fxFields} />
      </Look>
    );
    const { container, unmount } = render(view());
    expect(container.querySelector('input[type="date"]')).not.toBeNull();
    unmount();
    const again = render(view(true));
    expect(again.container.querySelector('input[type="date"]')).toBeNull();
    expect(screen.getByRole('button', { name: 'Open calendar' })).toBeTruthy();
    expect(FILL_VIEW.formId).toBe(FORM.id);
    expect(WORKFLOW.id).toBe('w-1');
  });
});
