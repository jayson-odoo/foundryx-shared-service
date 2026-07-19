import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Idea } from '@/types/ideation';
import { EmbedIdeasBoard } from './embed-ideas-board';

// Mock the embed data boundary — the page's only backend dependency.
vi.mock('@/services/ideation-embed-service', () => ({
  ideationEmbedService: {
    validateToken: vi.fn(),
    listIdeas: vi.fn(),
    getIdea: vi.fn(),
  },
}));

import { ideationEmbedService } from '@/services/ideation-embed-service';

const validateToken = vi.mocked(ideationEmbedService.validateToken);
const listIdeas = vi.mocked(ideationEmbedService.listIdeas);

function idea(id: string, problem: string): Idea {
  return {
    id,
    productId: 'p-1',
    productName: 'Sorento CRM',
    status: 'captured',
    problem,
    proposedSolution: null,
    impact: null,
    department: null,
    rawText: problem,
    source: 'whatsapp',
    submitterName: 'Jayson Tan',
    upvotes: 2,
    downvotes: 0,
    priority: 0,
    myVote: null,
    attachments: [],
    createdAt: '2026-07-20T00:00:00Z',
  } as Idea;
}

function setHash(hash: string) {
  window.location.hash = hash;
}

describe('EmbedIdeasBoard (chrome-less embed page)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    setHash('');
  });

  it('shows the "session expired" state when there is no token (AC-E-9)', async () => {
    setHash('');
    render(<EmbedIdeasBoard />);
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /session expired/i })).toBeInTheDocument(),
    );
    // Never renders another tenant's board without a valid token.
    expect(validateToken).not.toHaveBeenCalled();
    expect(listIdeas).not.toHaveBeenCalled();
  });

  it('renders the tenant ideas with a valid token (AC-E-8)', async () => {
    setHash('#token=valid-embed-token');
    validateToken.mockResolvedValue({
      tenant_id: 'tenant-A',
      connection_id: 'sorento-ideation',
      idea_id: null,
      scope: 'ideation',
    });
    listIdeas.mockResolvedValue([idea('i-1', 'Export orders to Excel')]);

    render(<EmbedIdeasBoard />);

    await waitFor(() => expect(screen.getByText('Export orders to Excel')).toBeInTheDocument());
    expect(validateToken).toHaveBeenCalledWith('valid-embed-token');
    expect(screen.getByRole('heading', { name: /^ideas$/i })).toBeInTheDocument();
  });

  it('renders exactly the tenant-scoped rows the service returns — no fabricated cross-tenant rows (AC-E-8/12)', async () => {
    setHash('#token=tenant-A-token');
    validateToken.mockResolvedValue({
      tenant_id: 'tenant-A',
      connection_id: 'sorento-ideation',
      idea_id: null,
      scope: 'ideation',
    });
    // The backend scopes to the token's tenant; the FE renders ONLY what it gets.
    listIdeas.mockResolvedValue([idea('a-1', 'Tenant A idea one'), idea('a-2', 'Tenant A idea two')]);

    render(<EmbedIdeasBoard />);

    await waitFor(() => expect(screen.getByText('Tenant A idea one')).toBeInTheDocument());
    expect(screen.getByText('Tenant A idea two')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('falls back to the expired state when the token is rejected (AC-E-9)', async () => {
    setHash('#token=expired');
    validateToken.mockRejectedValue(Object.assign(new Error('invalid'), { status: 401 }));

    render(<EmbedIdeasBoard />);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /session expired/i })).toBeInTheDocument(),
    );
    expect(listIdeas).not.toHaveBeenCalled();
  });
});
