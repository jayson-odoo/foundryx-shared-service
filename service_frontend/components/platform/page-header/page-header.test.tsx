import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const svc = { getTerminology: vi.fn(), getCatalog: vi.fn(), setTerm: vi.fn(), resetTerm: vi.fn() };
vi.mock('@/services/terminology-service', () => ({
  get terminologyService() {
    return svc;
  },
}));

// AC-10 fix round 2 (commit 4961b493 added the `guardNav`-driven dirty
// guard on crumb links, which now calls `useRouter()` - the mock must
// return it or every render throws "No useRouter export".
const { usePathname, useRouter, push } = vi.hoisted(() => ({
  usePathname: vi.fn(() => '/user-management/users'),
  push: vi.fn(),
  useRouter: vi.fn(),
}));
vi.mock('next/navigation', () => ({
  usePathname,
  useRouter,
}));

import { PageHeader } from './page-header';

beforeEach(() => {
  vi.clearAllMocks();
  svc.getTerminology.mockResolvedValue({});
  usePathname.mockReturnValue('/user-management/users');
  useRouter.mockReturnValue({ push, back: vi.fn() });
});

describe('PageHeader (AC-DLA-27)', () => {
  it('auto-resolves the title from the current sidebar entry when none is passed', () => {
    render(<PageHeader />);
    expect(screen.getByRole('heading', { level: 1, name: 'Users' })).toBeInTheDocument();
  });

  it('renders an explicit title over the menu-derived one', () => {
    render(<PageHeader title="Admin User" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Admin User' })).toBeInTheDocument();
  });

  it('derives the breadcrumb trail from the sidebar with a Dashboard root', () => {
    render(<PageHeader />);
    const nav = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(nav).toHaveTextContent('Dashboard');
    expect(nav).toHaveTextContent('User Management');
    expect(nav).toHaveTextContent('Users');
  });

  it('marks only the LAST crumb aria-current=page', () => {
    render(<PageHeader />);
    const current = screen.getAllByText((_, el) => el?.getAttribute('aria-current') === 'page');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent('Users');
  });

  it('the root crumb reads "Dashboard"', () => {
    render(<PageHeader />);
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/');
  });

  it('renders an explicit crumbs override instead of the sidebar-derived trail', () => {
    render(<PageHeader title="Custom" crumbs={[{ label: 'Somewhere', href: '/somewhere' }, { label: 'Custom' }]} />);
    const nav = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(nav).toHaveTextContent('Dashboard');
    expect(nav).toHaveTextContent('Somewhere');
    expect(nav).toHaveTextContent('Custom');
    expect(screen.queryByText('Users')).not.toBeInTheDocument();
  });

  it('renders the actions slot', () => {
    render(<PageHeader title="Users" actions={<button>Create user</button>} />);
    expect(screen.getByRole('button', { name: 'Create user' })).toBeInTheDocument();
  });

  it('renders an eyebrow and a description when given', () => {
    render(<PageHeader title="Users" eyebrow="Team" description="Manage users, their roles and access." />);
    expect(screen.getByText('Team')).toBeInTheDocument();
    expect(screen.getByText('Manage users, their roles and access.')).toBeInTheDocument();
  });

  it('routes a crumb-link click through `guardNav` when supplied, but navigates it directly (no guard) when omitted (AC-10-16)', () => {
    const guardNav = vi.fn();
    const crumbs = [{ label: 'Somewhere', href: '/somewhere' }, { label: 'Custom' }];

    const { unmount } = render(<PageHeader title="Custom" crumbs={crumbs} guardNav={guardNav} />);
    fireEvent.click(screen.getByRole('link', { name: 'Somewhere' }));
    expect(guardNav).toHaveBeenCalledTimes(1);
    expect(guardNav).toHaveBeenCalledWith(expect.any(Function));
    unmount();

    guardNav.mockClear();
    push.mockClear();
    render(<PageHeader title="Custom" crumbs={crumbs} />);
    fireEvent.click(screen.getByRole('link', { name: 'Somewhere' }));
    expect(guardNav).not.toHaveBeenCalled();
  });

  it('a modifier or middle click on a guarded crumb link bypasses `guardNav` (open-in-new-tab stays default)', () => {
    const guardNav = vi.fn();
    const crumbs = [{ label: 'Somewhere', href: '/somewhere' }, { label: 'Custom' }];
    render(<PageHeader title="Custom" crumbs={crumbs} guardNav={guardNav} />);
    const link = screen.getByRole('link', { name: 'Somewhere' });

    fireEvent.click(link, { metaKey: true });
    fireEvent.click(link, { ctrlKey: true });
    fireEvent.click(link, { shiftKey: true });
    fireEvent.click(link, { altKey: true });
    fireEvent.click(link, { button: 1 });

    expect(guardNav).not.toHaveBeenCalled();
  });
});
