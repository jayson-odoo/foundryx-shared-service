'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Bot } from 'lucide-react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { useAiModels } from '@/hooks/use-ai-models';
import { useAiPrerequisite } from '@/hooks/use-ai-prerequisite';
import { aiService } from '@/services/ai-service';
import type { AiAgent } from '@/types/ai';
import { AgentFormFields, type AgentFormValues } from './agent-form-fields';
import { AI_AGENTS_PATH, agentFormHref, agentPath } from './paths';
import { useAgentActions } from './use-agent-actions';

export interface UseAgentFormResult {
  config: ResourceFormConfig<AiAgent> | null;
  form: UseFormReturn<AgentFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

const EMPTY_VALUES: AgentFormValues = {
  name: '',
  description: '',
  connectionId: '',
  model: '',
  temperature: '0',
  skillIds: [],
  isEnabled: true,
};

function toValues(agent: AiAgent): AgentFormValues {
  return {
    name: agent.name,
    description: agent.description,
    connectionId: agent.connectionId ?? '',
    model: agent.model,
    temperature: String(agent.temperature),
    skillIds: agent.skills.map((s) => s.id),
    isEnabled: agent.isEnabled,
  };
}

/** `agentId === undefined` = create mode (/settings/ai/agents/new). */
export function useAgentForm(
  agentId: string | undefined,
  initialEditing: boolean,
): UseAgentFormResult {
  const router = useRouter();
  const actions = useAgentActions();
  const isNew = agentId === undefined;

  const [agent, setAgent] = useState<AiAgent | null>(null);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<AgentFormValues>({ defaultValues: EMPTY_VALUES });
  const { hasConnection, connections, skills } = useAiPrerequisite();
  const connectionId = form.watch('connectionId');
  const { models, isLoading: modelsLoading, isLive: modelsLive } = useAiModels(connectionId);

  useEffect(() => {
    if (isNew) return;
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      const loaded = await aiService.getAgent(agentId);
      if (cancelled) return;
      if (!loaded) {
        setNotFound(true);
        setIsLoading(false);
        return;
      }
      setAgent(loaded);
      form.reset(toValues(loaded));
      setIsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [agentId, isNew, form]);

  const onSave = useCallback(async (): Promise<boolean> => {
    const values = form.getValues();
    if (!values.name.trim()) {
      toast.error('Name is required.');
      return false;
    }
    const input = {
      name: values.name.trim(),
      description: values.description.trim(),
      connectionId: values.connectionId || null,
      model: values.model.trim(),
      temperature: Number(values.temperature) || 0,
      skillIds: values.skillIds,
      isEnabled: values.isEnabled,
    };
    try {
      if (isNew) {
        const created = await aiService.createAgent(input);
        toast.success(`Agent "${created.name}" created.`);
        router.replace(agentPath(created.id));
      } else {
        const updated = await aiService.updateAgent(agentId, input);
        setAgent(updated);
        form.reset(toValues(updated));
        toast.success('Agent saved.');
      }
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  }, [form, isNew, router, agentId]);

  const onCancel = useCallback(() => {
    if (isNew) {
      router.push(AI_AGENTS_PATH);
      return;
    }
    if (agent) form.reset(toValues(agent));
  }, [agent, form, isNew, router]);

  const config = useMemo<ResourceFormConfig<AiAgent> | null>(() => {
    if (!isNew && !agent) return null;
    return {
      breadcrumb: [
        { label: 'AI agents', href: AI_AGENTS_PATH },
        { label: isNew ? 'New agent' : (agent?.name ?? '') },
      ],
      backHref: AI_AGENTS_PATH,
      title: isNew ? 'New agent' : (agent?.name ?? ''),
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Bot,
          render: ({ editing }) => (
            <AgentFormFields
              form={form}
              editing={editing}
              agent={agent}
              connections={connections}
              skills={skills}
              models={models}
              modelsLoading={modelsLoading}
              modelsLive={modelsLive}
              hasConnection={hasConnection}
            />
          ),
        },
      ],
      initialTabId: 'details',
      actions,
      actionRows: agent ? [agent] : [],
      editable: true,
      editPermission: 'ai_agents.manage',
      initialEditing: isNew ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: isNew
        ? undefined
        : {
            fetchAt: (query, index) =>
              aiService.getAgentAt(query, index).then((r) => ({
                recordId: r.agent?.id ?? null,
                total: r.total,
              })),
            buildHref: (recordId, ctx, index) => agentFormHref(recordId, { ctx, index }),
          },
    };
  }, [
    actions,
    agent,
    connections,
    form,
    hasConnection,
    initialEditing,
    isNew,
    models,
    modelsLive,
    modelsLoading,
    onCancel,
    onSave,
    skills,
  ]);

  return { config, form, isLoading, notFound };
}
