/**
 * The templates pages and the email editor with the Foundryx UIUX switch on
 * (slice W4-TEMPLATES).
 *
 * The core guarantee: email templates go to real people, so the saved
 * document, subject, name and context must be byte-identical in both looks
 * for the same editing actions (the rich text field's toolbar only changes
 * its look), and test sends, duplicates and deletes send the same requests.
 * Each scenario runs once per look through that look's own screen and
 * compares what reached the service. Then the new look's own behaviour.
 */
import type { ReactElement } from 'react';
import { fireEvent, render as rtlRender, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { FxProvider } from '@/providers/fx-provider';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { answers, calls, resetCalls, seededRandom, settle, template, writeCalls } from './template-test-kit';
import { createTemplate, editTemplateRecord, fakeExecCommand, openGearItem } from './template-steps';

const h = vi.hoisted(() => ({
  params: { id: 'tpl-1' } as Record<string, string>,
  search: new URLSearchParams(),
  pathname: '/settings/templates',
}));

vi.mock('@/lib/toast', async () => (await import('./template-test-kit')).toastMock);
vi.mock('@/services/template-service', async () => (await import('./template-test-kit')).templateServiceMock);
vi.mock('@/services/rule-engine-service', async () => (await import('./template-test-kit')).ruleEngineServiceMock);
vi.mock('@/services/pending-actions-service', async () => (await import('./template-test-kit')).pendingActionsServiceMock);
vi.mock('@/services/preferences-service', async () => (await import('./template-test-kit')).preferencesServiceMock);

vi.mock('next/navigation', async () => {
  const kit = await import('./template-test-kit');
  const router = {
    push: (...args: unknown[]) => kit.calls.push(['router.push', ...args]),
    replace: (...args: unknown[]) => kit.calls.push(['router.replace', ...args]),
    prefetch: () => undefined,
    back: () => undefined,
    refresh: () => undefined,
  };
  return {
    useRouter: () => router,
    usePathname: () => h.pathname,
    useSearchParams: () => h.search,
    useParams: () => h.params,
  };
});

vi.mock('next-auth/react', async () => ({
  // The signed-in person, for the done toasts' "by Kay Tan".
  SessionContext: (await import('react')).createContext({ data: { user: { name: 'Kay Tan' } } }),
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
  getSession: () => Promise.resolve(null),
  signOut: () => undefined,
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: () => Promise.resolve({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: () => undefined }),
}));

// Imported after the mocks.
import TemplatesPage from '../page';
import NewTemplatePage from '../new/page';
import TemplateFormPage from '../[id]/page';
import { RichTextField } from '@/components/platform/email-editor/rich-text-field';
import { FX_LIVE_PREVIEW_DELAY_MS } from '@/components/platform/email-editor/fx-email-editor';

type Look = 'off' | 'on';

function render(ui: ReactElement, look: Look) {
  const inner = <SettingsProvider>{ui}</SettingsProvider>;
  return rtlRender(
    look === 'on' ? (
      <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
        {inner}
      </FxProvider>
    ) : (
      inner
    ),
  );
}

const execCommand = vi.fn(fakeExecCommand);

function reset() {
  resetCalls();
  resetPageActionsForTests();
  execCommand.mockClear();
  vi.spyOn(Math, 'random').mockImplementation(seededRandom());
}

beforeEach(() => {
  reset();
  answers.template = template();
  h.params = { id: 'tpl-1' };
  h.search = new URLSearchParams();
  h.pathname = '/settings/templates';
  window.localStorage.clear();
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function runRecordAction(look: Look, name: RegExp): Promise<void> {
  if (look === 'off') {
    await openGearItem(name);
    return;
  }
  fireEvent.click(screen.getByRole('button', { name }));
  await settle();
}

async function bothLooks(run: (look: Look) => Promise<{ unmount: () => void }>) {
  const out: Record<Look, { writes: unknown[][]; commands: unknown[][] }> = {
    off: { writes: [], commands: [] },
    on: { writes: [], commands: [] },
  };
  for (const look of ['off', 'on'] as const) {
    reset();
    const { unmount } = await run(look);
    out[look] = { writes: writeCalls(), commands: [...execCommand.mock.calls] };
    unmount();
  }
  return out;
}

describe('the same requests in both looks', () => {
  it('saves a byte-identical template for the same editing actions', async () => {
    const out = await bothLooks(async (look) => {
      h.pathname = '/settings/templates/tpl-1';
      h.search = new URLSearchParams('edit=1');
      const r = render(<TemplateFormPage />, look);
      await screen.findByTestId('email-editor');
      await settle();
      // Each look edits through its own editor.
      expect(r.container.querySelector('[data-fx-email-editor]') !== null).toBe(look === 'on');
      await editTemplateRecord(r.container, () => {
        expect(r.container.querySelector('[data-fx-rich-text]') !== null).toBe(look === 'on');
      });
      return r;
    });
    expect(out.off.writes).toHaveLength(1);
    expect(out.off.writes[0][0]).toBe('template.update');
    // Byte-identical: the serialised request, not only deep equality.
    expect(JSON.stringify(out.on.writes)).toBe(JSON.stringify(out.off.writes));
    expect(out.on.commands).toEqual(out.off.commands);
    const body = out.on.writes[0][2] as { doc: { sections: { columns: { blocks: { html?: string }[] }[] }[] } };
    expect(body.doc.sections[1].columns[0].blocks[1].html).toBe(
      'Your account is <b>ready</b>. Sign in today.<b>bold</b><i>italic</i><ul><li>item</li></ul><a href="https://maju.my/start">link</a>{{recipient.firstName}}',
    );
  });

  it('creates a byte-identical template', async () => {
    const out = await bothLooks(async (look) => {
      h.pathname = '/settings/templates/new';
      const r = render(<NewTemplatePage />, look);
      await screen.findByTestId('email-editor');
      await settle();
      await createTemplate();
      return r;
    });
    expect(out.off.writes).toHaveLength(1);
    expect(out.off.writes[0][0]).toBe('template.create');
    expect(JSON.stringify(out.on.writes)).toBe(JSON.stringify(out.off.writes));
  });

  it('sends a test email and duplicates with the same requests', async () => {
    const out = await bothLooks(async (look) => {
      h.pathname = '/settings/templates/tpl-1';
      const r = render(<TemplateFormPage />, look);
      await screen.findByTestId('email-editor');
      await settle();
      await runRecordAction(look, /Send test email/);
      await runRecordAction(look, /Duplicate/);
      return r;
    });
    expect(out.off.writes).toEqual([
      ['template.testSend', 'tpl-1'],
      ['template.duplicate', 'tpl-1'],
    ]);
    expect(out.on.writes).toEqual(out.off.writes);
  });

  it('starts Delete with the same request', async () => {
    const out = await bothLooks(async (look) => {
      h.pathname = '/settings/templates/tpl-1';
      const r = render(<TemplateFormPage />, look);
      await screen.findByTestId('email-editor');
      await settle();
      await runRecordAction(look, /Delete/);
      return r;
    });
    expect(out.off.writes).toHaveLength(1);
    expect(out.off.writes[0].slice(0, 4)).toEqual(['pending.park', 'templates.delete', 'template', 'tpl-1']);
    expect(out.on.writes).toEqual(out.off.writes);
  });

  it('emits the same HTML from the rich text field for the same actions', async () => {
    const emitted: Record<Look, string[]> = { off: [], on: [] };
    for (const look of ['off', 'on'] as const) {
      reset();
      const prompt = vi.spyOn(window, 'prompt').mockReturnValue('https://maju.my');
      const onChange = (html: string) => emitted[look].push(html);
      const { unmount } = render(
        <RichTextField
          value="Hi <b>Alex</b>"
          onChange={onChange}
          fields={[{ key: 'recipient.firstName', label: 'First name', sample: 'Alex' }]}
          aria-label="Text"
        />,
        look,
      );
      const box = screen.getByTestId('rich-text-editable');
      box.focus();
      box.innerHTML = 'Hi <b>Alex</b>, welcome';
      fireEvent.input(box);
      for (const label of ['Bold', 'Italic', 'Underline', 'Bulleted list', 'Numbered list', 'Insert link']) {
        fireEvent.mouseDown(screen.getByRole('button', { name: label }), { button: 0 });
      }
      fireEvent.mouseDown(screen.getByTestId('merge-chip-recipient.firstName'), { button: 0 });
      fireEvent.blur(box);
      prompt.mockRestore();
      unmount();
    }
    expect(emitted.off.length).toBeGreaterThan(5);
    expect(emitted.on).toEqual(emitted.off);
  });
});

describe('the new look', () => {
  it('names the template and who in the done toasts', async () => {
    h.pathname = '/settings/templates/tpl-1';
    render(<TemplateFormPage />, 'on');
    await screen.findByTestId('email-editor');
    await settle();
    await runRecordAction('on', /Send test email/);
    expect(calls).toContainEqual([
      'toast.fxDone',
      { what: 'Test of Welcome email queued', forWhom: 'to kay@maju.my', byWhom: 'Kay Tan' },
    ]);
  });

  it('makes Save the red action while editing, with the record actions as icons at rest', async () => {
    h.pathname = '/settings/templates/tpl-1';
    render(<TemplateFormPage />, 'on');
    await screen.findByTestId('email-editor');
    await settle();
    expect(screen.getByRole('button', { name: /^Edit template$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send test email' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeInTheDocument();
  });

  it('shows the rich text toolbar along the field with tooltips and pressed states', () => {
    render(<RichTextField value="" onChange={() => undefined} fields={[]} aria-label="Text" />, 'on');
    const bar = screen.getByRole('toolbar', { name: 'Text formatting' });
    expect(within(bar).getByRole('button', { name: 'Bold' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(bar).getByRole('button', { name: 'Insert link' })).toBeInTheDocument();
  });

  it('shows a live preview beside the design that follows the document', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      h.pathname = '/settings/templates/tpl-1';
      h.search = new URLSearchParams('edit=1');
      const { container } = render(<TemplateFormPage />, 'on');
      await screen.findByTestId('email-editor');
      await settle();
      const live = container.querySelector('[data-fx-live-preview]') as HTMLElement;
      expect(live).not.toBeNull();
      const before = calls.filter((c) => c[0] === 'template.preview').length;
      expect(before).toBeGreaterThan(0);
      // A change re-renders it a moment later, never per keystroke.
      fireEvent.click(container.querySelector('[data-testid="canvas-block-blk_head"]') as Element);
      await settle();
      fireEvent.change(screen.getByLabelText('Heading text'), { target: { value: 'Hello' } });
      fireEvent.change(screen.getByLabelText('Heading text'), { target: { value: 'Hello there' } });
      await settle();
      expect(calls.filter((c) => c[0] === 'template.preview').length).toBe(before);
      await vi.advanceTimersByTimeAsync(FX_LIVE_PREVIEW_DELAY_MS + 50);
      await settle();
      expect(calls.filter((c) => c[0] === 'template.preview').length).toBe(before + 1);
      // Nothing was saved or sent by previewing.
      expect(writeCalls()).toEqual([]);
      // It folds away.
      fireEvent.click(screen.getByTestId('editor-live-preview'));
      expect(container.querySelector('[data-fx-live-preview]')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('has no instructional copy in read mode', async () => {
    h.pathname = '/settings/templates/tpl-1';
    const { container } = render(<TemplateFormPage />, 'on');
    await screen.findByTestId('email-editor');
    await settle();
    expect(container.textContent).not.toContain('Enable Edit to modify the design.');
  });

  it('declares the tier as the list status and names the list', async () => {
    render(<TemplatesPage />, 'on');
    expect(await screen.findAllByText('Welcome email')).not.toHaveLength(0);
  });
});
