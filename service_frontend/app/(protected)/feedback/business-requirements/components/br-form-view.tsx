'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { ResourceForm } from '@/components/platform/resource-form';
import { BrSendConfirmDialog } from './br-send-confirm-dialog';
import { useBrBuild } from './use-br-build';
import { useBrForm } from './use-br-form';
import { BR_PATH } from './paths';

export interface BrFormViewProps {
  brId: string;
  initialEditing: boolean;
  /** Deep-link a starting tab (e.g. `grill` - Promote-to-BR lands here). */
  initialTab?: string;
}

/** Loads + renders a Business Requirement detail form (tabbed ResourceForm). */
export function BrFormView({ brId, initialEditing, initialTab }: BrFormViewProps) {
  const { config: baseConfig, isLoading, notFound, br, onBrChanged } = useBrForm(
    brId,
    initialEditing,
    initialTab,
  );
  // Send to build: the header CTA / issue chip + reason line ride the shell's
  // `primaryAction` / `actionsNote`; the confirm dialog renders beside the form.
  const build = useBrBuild(br, { onChanged: onBrChanged });
  const config = useMemo(
    () =>
      baseConfig
        ? { ...baseConfig, primaryAction: build.primaryAction, actionsNote: build.actionsNote }
        : null,
    [baseConfig, build.primaryAction, build.actionsNote],
  );

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Business requirement not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={BR_PATH}>Back to business requirements</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <ResourceForm config={config} />
      <BrSendConfirmDialog
        open={build.confirmOpen}
        repo={build.summary.repo}
        ideaCount={build.summary.ideaCount}
        fieldsComplete={build.summary.fieldsComplete}
        pending={build.pending}
        onCancel={build.closeConfirm}
        onConfirm={() => void build.confirmSend()}
      />
    </Container>
  );
}
