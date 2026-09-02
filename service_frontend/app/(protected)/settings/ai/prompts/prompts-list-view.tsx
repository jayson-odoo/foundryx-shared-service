'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChevronRight, LoaderCircleIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useDatetime } from '@/hooks/use-datetime';
import { aiPromptsService } from '@/services/ai-prompts-service';
import type { AiPromptSummary } from '@/types/ai-prompt';
import { promptPath } from './paths';

/**
 * List page (plan §3.4): name, active production version, last updated.
 * Hairline-separated rows, not a bordered DataGrid table - this registry is
 * a handful of platform-seeded rows, not a growing tenant collection.
 */
export function PromptsListView() {
  const [prompts, setPrompts] = useState<AiPromptSummary[] | null>(null);
  const { formatDateTime } = useDatetime();

  useEffect(() => {
    let cancelled = false;
    aiPromptsService.listPrompts().then((rows) => {
      if (!cancelled) setPrompts(rows);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (prompts === null) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (prompts.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1 py-16 text-center">
        <p className="text-sm font-medium">No prompts registered yet.</p>
        <p className="text-sm text-muted-foreground">
          Prompts are seeded by the platform - none have been created yet.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border">
      <div className="flex items-center gap-4 px-4 py-2.5 text-[0.72rem] font-medium uppercase tracking-[0.05em] text-muted-foreground">
        <span className="flex-1">Name</span>
        <span className="w-20 shrink-0">Production</span>
        <span className="hidden w-44 shrink-0 sm:block">Last updated</span>
      </div>
      <div className="divide-y divide-border">
        {prompts.map((prompt) => {
          const updated = `${prompt.updatedAt ? formatDateTime(prompt.updatedAt) : '-'}${prompt.updatedByName ? ` · ${prompt.updatedByName}` : ''}`;
          return (
            <Link
              key={prompt.name}
              href={promptPath(prompt.name)}
              data-testid={`prompt-row-${prompt.name}`}
              className="flex items-center gap-4 px-4 py-3.5 transition-colors duration-150 ease-out hover:bg-muted/50 active:bg-muted"
            >
              <span
                title={prompt.name}
                className="min-w-0 flex-1 truncate font-mono text-sm font-medium tracking-[-0.01em] text-foreground"
              >
                {prompt.name}
              </span>
              <span className="w-20 shrink-0">
                {prompt.productionVersion != null ? (
                  <Badge variant="success" appearance="light" size="sm">
                    v{prompt.productionVersion}
                  </Badge>
                ) : (
                  <span className="text-xs text-muted-foreground">Unpublished</span>
                )}
              </span>
              <span
                title={updated}
                className="hidden w-44 shrink-0 truncate text-sm text-muted-foreground sm:block"
              >
                {updated}
              </span>
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
            </Link>
          );
        })}
      </div>
    </div>
  );
}
