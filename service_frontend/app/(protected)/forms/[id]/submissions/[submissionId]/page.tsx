'use client';

/** Submission detail (plan sprint-3/01 D18) - read-only render of the PINNED
 * version (D9: the reviewer sees the form as it was), graph-driven transition
 * buttons (edge label = button text, D15) and the raw answers. Plan sprint-4/04
 * adds the Revise action (clone a frozen entry into a new Draft), the
 * edit-and-resubmit entry for the current Draft, a "rev N" badge and a
 * revision-history panel (each revision opens pinned to ITS own version). */
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { ArrowLeft, ChevronLeft, ChevronRight, LoaderCircleIcon, PencilLine, RotateCcw } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FormRenderer } from '@/components/platform/form-renderer';
import { apiFetchBlob } from '@/lib/api-client';
import { RequirePermission } from '@/components/common/require-permission';
import { StatusBadge, colorToHex, colorToTone } from '@/components/platform/status-badge';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { useFormSubmission } from '@/hooks/use-form-submission';
import { useSubmissionNav } from './use-submission-nav';

export default function FormSubmissionPage() {
  const params = useParams();
  const formId = String(params.id);
  const submissionId = String(params.submissionId);

  return (
    <RequirePermission permission="submissions.read">
      <SubmissionDetail formId={formId} submissionId={submissionId} />
    </RequirePermission>
  );
}

