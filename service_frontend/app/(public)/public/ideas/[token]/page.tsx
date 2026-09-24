'use client';

/**
 * Public (anonymous) idea-status page (S5, AC-1601). Pre-auth, branded by the
 * public layout (white-label). Shows the idea number, title (or "Idea
 * <number>" when title is null), and the status as a pill - never the
 * problem/solution/impact/department/submitter/product. No login prompt.
 * Responsive down to ~375px.
 */
import { useParams } from 'next/navigation';
import { AlertCircle, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { usePublicIdeaStatus } from '@/hooks/use-public-idea-status';

export default function PublicIdeaStatusPage() {
  const params = useParams();
  const token = String(params.token);
  const { view, loading, notFound } = usePublicIdeaStatus(token);

  const shell = (body: React.ReactNode) => (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 px-4">{body}</div>
  );

  if (loading && !view) {
    return shell(
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
      </div>,
    );
  }

  if (notFound || !view) {
    return shell(
      <div
        className="flex flex-col items-center gap-3 py-24 text-center"
        data-testid="idea-status-notfound"
      >
        <AlertCircle className="size-10 text-muted-foreground" />
        <p className="text-base font-medium">This link isn’t available.</p>
      </div>,
    );
  }

  return shell(
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <p className="text-sm font-medium text-muted-foreground">{view.ideaNumber}</p>
      <p className="font-heading text-xl font-semibold">
        {view.title ?? `Idea ${view.ideaNumber}`}
      </p>
      <Badge variant="secondary" appearance="light">
        {view.status}
      </Badge>
    </div>,
  );
}
