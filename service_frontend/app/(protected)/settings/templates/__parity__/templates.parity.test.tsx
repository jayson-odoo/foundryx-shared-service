/**
 * Switch-off parity for the templates pages and the email editor (Foundryx
 * UIUX, slice W4-TEMPLATES). Recorded on the code BEFORE the slice changed
 * anything, so a later change that alters what a user sees or what reaches
 * the backend with the switch off fails here. A change that needs one of these
 * snapshots updated is wrong by definition: fix the code, never the snapshot.
 *
 * Covers: the templates list, a template record (Design tab read and edit,
 * Settings tab, the rich text field, Send test email, Duplicate, Save), the
 * new template form (Create) and the email preview pane.
 */
import type { ReactElement } from 'react';
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { answers, calls, parityHtml, resetCalls, seededRandom, settle, template } from './template-test-kit';
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

vi.mock('next-auth/react', () => ({
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
import { PreviewPane } from '@/components/platform/email-editor';
import { RichTextField } from '@/components/platform/email-editor/rich-text-field';

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

const execCommand = vi.fn(fakeExecCommand);

beforeEach(() => {
  resetCalls();
  answers.template = template();
  h.params = { id: 'tpl-1' };
  h.search = new URLSearchParams();
  h.pathname = '/settings/templates';
  window.localStorage.clear();
  execCommand.mockClear();
  // jsdom has no editing commands; the toolbar's calls are recorded instead.
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });
  vi.spyOn(Math, 'random').mockImplementation(seededRandom());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('templates list (switch off)', () => {
  it('renders the list as today', async () => {
    const { container } = render(<TemplatesPage />);
    await screen.findByText('Welcome email');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('template record (switch off)', () => {
  beforeEach(() => {
    h.pathname = '/settings/templates/tpl-1';
  });

  it('renders the Design tab read-only and runs Send test email and Duplicate as today', async () => {
    const { container } = render(<TemplateFormPage />);
    await screen.findByTestId('email-editor');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('read');

    await openGearItem(/Send test email/);
    await openGearItem(/Duplicate/);
    expect(calls.filter((c) => c[0] !== 'template.preview')).toMatchSnapshot('calls');
  });

  it('edits the design and settings and saves the same document as today', async () => {
    h.search = new URLSearchParams('edit=1');
    const { container } = render(<TemplateFormPage />);
    await screen.findByTestId('email-editor');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('edit');

    await editTemplateRecord(container, (label) => expect(parityHtml(container)).toMatchSnapshot(label));
    expect(execCommand.mock.calls).toMatchSnapshot('editing commands');
    expect(calls.filter((c) => c[0] !== 'template.preview')).toMatchSnapshot('save calls');
  });

  it('shows the preview as today', async () => {
    const { container } = render(<TemplateFormPage />);
    await screen.findByTestId('email-editor');
    fireEvent.click(screen.getByTestId('editor-mode-preview'));
    await settle();
    expect(parityHtml(container.querySelector('[data-testid="email-editor"]') as Element)).toMatchSnapshot();
  });
});

describe('new template (switch off)', () => {
  it('renders the create form and creates as today', async () => {
    h.pathname = '/settings/templates/new';
    const { container } = render(<NewTemplatePage />);
    await screen.findByTestId('email-editor');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('form');

    await createTemplate();
    expect(calls.filter((c) => c[0] !== 'template.preview')).toMatchSnapshot('create calls');
  });
});

describe('email editor pieces (switch off)', () => {
  it('renders the rich text field as today', () => {
    const { container } = render(
      <RichTextField
        value="Hello <b>Alex</b>"
        onChange={() => undefined}
        fields={[{ key: 'recipient.firstName', label: 'First name', sample: 'Alex' }]}
        aria-label="Text"
      />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders the preview pane as today', async () => {
    const { container } = render(
      <PreviewPane render={() => Promise.resolve({ subject: 'Hi Alex', html: '<p>Hi</p>', text: 'Hi' })} />,
    );
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
