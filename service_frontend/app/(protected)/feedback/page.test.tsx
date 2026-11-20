/**
 * AC-15-10 - the operator ideas page carries no description (the drag-grip copy
 * is gone with the manual reorder). Rendered with RTL, IdeasView stubbed.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import IdeasPage from './page';

vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/platform/page-header', () => ({
  PageHeader: ({ description }: { description?: string }) => (
    <header data-testid="page-header">{description}</header>
  ),
}));
vi.mock('./ideas-view', () => ({ IdeasView: () => <div data-testid="ideas-view" /> }));

describe('IdeasPage - no description (AC-15-10)', () => {
  it('renders the view without the drag-to-reprioritise copy', () => {
    render(<IdeasPage />);
    expect(screen.getByTestId('page-header')).toBeEmptyDOMElement();
    expect(screen.getByTestId('ideas-view')).toBeInTheDocument();
    expect(screen.queryByText(/drag the grip/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/raw idea repository/i)).not.toBeInTheDocument();
  });
});
