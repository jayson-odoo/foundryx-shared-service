/**
 * AI prompt detail (Meetings S4 plan §3.4, AC-S4-9/AC-S4-10).
 *
 * Version history + badges, "New version" appending a version in mock state
 * without touching prior ones, and "Publish" repointing the production
 * badge through a confirm dialog (never a bare `confirm()`).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  AiPromptDetail,
  AiPromptVersion,
  CreatePromptVersionInput,
  PublishPromptVersionInput,
} from '@/types/ai-prompt';

function version(overrides: Partial<AiPromptVersion> = {}): AiPromptVersion {
  return {
    id: 'v1',
    version: 1,
    template: 'Hello {{title}}',
    commitMessage: 'Initial version.',
    createdByName: 'Wei Ling',
    createdAt: '2026-08-20T09:00:00.000Z',
    labels: ['production'],
    ...overrides,
  };
}

let detail: AiPromptDetail;

function resetDetail() {
  detail = {
    name: 'meetings_minutes',
    variables: ['title', 'participants', 'language', 'transcript'],
    labels: { production: 1, staging: null },
    versions: [version()],
  };
}
resetDetail();

vi.mock('@/services/ai-prompts-service', () => ({
  aiPromptsService: {
    getPrompt: vi.fn(async (name: string) => (name === detail.name ? structuredClone(detail) : null)),
    createVersion: vi.fn(async (_name: string, input: CreatePromptVersionInput) => {
      const created: AiPromptVersion = {
        id: 'v2',
        version: 2,
        template: input.template,
        commitMessage: input.commitMessage,
        createdByName: 'You',
        createdAt: '2026-09-01T10:00:00.000Z',
        labels: [],
      };
      detail = { ...detail, versions: [created, ...detail.versions] };
      return structuredClone(created);
    }),
    publishVersion: vi.fn(async (_name: string, input: PublishPromptVersionInput) => {
      detail = {
        ...detail,
        labels: { ...detail.labels, [input.label]: detail.versions.find((v) => v.id === input.versionId)?.version ?? null },
        versions: detail.versions.map((v) => ({
          ...v,
          labels:
            v.id === input.versionId
              ? [...v.labels.filter((l) => l !== input.label), input.label]
              : v.labels.filter((l) => l !== input.label),
        })),
      };
      return structuredClone(detail);
    }),
  },
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: { user: { timezone: 'UTC' } } }),
}));

// `vi.mock` is hoisted above imports, so a static import is already mocked.
import { PromptDetailView } from './prompt-detail-view';

describe('AI prompt detail', () => {
  beforeEach(() => {
    resetDetail();
  });

  it('shows the version history with the production badge and the template body', async () => {
    render(<PromptDetailView name="meetings_minutes" />);

    expect(await screen.findByTestId('version-row-1')).toBeInTheDocument();
    expect(within(screen.getByTestId('version-row-1')).getByText('Production')).toBeInTheDocument();
    expect(screen.getByText('Hello {{title}}')).toBeInTheDocument();
  });

  it('"New version" edits the template well in place and appends a version without touching v1', async () => {
    const user = userEvent.setup();
    render(<PromptDetailView name="meetings_minutes" />);
    await screen.findByTestId('version-row-1');

    await user.click(screen.getByTestId('new-version-button'));
    const editor = screen.getByTestId('prompt-editor');
    // fireEvent, not user.type: userEvent's `{}` syntax is reserved for special
    // keys, so it would mangle the literal `{{title}}` template token.
    fireEvent.change(editor, { target: { value: 'Updated {{title}} body' } });
    await user.type(screen.getByTestId('commit-message'), 'Tighten wording');
    await user.click(screen.getByTestId('save-version'));

    await waitFor(() => expect(screen.getByTestId('version-row-2')).toBeInTheDocument());
    expect(screen.getByTestId('version-row-1')).toBeInTheDocument();
    expect(screen.getByText('Updated {{title}} body')).toBeInTheDocument();
  });

  it('shows an explicit empty state when there are no versions yet (P3 review S7 - a fresh DB)', async () => {
    detail.versions = [];
    detail.labels = { production: null, staging: null };
    render(<PromptDetailView name="meetings_minutes" />);

    expect(await screen.findByText('No versions yet.')).toBeInTheDocument();
    expect(screen.getByText('No template yet')).toBeInTheDocument();
    expect(screen.getByTestId('new-version-button')).toBeInTheDocument();
    // The bug this guards against: `Template · v${selected?.version}` with
    // no version renders the literal string "vundefined".
    expect(screen.queryByText(/vundefined/)).not.toBeInTheDocument();
  });

  it('Publish opens a confirm dialog and repoints the production badge on confirm', async () => {
    detail.versions = [
      version({ id: 'v1', version: 1, labels: ['production'] }),
      version({ id: 'v2', version: 2, commitMessage: 'v2', labels: [] }),
    ];
    const user = userEvent.setup();
    render(<PromptDetailView name="meetings_minutes" />);
    await screen.findByTestId('version-row-2');

    await user.click(screen.getByTestId('version-row-2'));
    await user.click(screen.getByTestId('publish-button'));

    expect(await screen.findByText(/Publish meetings_minutes v2 to production\?/)).toBeInTheDocument();
    await user.click(screen.getByTestId('confirm-publish'));

    await waitFor(() =>
      expect(within(screen.getByTestId('version-row-2')).getByText('Production')).toBeInTheDocument(),
    );
    expect(within(screen.getByTestId('version-row-1')).queryByText('Production')).not.toBeInTheDocument();
  });
});
