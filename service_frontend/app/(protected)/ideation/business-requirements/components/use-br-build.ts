'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import { ExternalLink, Rocket } from 'lucide-react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import type { FormActionsNote, FormPrimaryAction } from '@/components/platform/resource-form';
import { businessRequirementService } from '@/services/business-requirement-service';
import type { BusinessRequirementDetail } from '@/types/business-requirement';

export const SEND_TO_BUILD_PERMISSION = 'ideation.business_requirements.send_to_build';

export interface UseBrBuildHandlers {
  /** Refresh the page with the BR the send returned (status + build). */
  onChanged: (br: BusinessRequirementDetail) => void;
}

export interface BrBuildSummary {
  repo: string | null;
  ideaCount: number;
  fieldsComplete: { done: number; total: number };
}

export interface UseBrBuildResult {
  /** Undefined when the caller may not send (the plain Edit primary stays). */
  primaryAction: FormPrimaryAction | undefined;
  actionsNote: string | FormActionsNote | undefined;
  confirmOpen: boolean;
  closeConfirm: () => void;
  confirmSend: () => Promise<void>;
  pending: boolean;
  summary: BrBuildSummary;
}

function isEmptyAnswer(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (typeof value === 'string') return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/** "<n> of <m> fields complete" over the STAMPED template's input fields. */
function fieldsComplete(br: BusinessRequirementDetail): { done: number; total: number } {
  const keys: string[] = [];
  for (const page of br.templateDoc?.pages ?? []) {
    for (const section of page.sections) {
      for (const field of section.fields) {
        if (field.key) keys.push(field.key);
      }
    }
  }
  const done = keys.filter((k) => !isEmptyAnswer(br.answers?.[k])).length;
  return { done, total: keys.length };
}

function repoShortName(repo: string | null, issueUrl: string | null): string {
  if (repo) return repo.split('/').pop() ?? repo;
  const match = issueUrl?.match(/github\.com\/[^/]+\/([^/]+)\//);
  return match?.[1] ?? 'issue';
}

/**
 * Send-to-build header state for the BR page (plan D2/D12, AC-STB-07/08): builds
 * the shell's `primaryAction` (CTA / disabled + reason / issue-link chip) and the
 * `actionsNote` line, and owns the confirm-dialog state + the single send call.
 * The server decides `canSend` and `blockers`; nothing here re-derives them.
 */
export function useBrBuild(
  br: BusinessRequirementDetail | null,
  handlers: UseBrBuildHandlers,
): UseBrBuildResult {
  const { onChanged } = handlers;
  const { can } = useCan();
  const { formatDateTime } = useDatetime();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  const canSendPermission = can(SEND_TO_BUILD_PERMISSION);
  const build = br?.build;

  const openConfirm = useCallback(() => setConfirmOpen(true), []);
  const closeConfirm = useCallback(() => setConfirmOpen(false), []);

  const confirmSend = useCallback(async () => {
    if (!br || inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    try {
      const updated = await businessRequirementService.sendToBuild(br.id);
      setConfirmOpen(false);
      onChanged(updated);
      toast.success('Sent to build.');
    } catch (e) {
      const detail =
        e instanceof ApiError && typeof e.detail === 'object' && e.detail
          ? (e.detail as { message?: string })
          : null;
      toast.error(
        detail?.message ?? (e instanceof Error ? e.message : 'Could not send to build.'),
      );
      if (e instanceof ApiError && e.status === 409) {
        // Another click won the race: reload and show the issue link.
        setConfirmOpen(false);
        try {
          onChanged(await businessRequirementService.get(br.id));
        } catch {
          // The toast above already told the user; the next page load recovers.
        }
      }
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [br, onChanged]);

  const summary = useMemo<BrBuildSummary>(
    () => ({
      repo: build?.repo ?? null,
      ideaCount: br?.ideaCount ?? 0,
      fieldsComplete: br ? fieldsComplete(br) : { done: 0, total: 0 },
    }),
    [br, build?.repo],
  );

  const view = useMemo(() => {
    if (!br || !build || !canSendPermission) {
      return { primaryAction: undefined, actionsNote: undefined };
    }
    const issueUrl = build.issueUrl;
    const issueLabel = issueUrl
      ? `${repoShortName(build.repo, issueUrl)} #${build.issueNumber ?? ''}`.trim()
      : '';
    // No issue and no send edge (in FR, delivered, archived): plain Edit returns.
    if (!issueUrl && !build.sendEdgeAvailable) {
      return { primaryAction: undefined, actionsNote: undefined };
    }
    // The issue chip is the primary only while a re-send is not possible.
    const by = build.sentBy?.name ? ` by ${build.sentBy.name}` : '';
    if (issueUrl && !build.canSend) {
      return {
        primaryAction: {
          id: 'build-issue',
          label: issueLabel,
          icon: ExternalLink,
          href: issueUrl,
        } satisfies FormPrimaryAction,
        actionsNote: build.sentAt ? `Sent ${formatDateTime(build.sentAt)}${by}` : undefined,
      };
    }
    // D10 re-send: the CTA returns and the issue link moves into the note.
    const resendNote: FormActionsNote | undefined = issueUrl
      ? {
          text: build.sentAt ? `Sent ${formatDateTime(build.sentAt)}${by}` : 'Sent',
          href: issueUrl,
          linkLabel: issueLabel,
        }
      : undefined;
    const reason = build.canSend ? undefined : build.blockers[0];
    return {
      primaryAction: {
        id: 'send-to-build',
        label: 'Send to build',
        icon: Rocket,
        disabled: !build.canSend || pending,
        reason,
        onRun: openConfirm,
      } satisfies FormPrimaryAction,
      actionsNote: reason ?? resendNote,
    };
  }, [br, build, canSendPermission, formatDateTime, openConfirm, pending]);

  return {
    primaryAction: view.primaryAction,
    actionsNote: view.actionsNote,
    confirmOpen,
    closeConfirm,
    confirmSend,
    pending,
    summary,
  };
}
