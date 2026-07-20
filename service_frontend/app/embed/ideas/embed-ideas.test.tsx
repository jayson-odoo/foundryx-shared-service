import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Idea } from '@/types/ideation';
import type { UseIdeas } from '@/hooks/use-ideas';
import { IdeationRuntimeProvider, useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { ideationEmbedService } from '@/services/ideation-embed-service';

// The embed service's only backend dependency is the shared api-client.
vi.mock('@/lib/api-client', () => ({ apiFetch: vi.fn() }));
import { apiFetch } from '@/lib/api-client';
const mockApiFetch = vi.mocked(apiFetch);

function idea(id: string, over: Partial<Idea> = {}): Idea {
  return {
    id,
    productId: 'p-1',
    productName: 'Sorento CRM',
    status: 'captured',
    problem: 'Export orders to Excel',
    proposedSolution: null,
    impact: null,
    department: null,
    rawText: 'raw',
    source: 'whatsapp',
    submitterName: 'Jayson Tan',
    upvotes: 2,
    downvotes: 0,
    priority: 0,
    myVote: null,
    attachments: [],
    createdAt: '2026-07-20T00:00:00Z',
    ...over,
  } as Idea;
}

beforeEach(() => mockApiFetch.mockReset());

// ── the embed service hits the /embed/* routes (AC-CAP-11 — writes) ───────────
describe('ideationEmbedService → /embed/* endpoints', () => {
  it('validate posts the token and lists ideas from /embed/ideas', async () => {
    mockApiFetch.mockResolvedValueOnce({
      tenant_id: 't', connection_id: 'c', idea_id: null, product_id: 'p-1', scope: 'ideation',
    });
    const scope = await ideationEmbedService.validateToken('tok');
    expect(scope.product_id).toBe('p-1');
    expect(mockApiFetch).toHaveBeenCalledWith('/embed/validate', expect.objectContaining({ method: 'POST' }));

    mockApiFetch.mockResolvedValueOnce([idea('i-1')]);
    await ideationEmbedService.listIdeas();
    expect(mockApiFetch).toHaveBeenLastCalledWith('/embed/ideas');
  });

  it('create posts to /embed/ideas WITHOUT a productId (server forces it)', async () => {
    mockApiFetch.mockResolvedValueOnce(idea('new'));
    await ideationEmbedService.createIdea({ productId: 'ignored', problem: 'p', rawText: 'r' });
    const [path, init] = mockApiFetch.mock.calls[0];
    expect(path).toBe('/embed/ideas');
    expect((init as RequestInit).method).toBe('POST');
    expect(JSON.parse((init as RequestInit).body as string)).not.toHaveProperty('productId');
  });

  it('vote / status / reorder / delete hit the scoped embed routes', async () => {
    mockApiFetch.mockResolvedValue(idea('i-1'));
    await ideationEmbedService.vote('i-1', 'up');
    expect(mockApiFetch).toHaveBeenLastCalledWith('/embed/ideas/i-1/vote', expect.objectContaining({ method: 'POST' }));

    await ideationEmbedService.setStatus('i-1', 'triaged');
    expect(mockApiFetch).toHaveBeenLastCalledWith('/embed/ideas/i-1/status', expect.objectContaining({ method: 'POST' }));

    mockApiFetch.mockResolvedValueOnce([idea('i-1')]);
    await ideationEmbedService.reorderPriority(['i-1']);
    expect(mockApiFetch).toHaveBeenLastCalledWith('/embed/ideas/reorder', expect.objectContaining({ method: 'PUT' }));

    mockApiFetch.mockResolvedValueOnce(undefined);
    await ideationEmbedService.remove('i-1');
    expect(mockApiFetch).toHaveBeenLastCalledWith('/embed/ideas/i-1', expect.objectContaining({ method: 'DELETE' }));
  });

  it('update PATCHes /embed/ideas/{id} and never sends productId', async () => {
    mockApiFetch.mockResolvedValueOnce(idea('i-1', { problem: 'edited' }));
    await ideationEmbedService.updateIdea('i-1', { problem: 'edited', productId: 'nope' });
    const [path, init] = mockApiFetch.mock.calls[0];
    expect(path).toBe('/embed/ideas/i-1');
    expect((init as RequestInit).method).toBe('PATCH');
    expect(JSON.parse((init as RequestInit).body as string)).not.toHaveProperty('productId');
  });
});

// ── the runtime seam: one component, two modes ────────────────────────────────
describe('IdeationRuntimeProvider (embed mode)', () => {
  function Probe() {
    const { mode, service, paths } = useIdeationRuntime();
    return (
      <div>
        <span data-testid="mode">{mode}</span>
        <span data-testid="is-embed-service">{String(service === ideationEmbedService)}</span>
        <span data-testid="form-href">{paths.formHref('abc')}</span>
      </div>
    );
  }

  it('defaults to operator outside any provider', () => {
    render(<Probe />);
    expect(screen.getByTestId('mode').textContent).toBe('operator');
    expect(screen.getByTestId('form-href').textContent).toBe('/ideation/ideas/abc');
  });

  it('supplies the embed service + embed URLs under the embed provider', () => {
    render(
      <IdeationRuntimeProvider
        runtime={{
          mode: 'embed',
          service: ideationEmbedService,
          paths: {
            listHref: '/embed/ideas',
            formHref: (id) => `/embed/ideas/${id}`,
            newHref: '/embed/ideas/new',
          },
        }}
      >
        <Probe />
      </IdeationRuntimeProvider>,
    );
    expect(screen.getByTestId('mode').textContent).toBe('embed');
    expect(screen.getByTestId('is-embed-service').textContent).toBe('true');
    expect(screen.getByTestId('form-href').textContent).toBe('/embed/ideas/abc');
  });
});

// ── the SHARED board renders chrome-less in embed mode with embed card links ──
vi.mock('@/hooks/use-ideas', () => ({ useIdeas: vi.fn() }));
import { useIdeas } from '@/hooks/use-ideas';
import { TriageBoard } from '@/app/(protected)/ideation/board/triage-board';

const baseUseIdeas: UseIdeas = {
  ideas: [],
  products: [],
  loading: false,
  error: null,
  reload: vi.fn(),
  create: vi.fn(),
  setStatus: vi.fn(),
  vote: vi.fn(),
  reorderPriority: vi.fn(),
  remove: vi.fn(),
};

const embedRuntime = {
  mode: 'embed' as const,
  service: ideationEmbedService,
  paths: {
    listHref: '/embed/ideas#token=t',
    formHref: (id: string) => `/embed/ideas/${id}#token=t`,
    newHref: '/embed/ideas/new#token=t',
  },
};

describe('shared TriageBoard in embed mode', () => {
  afterEach(() => vi.mocked(useIdeas).mockReset());

  it('renders the SAME board component with cards, linking within the iframe', () => {
    vi.mocked(useIdeas).mockReturnValue({
      ...baseUseIdeas,
      ideas: [idea('i-1', { problem: 'Export orders to Excel' })],
    });
    render(
      <IdeationRuntimeProvider runtime={embedRuntime}>
        <TriageBoard />
      </IdeationRuntimeProvider>,
    );
    expect(screen.getByText('Export orders to Excel')).toBeInTheDocument();
    // The card link stays inside the iframe and carries the fragment token.
    const link = screen.getByText('Export orders to Excel').closest('a');
    expect(link?.getAttribute('href')).toBe('/embed/ideas/i-1#token=t');
  });
});
