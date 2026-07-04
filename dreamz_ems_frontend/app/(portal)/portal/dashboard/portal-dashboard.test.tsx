import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PortalSurface } from '@/services/portal-surface-service';
import { PortalDashboard } from './portal-dashboard';

// ── Surface service: drive composition from a controlled response. ──────────
const { listSurfaces } = vi.hoisted(() => ({ listSurfaces: vi.fn() }));
vi.mock('@/services/portal-surface-service', () => ({
  portalSurfaceService: { listSurfaces },
}));

// ── Portal filter: a controllable in-test store (the URL-backed provider). ──
const filterStore = vi.hoisted(() => ({
  activeContextKey: null as string | null,
  setActiveContextKey: vi.fn(),
}));
vi.mock('@/providers/portal-filter-provider', () => ({
  usePortalFilter: () => filterStore,
}));

vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => ({
    branding: { isBranded: false, tenantName: null, appName: null, logoUrl: null },
    isResolved: true,
  }),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { profile: { fullName: 'Ada Lovelace', email: 'ada@example.com' } },
    status: 'authenticated',
  }),
  signOut: vi.fn(),
}));

const SURFACES: PortalSurface[] = [
  {
    key: 'my_submissions',
    label: 'My Submissions',
    gatingPermission: 'my_submissions.read',
    module: 'ems',
    sortOrder: 10,
    description: 'Your submissions',
    contexts: [
      { scopeType: 'project', scopeId: 'proj-aaaaaaaa' },
      { scopeType: 'project', scopeId: 'proj-bbbbbbbb' },
    ],
  },
  {
    key: 'my_reviews',
    label: 'My Reviews',
    gatingPermission: 'my_reviews.read',
    module: 'ems',
    sortOrder: 20,
    description: 'Your reviews',
    contexts: [{ scopeType: 'project', scopeId: 'proj-aaaaaaaa' }],
  },
];

describe('Portal unified dashboard', () => {
  beforeEach(() => {
    listSurfaces.mockReset();
    filterStore.activeContextKey = null;
    filterStore.setActiveContextKey.mockReset();
  });

  // Section headings (the dashboard cards) are <h2> — distinct from the nav
  // buttons that share the surface label.
  const sectionHeading = (name: string) =>
    screen.queryByRole('heading', { level: 2, name });

  it('renders only the surfaces the backend returned (gating)', async () => {
    listSurfaces.mockResolvedValueOnce(SURFACES);
    render(<PortalDashboard />);

    await waitFor(() => expect(sectionHeading('My Submissions')).toBeInTheDocument());
    expect(sectionHeading('My Reviews')).toBeInTheDocument();
    // A surface NOT returned never renders.
    expect(sectionHeading('Decisions')).not.toBeInTheDocument();
    // Greets the signed-in Profile.
    expect(screen.getByText(/Ada Lovelace/)).toBeInTheDocument();
  });

  it('hides a section whose gating key the Profile lacks (empty set)', async () => {
    listSurfaces.mockResolvedValueOnce([SURFACES[0]]);
    render(<PortalDashboard />);

    await waitFor(() => expect(sectionHeading('My Submissions')).toBeInTheDocument());
    expect(sectionHeading('My Reviews')).not.toBeInTheDocument();
  });

  it('unfiltered: shows every context with the context per row', async () => {
    listSurfaces.mockResolvedValueOnce(SURFACES);
    render(<PortalDashboard />);

    await waitFor(() => expect(sectionHeading('My Submissions')).toBeInTheDocument());
    const card = document.querySelector(
      '[data-surface="my_submissions"]',
    ) as HTMLElement;
    // Both contexts listed (context per row). Label = "Event " + 8-char id.
    expect(card.textContent).toContain('Event proj-aaa');
    const rows = card.querySelectorAll('[data-context]');
    expect(rows.length).toBe(2);
  });

  it('the event filter narrows sections to one context', async () => {
    listSurfaces.mockResolvedValue(SURFACES);
    // Active filter = proj-bbbbbbbb (only My Submissions holds it).
    filterStore.activeContextKey = 'project:proj-bbbbbbbb';
    render(<PortalDashboard />);

    await waitFor(() => expect(sectionHeading('My Submissions')).toBeInTheDocument());
    // My Reviews has no proj-bbbbbbbb context → its section is filtered out.
    expect(sectionHeading('My Reviews')).not.toBeInTheDocument();

    const card = document.querySelector(
      '[data-surface="my_submissions"]',
    ) as HTMLElement;
    const rows = card.querySelectorAll('[data-context]');
    // Narrowed to just the one matching context.
    expect(rows.length).toBe(1);
    expect(rows[0].getAttribute('data-context')).toBe('project:proj-bbbbbbbb');
  });

  it('selecting an event in the filter pill propagates via setActiveContextKey', async () => {
    listSurfaces.mockResolvedValue(SURFACES);
    render(<PortalDashboard />);
    await waitFor(() => expect(sectionHeading('My Submissions')).toBeInTheDocument());

    // Open the filter pill (first combobox = the event filter) and pick an event.
    const pill = screen.getAllByRole('combobox', { name: /filter by event/i })[0];
    const user = userEvent.setup();
    await user.click(pill);
    const option = await screen.findByRole('option', { name: 'Event proj-aaa' });
    await user.click(option);

    expect(filterStore.setActiveContextKey).toHaveBeenCalledWith(
      'project:proj-aaaaaaaa',
    );
  });
});