function SubmissionDetail({ formId, submissionId }: { formId: string; submissionId: string }) {
  const { can } = useCan();
  const { data: session } = useSession();
  const router = useRouter();
  const { formatDateTime } = useDatetime();
  const nav = useSubmissionNav(formId, submissionId);
  const {
    submission,
    definition,
    graph,
    allowRevisions,
    revisions,
    isActive,
    loading,
    notFound,
    busy,
    fireTransition,
    revise,
  } = useFormSubmission(formId, submissionId);

  if (loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !submission) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Submission not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={`/forms/${formId}`}>Back to form</Link>
          </Button>
        </div>
      </Container>
    );
  }

  const fireable = (graph?.transitions ?? []).filter((t) =>
    (submission.availableTransitionIds ?? []).includes(t.id),
  );
  const isOwnerOrManager =
    can('submissions.manage') || (!!session?.user?.id && submission.userId === session.user.id);
  // Revise: a frozen current revision on a revision-enabled form.
  const canRevise =
    allowRevisions && submission.isCurrent && !isActive && isOwnerOrManager;
  // Edit & resubmit: the current revision while still a Draft (answers editable).
  const canEditDraft = submission.isCurrent && isActive && isOwnerOrManager;
  const hasHistory = revisions.length > 1;

  async function onRevise() {
    const draftId = await revise();
    if (draftId) router.push(`/forms/${formId}/submissions/${draftId}`);
  }

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-4 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/forms/${formId}`}>
                <ArrowLeft className="size-4" />
              </Link>
            </Button>
            <div>
              <h2 className="font-heading text-lg font-semibold text-foreground">
                {submission.userName ?? 'Anonymous'}
              </h2>
              <p className="text-xs text-muted-foreground">
                v{submission.versionNumber}
                {submission.submittedAt && <> · {formatDateTime(submission.submittedAt)}</>}
              </p>
            </div>
            <StatusBadge
              status={submission.statusKey}
              registry={{
                [submission.statusKey]: {
                  label: submission.statusLabel,
                  tone: colorToTone(submission.statusColor),
                  hex: colorToHex(submission.statusColor),
                },
              }}
            />
            {(hasHistory || submission.revisionNumber > 1) && (
              <Badge
                variant={submission.isCurrent ? 'primary' : 'secondary'}
                appearance="light"
                size="sm"
                data-testid="revision-badge"
              >
                {submission.isCurrent ? `Current · rev ${submission.revisionNumber}` : `rev ${submission.revisionNumber}`}
              </Badge>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canEditDraft && (
              <Button size="sm" disabled={busy} asChild data-testid="edit-revision">
                <Link href={`/forms/${formId}/fill?revision=${submission.id}`}>
                  <PencilLine className="size-4" />
                  Edit &amp; resubmit
                </Link>
              </Button>
            )}
            {canRevise && (
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => void onRevise()}
                data-testid="revise-submission"
              >
                <RotateCcw className="size-4" />
                Revise
              </Button>
            )}
            {can('submissions.manage') && fireable.length > 0 && (
              <div className="flex flex-wrap items-center gap-2" data-testid="submission-transitions">
                {fireable.map((t) => (
                  <Button
                    key={t.id}
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void fireTransition(t.id)}
                    data-testid={`transition-${t.label.toLowerCase().replace(/\s+/g, '-')}`}
                  >
                    {t.label}
                  </Button>
                ))}
              </div>
            )}
            {/* Prev / next scroll-through across the form's submissions. */}
            {nav.total > 1 && nav.index >= 0 && (
              <div className="flex items-center gap-1" data-testid="submission-record-nav">
                <Button
                  variant="outline"
                  size="sm"
                  className="size-8 p-0"
                  disabled={!nav.prevId}
                  onClick={() => nav.prevId && router.push(`/forms/${formId}/submissions/${nav.prevId}`)}
                  aria-label="Previous submission"
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <span className="px-1 text-xs tabular-nums text-muted-foreground">
                  {nav.index + 1} / {nav.total}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="size-8 p-0"
                  disabled={!nav.nextId}
                  onClick={() => nav.nextId && router.push(`/forms/${formId}/submissions/${nav.nextId}`)}
                  aria-label="Next submission"
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
          <div className="rounded-lg border border-border p-4">
            {definition ? (
              <FormRenderer definition={definition} mode="read" answers={submission.answers} submissionId={submission.id} fileFetcher={apiFetchBlob} />
            ) : (
              <p className="py-8 text-center text-sm text-muted-foreground">
                The version this submission was made against is unavailable.
              </p>
            )}
          </div>
          <div className="flex flex-col gap-4">
            {hasHistory && (
              <RevisionHistory
                formId={formId}
                currentId={submission.id}
                revisions={revisions}
                formatDateTime={formatDateTime}
              />
            )}
            <div className="h-fit rounded-lg border border-border p-4">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-medium text-foreground">Raw answers</h2>
                <Badge variant="secondary" appearance="light" size="sm">
                  v{submission.versionNumber}
                </Badge>
              </div>
              <pre className="max-h-[60vh] overflow-auto rounded bg-muted/40 p-3 text-xs leading-relaxed">
                {JSON.stringify(submission.answers, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </Container>
  );
}

function RevisionHistory({
  formId,
  currentId,
  revisions,
  formatDateTime,
}: {
  formId: string;
  currentId: string;
  revisions: import('@/types/forms').FormSubmissionRow[];
  formatDateTime: (iso: string) => string;
}) {
  return (
    <div className="h-fit rounded-lg border border-border p-4" data-testid="revision-history">
      <h2 className="mb-3 text-sm font-medium text-foreground">Revision history</h2>
      <ol className="flex flex-col gap-2">
        {revisions.map((r) => {
          const active = r.id === currentId;
          return (
            <li key={r.id}>
              <Link
                href={`/forms/${formId}/submissions/${r.id}`}
                className={`flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs transition-colors ${
                  active
                    ? 'border-primary/40 bg-primary/5'
                    : 'border-border hover:bg-muted/50'
                }`}
                aria-current={active ? 'true' : undefined}
              >
                <span className="flex items-center gap-2">
                  <span className="font-medium tabular-nums">rev {r.revisionNumber}</span>
                  {r.isCurrent && (
                    <Badge variant="primary" appearance="light" size="sm">
                      Current
                    </Badge>
                  )}
                </span>
                <span className="flex items-center gap-2 text-muted-foreground">
                  <StatusBadge
                    status={r.statusKey}
                    registry={{
                      [r.statusKey]: {
                        label: r.statusLabel,
                        tone: colorToTone(r.statusColor),
                        hex: colorToHex(r.statusColor),
                      },
                    }}
                    size="sm"
                  />
                  <span className="tabular-nums">
                    {r.submittedAt ? formatDateTime(r.submittedAt) : '-'}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
