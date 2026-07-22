'use client';

import { useEffect, useState } from 'react';
import { aiService } from '@/services/ai-service';
import type { AiConnectionOption, AiSkillOption } from '@/types/ai';

export interface UseAiPrerequisiteResult {
  /** AC-BI-11 — false ⇒ show the "no AI connection configured" warning. */
  hasConnection: boolean;
  connections: AiConnectionOption[];
  skills: AiSkillOption[];
  isLoading: boolean;
}

/**
 * The agent form's option sources + the missing-prerequisite signal.
 *
 * Foolproof-UI: the connection picker offers ONLY real LLM connections, and a
 * workspace with none is warned up front rather than discovering it at run time.
 */
export function useAiPrerequisite(): UseAiPrerequisiteResult {
  const [connections, setConnections] = useState<AiConnectionOption[]>([]);
  const [skills, setSkills] = useState<AiSkillOption[]>([]);
  const [hasConnection, setHasConnection] = useState(true);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      aiService.getPrerequisite().catch(() => ({ hasConnection: false, connections: [] })),
      aiService.listSkillOptions().catch(() => []),
    ])
      .then(([prerequisite, skillOptions]) => {
        if (cancelled) return;
        setHasConnection(prerequisite.hasConnection);
        setConnections(prerequisite.connections);
        setSkills(skillOptions);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { hasConnection, connections, skills, isLoading };
}
