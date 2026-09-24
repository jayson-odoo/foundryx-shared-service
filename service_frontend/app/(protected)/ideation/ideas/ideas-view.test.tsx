/**
 * issue #1179 - the "Show test ideas" toggle is operator-only: the chrome-less
 * embed iframe (WS-C1) must never offer it (there is no debugging surface for
 * an external host consumer).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { IdeasView } from './ideas-view';

vi.mock('@/hooks/use-ideas', () => ({
  useIdeas: () => ({
    ideas: [],
    products: [],
    loading: false,
    error: null,
    includeTest: false,
    setIncludeTest: vi.fn(),
    reload: vi.fn(),
    create: vi.fn(),
    setStatus: vi.fn(),
    vote: vi.fn(),
    reorderPriority: vi.fn(),
    remove: vi.fn(),
  }),
}));

// Not under test here - the shared grid + the (permission-gated, session-
// dependent) cluster suggestions strip; stub both to isolate the toggle.
vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: () => null,
}));
vi.mock('./cluster-suggestions', () => ({
  IdeaClusterSuggestions: () => null,
}));

describe('IdeasView - "Show test ideas" toggle (issue #1179)', () => {
  it('renders the toggle in operator mode (no provider = operator default)', () => {
    render(<IdeasView />);
    expect(screen.getByTestId('ideas-include-test')).toBeInTheDocument();
    expect(screen.getByText('Show test ideas')).toBeInTheDocument();
  });

  it('hides the toggle entirely in embed mode', () => {
    render(
      <IdeationRuntimeProvider
        runtime={{
          mode: 'embed',
          service: {
            listProducts: vi.fn(),
            listIdeas: vi.fn(),
            getIdea: vi.fn(),
            updateIdea: vi.fn(),
            createIdea: vi.fn(),
            setStatus: vi.fn(),
            vote: vi.fn(),
            reorderPriority: vi.fn(),
            suggestClusters: vi.fn(),
            remove: vi.fn(),
          },
          paths: {
            listHref: '/embed/ideas',
            formHref: (id) => `/embed/ideas/${id}`,
            newHref: '/embed/ideas/new',
          },
        }}
      >
        <IdeasView />
      </IdeationRuntimeProvider>,
    );
    expect(screen.queryByTestId('ideas-include-test')).not.toBeInTheDocument();
    expect(screen.queryByText('Show test ideas')).not.toBeInTheDocument();
  });
});
