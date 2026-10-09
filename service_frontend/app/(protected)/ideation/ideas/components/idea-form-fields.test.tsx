/**
 * AC-94-33 (no Status control, in any mode) and AC-94-46 (the form shows the
 * real `rank`, never the raw stored `priority`) - issue #94, ideation round 2,
 * plan sections 4.1 and 5.
 *
 * TEST-FIRST (PRINCIPLES.md): `DetailsTab` still renders a bare
 * `@/components/ui/select` Status row in edit mode and an engine-labelled
 * status badge in read mode, and renders the raw `idea.priority` - every
 * assertion below is expected to fail until slice S1 lands.
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useForm } from 'react-hook-form';
import { Form } from '@/components/ui/form';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import type { Idea, Product } from '@/types/ideation';
import { DetailsTab } from './idea-form-fields';
import type { IdeaFormValues } from './idea-schema';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v.slice(0, 10),
    formatDateTime: (v: string) => v.slice(0, 10),
    formatTime: (v: string) => v.slice(11, 16),
  }),
}));

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 0,
  downvotes: 0,
  myVote: null,
  // Deliberately a DIFFERENT number from `rank` below, so a test asserting
  // "#1" cannot pass by accident if the component still renders the raw
  // stored `priority` instead of the engine-computed `rank`.
  priority: 7,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

const products: Product[] = [{ id: 'prod-1', name: 'Sorento CRM', kind: 'software' }];

function Harness({ idea, editing }: { idea: Idea | null; editing: boolean }) {
  const form = useForm<IdeaFormValues>({
    defaultValues: {
      problem: idea?.problem ?? '',
      productId: idea?.productId ?? '',
      proposedSolution: idea?.proposedSolution ?? '',
      impact: idea?.impact ?? '',
      department: idea?.department ?? '',
      rawText: idea?.rawText ?? '',
    },
  });
  return (
    <Form {...form}>
      <DetailsTab form={form} editing={editing} creating={false} idea={idea} products={products} />
    </Form>
  );
}

describe('DetailsTab - no Status control in any mode (AC-94-33)', () => {
  it('renders no Status row in EDIT mode', () => {
    render(<Harness idea={anIdea()} editing />);
    expect(screen.queryByText('Status')).not.toBeInTheDocument();
    expect(document.querySelector('select')).toBeNull();
  });

  it('renders no Status row in READ mode either (owner Q5)', () => {
    render(<Harness idea={anIdea()} editing={false} />);
    expect(screen.queryByText('Status')).not.toBeInTheDocument();
    // Today's read-mode badge text for a captured idea ("New") must not
    // appear as a status pill on this tab (status lives on the list/board).
    expect(screen.queryByText('New')).not.toBeInTheDocument();
  });
});

vi.mock('@/hooks/use-idea-comments', () => ({
  useIdeaComments: () => ({
    threads: [],
    count: 0,
    loading: false,
    error: null,
    add: vi.fn(),
    edit: vi.fn(),
    remove: vi.fn(),
  }),
}));

describe('DetailsTab - Votes row moved to the header, Comments section (AC-19-16/21)', () => {
  it('has no Votes row (the vote box lives in the header avatar slot)', () => {
    render(<Harness idea={anIdea({ upvotes: 5 })} editing={false} />);
    expect(screen.queryByText('Votes')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /upvote/i })).not.toBeInTheDocument();
  });

  it('shows the Comments section in view mode for an existing idea', () => {
    render(<Harness idea={anIdea()} editing={false} />);
    expect(screen.getByRole('heading', { name: /^Comments/ })).toBeInTheDocument();
  });

  it('hides the Comments section while editing', () => {
    render(<Harness idea={anIdea()} editing />);
    expect(screen.queryByRole('heading', { name: /^Comments/ })).not.toBeInTheDocument();
  });
});

function priorityRowValue(): HTMLElement {
  const label = screen.getByText('Priority');
  const row = label.parentElement as HTMLElement;
  return row;
}

// ── BLOCKER 1 (issue #94 review round 1) - the "Merged into" link must resolve
// through the runtime's OWN `paths.formHref`, never the bare operator helper
// (the CRM embed iframe has no operator session and would 404/redirect to
// sign-in on `/ideation/ideas/<id>`). ──────────────────────────────────────

describe('DetailsTab - "Merged into" link is runtime-aware (BLOCKER 1)', () => {
  const mergedInto = { id: 'survivor-1', ideaNumber: 'IDEA-0012', title: 'Survivor idea' };

  it('operator mode: links to the operator path', () => {
    render(<Harness idea={anIdea({ mergedInto } as Partial<Idea>)} editing={false} />);
    const link = screen.getByRole('link', { name: 'IDEA-0012' });
    expect(link).toHaveAttribute('href', '/ideation/ideas/survivor-1');
  });

  it('embed mode: links to the embed path, never the operator one', () => {
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
        <Harness idea={anIdea({ mergedInto } as Partial<Idea>)} editing={false} />
      </IdeationRuntimeProvider>,
    );
    const link = screen.getByRole('link', { name: 'IDEA-0012' });
    expect(link).toHaveAttribute('href', '/embed/ideas/survivor-1');
  });
});

describe('DetailsTab - Priority shows the real rank, never the raw stored priority (AC-94-46)', () => {
  it('reads "#{rank}" for a ranked idea', () => {
    render(<Harness idea={anIdea({ rank: 1 } as Partial<Idea>)} editing={false} />);
    const row = within(priorityRowValue());
    expect(row.getByText('#1')).toBeInTheDocument();
    expect(row.queryByText('#7')).not.toBeInTheDocument(); // the raw `priority`
  });

  it('reads "-" for an unranked (archived/merged) idea, never "#0"', () => {
    render(<Harness idea={anIdea({ rank: null } as Partial<Idea>)} editing={false} />);
    const row = within(priorityRowValue());
    expect(row.getByText('-')).toBeInTheDocument();
    expect(row.queryByText(/^#/)).not.toBeInTheDocument();
  });
});
