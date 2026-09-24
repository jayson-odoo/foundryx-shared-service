import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PublicIdeaStatusPage from './page';

/**
 * S5 public idea status page (AC-1601, AC-1106, AC-1115). TEST-FIRST
 * (PRINCIPLES.md): written before the page exists. Mocks next/navigation's
 * useParams + the hook so this exercises only the page's render logic, per
 * the sibling `public-form-service`/`use-public-share` test style.
 */

const useParams = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useParams: () => useParams() }));

const usePublicIdeaStatus = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-public-idea-status', () => ({
  usePublicIdeaStatus: (token: string) => usePublicIdeaStatus(token),
}));

beforeEach(() => {
  useParams.mockReset();
  usePublicIdeaStatus.mockReset();
  useParams.mockReturnValue({ token: 'tok_abc123def456' });
});

describe('PublicIdeaStatusPage', () => {
  it('renders the idea number, title and status pill with no auth', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: {
        ideaNumber: 'IDEA-0182',
        title: 'Show promo price in red on price tags',
        status: 'New',
      },
    });
    render(<PublicIdeaStatusPage />);
    expect(screen.getByText('IDEA-0182')).toBeInTheDocument();
    expect(screen.getByText('Show promo price in red on price tags')).toBeInTheDocument();
    expect(screen.getByText('New')).toBeInTheDocument();
  });

  it('renders the not-found state when the hook reports not found', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: true, view: null });
    render(<PublicIdeaStatusPage />);
    expect(screen.getByTestId('idea-status-notfound')).toBeInTheDocument();
  });

  it('never renders any problem/solution/impact/department text', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: {
        ideaNumber: 'IDEA-0182',
        title: 'Show promo price in red',
        status: 'New',
        // A conforming hook/view NEVER carries these (S5 lookup is
        // title/status/ideaNumber only) - present here only to prove the
        // page itself never renders them even if a bug leaked one through.
        problem: 'the price tag should show promo price in red - MUST NOT RENDER',
      },
    });
    render(<PublicIdeaStatusPage />);
    expect(
      screen.queryByText(/the price tag should show promo price in red - MUST NOT RENDER/i),
    ).not.toBeInTheDocument();
  });

  it('shows "Idea <number>" as the heading when title is null', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: { ideaNumber: 'IDEA-0007', title: null, status: 'New' },
    });
    render(<PublicIdeaStatusPage />);
    expect(screen.getByText('Idea IDEA-0007')).toBeInTheDocument();
  });
});
