'use client';

import { Loader2, TriangleAlert } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { useGrill } from '@/hooks/use-grill';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import { GrillChat } from './grill-chat';

export interface BrGrillTabProps {
  brId: string;
  /** Called after a successful Generate so the Details tab reflects the new
   * answers (the use-br-form load/setAnswers seam). */
  onGenerated?: (br: BusinessRequirementDetail) => void;
}

/**
 * Grill tab (AC-BI-29) — the AI grill inside the BR ResourceForm, inheriting the
 * shell's breadcrumb / record-nav / permissions. Shows the prerequisite warning
 * when no AI connection is configured (AC-BI-11); otherwise the conversation.
 */
export function BrGrillTab({ brId, onGenerated }: BrGrillTabProps) {
  const grill = useGrill(brId, { onGenerated });

  if (grill.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  if (!grill.ready) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-16 text-center">
          <TriangleAlert className="size-6 text-amber-500" />
          <p className="max-w-sm text-sm text-muted-foreground">
            {grill.warning ?? 'The grill is not available for this workspace yet.'}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="py-4">
        <GrillChat
          messages={grill.messages}
          fields={grill.fields}
          coveredFields={grill.coveredFields}
          missingFields={grill.missingFields}
          sending={grill.sending}
          generating={grill.generating}
          disabled={!grill.ready}
          error={grill.error}
          onSend={grill.sendTurn}
          onGenerate={grill.generate}
        />
      </CardContent>
    </Card>
  );
}
