import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PublicIdeaStatusPage from './page';

/**
 * S5 public idea status page (AC-1601, AC-1106, AC-1115), grown into a full
 * page by issue #90 (AC-90-110/111/112). TEST-FIRST (PRINCIPLES.md). Mocks
 * next/navigation's useParams, the data hook, and the branding hook (the
 * header/footer BrandMark) so this exercises only the page's render logic,
 * per the sibling `public-form-service`/`use-public-share` test style.
 */

const useParams = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useParams: () => useParams() }));

const usePublicIdeaStatus = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-public-idea-status', () => ({
  usePublicIdeaStatus: (token: string) => usePublicIdeaStatus(token),
}));

const useTenantBranding = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => useTenantBranding(),
}));

const UNBRANDED = {
  isBranded: false,
  tenantName: null,
  appName: null,
  slogan: null,
  logoUrl: null,
  faviconUrl: null,
  illustrationUrl: null,
  tokens: null,
  version: 0,
};

const richView = {
  ideaNumber: 'IDEA-0182',
  title: 'Show promo price in red on price tags',
  status: 'New',
  statusColor: 'blue',
  productName: 'Sorento CRM',
  problem: 'Promo price is not visible in-store',
  proposedSolution: 'Print it in red on the price tag',
  impact: 'Fewer missed promotions at checkout',
  department: 'Merchandising',
  submitterFirstName: 'Jayson',
  submittedAt: '2026-07-20T10:00:00Z',
  upvotes: 7,
  nextStep: 'Your idea is in. The team will review it soon.',
  timeline: [
    { label: 'New', color: 'blue', state: 'done' },
    { label: 'Triaged', color: 'indigo', state: 'current' },
    { label: 'Linked to BR', color: 'violet', state: 'upcoming' },
    { label: 'Building', color: 'amber', state: 'upcoming' },
    { label: 'Delivered', color: 'green', state: 'upcoming' },
  ],
};

beforeEach(() => {
  useParams.mockReset();
  usePublicIdeaStatus.mockReset();
  useTenantBranding.mockReset();
  useParams.mockReturnValue({ token: 'tok_abc123def456' });
  useTenantBranding.mockReturnValue({ branding: UNBRANDED, isResolved: true });
});

describe('PublicIdeaStatusPage - AC-90-110 the full page contract', () => {
  it('renders the header product name, hero, votes, sections, next step and footer mark', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
    render(<PublicIdeaStatusPage />);

    // Header - product name (R1: the idea's core Product).
    expect(screen.getByText('Sorento CRM')).toBeInTheDocument();

    // Hero.
    expect(screen.getByText('IDEA-0182')).toBeInTheDocument();
    expect(screen.getByText('Show promo price in red on price tags')).toBeInTheDocument();
    expect(screen.getByText('New')).toBeInTheDocument();
    expect(screen.getByText(/Jayson/)).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument(); // submittedAt rendered
    expect(screen.getByText(/7/)).toBeInTheDocument(); // upvotes

    // Detail sections - labelled per idea-form-fields.tsx (Problem statement /
    // Proposed solution / Impact / Department).
    expect(screen.getByText('Problem statement')).toBeInTheDocument();
    expect(screen.getByText('Promo price is not visible in-store')).toBeInTheDocument();
    expect(screen.getByText('Proposed solution')).toBeInTheDocument();
    expect(screen.getByText('Print it in red on the price tag')).toBeInTheDocument();
    expect(screen.getByText('Impact')).toBeInTheDocument();
    expect(screen.getByText('Fewer missed promotions at checkout')).toBeInTheDocument();
    expect(screen.getByText('Department')).toBeInTheDocument();
    expect(screen.getByText('Merchandising')).toBeInTheDocument();

    // "What happens next".
    expect(
      screen.getByText('Your idea is in. The team will review it soon.'),
    ).toBeInTheDocument();

    // Footer mark - unbranded host shows the Foundryx wordmark.
    expect(screen.getByAltText(/foundryx/i)).toBeInTheDocument();
  });

  // Supersedes (REWRITTEN, not deleted) the old AC-1601
  // "never renders any problem/solution/impact/department text" test - issue
  // #90 makes these fields part of the page; the empty-state contract now is
  // "always render the section, 'Not provided' when blank", never omission.
  it('renders "Not provided" for empty detail sections and omits the submitter line when there is no first name', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: {
        ...richView,
        problem: null,
        proposedSolution: null,
        impact: null,
        department: null,
        submitterFirstName: null,
      },
    });
    render(<PublicIdeaStatusPage />);
    expect(screen.getAllByText('Not provided').length).toBe(4);
    expect(screen.queryByText('Jayson')).not.toBeInTheDocument();
  });

  it('shows the tenant name (not the Foundryx mark) on a branded host', () => {
    useTenantBranding.mockReturnValue({
      branding: { ...UNBRANDED, isBranded: true, tenantName: 'Acme Co', logoUrl: null },
      isResolved: true,
    });
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
    render(<PublicIdeaStatusPage />);
    expect(screen.queryByAltText(/foundryx/i)).not.toBeInTheDocument();
    expect(screen.getAllByText('Acme Co').length).toBeGreaterThan(0);
  });
});

describe('PublicIdeaStatusPage - AC-90-111 the status timeline', () => {
  it('renders one entry per timeline step with its state, done/current/upcoming', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
    render(<PublicIdeaStatusPage />);
    for (const step of richView.timeline) {
      const el = screen.getByText(step.label);
      const item = el.closest('[data-state]');
      expect(item).not.toBeNull();
      expect(item).toHaveAttribute('data-state', step.state);
    }
  });

  it('renders the truthful short off-ramp timeline (New done, Rejected current)', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: {
        ...richView,
        status: 'Rejected',
        nextStep: 'This idea will not go ahead for now.',
        timeline: [
          { label: 'New', color: 'blue', state: 'done' },
          { label: 'Rejected', color: 'red', state: 'current' },
        ],
      },
    });
    render(<PublicIdeaStatusPage />);
    const newItem = screen.getByText('New').closest('[data-state]');
    const rejectedItem = screen.getByText('Rejected').closest('[data-state]');
    expect(newItem).toHaveAttribute('data-state', 'done');
    expect(rejectedItem).toHaveAttribute('data-state', 'current');
  });
});

describe('PublicIdeaStatusPage - not-found (regression, unchanged)', () => {
  it('renders the not-found state when the hook reports not found', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: true, view: null });
    render(<PublicIdeaStatusPage />);
    expect(screen.getByTestId('idea-status-notfound')).toBeInTheDocument();
  });

  it('shows "Idea <number>" as the heading when title is null', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: { ...richView, title: null },
    });
    render(<PublicIdeaStatusPage />);
    expect(screen.getByText('Idea IDEA-0182')).toBeInTheDocument();
  });
});
