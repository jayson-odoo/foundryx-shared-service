/**
 * Settings → AI prompts list page (Meetings S4 plan §3.4, AC-S4-10).
 *
 * Covers both the platform-admin gate (RequirePlatformPermission) and the
 * list rendering - a non-platform session must render NOTHING of the
 * registry, only the friendly "no access" page.
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AiPromptSummary } from '@/types/ai-prompt';

const session: { value: { isPlatformTenant: boolean } } = { value: { isPlatformTenant: true } };
const permissions = new Set<string>(['ai_prompts.manage']);

const prompts: AiPromptSummary[] = [
  {
    name: 'meetings_minutes',
    productionVersion: 2,
    latestVersion: 2,
    updatedAt: '2026-08-30T03:12:00.000Z',
    updatedByName: 'Wei Ling',
  },
];

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    data: { user: { isPlatformTenant: session.value.isPlatformTenant, timezone: 'UTC' } },
  }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => permissions.has(key), ready: true, permissions }),
}));

vi.mock('@/services/ai-prompts-service', () => ({
  aiPromptsService: {
    listPrompts: vi.fn(async () => prompts),
  },
}));

// SettingsProvider-free: Toolbar/Container read layout tokens; stub the partials
// (precedent: app/(protected)/ideation/board/page.test.tsx).
vi.mock('@/partials/common/toolbar', () => ({
  Toolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ToolbarHeading: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ToolbarDescription: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ToolbarPageTitle: ({ text }: { text?: string }) => <h1>{text ?? 'AI prompts'}</h1>,
}));
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// `vi.mock` is hoisted above imports, so a static import is already mocked.
import AiPromptsPage from './page';

describe('Settings → AI prompts (list)', () => {
  beforeEach(() => {
    session.value = { isPlatformTenant: true };
  });

  it('AC-S4-10: a platform admin sees the registry - name + production version + updated', async () => {
    render(<AiPromptsPage />);

    expect(await screen.findByTestId('prompt-row-meetings_minutes')).toBeInTheDocument();
    expect(screen.getByText('meetings_minutes')).toBeInTheDocument();
    expect(screen.getByText('v2')).toBeInTheDocument();
  });

  it('AC-S4-10: a non-platform-tenant session renders no registry content', async () => {
    session.value = { isPlatformTenant: false };
    render(<AiPromptsPage />);

    expect(screen.queryByTestId('prompt-row-meetings_minutes')).not.toBeInTheDocument();
    expect(screen.queryByText('meetings_minutes')).not.toBeInTheDocument();
    expect(await screen.findByText(/don.?t have access/i)).toBeInTheDocument();
  });
});
