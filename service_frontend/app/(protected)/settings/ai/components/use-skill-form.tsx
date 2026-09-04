'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { FileText, History } from 'lucide-react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { toast } from 'sonner';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FormRow, type ResourceFormConfig } from '@/components/platform/resource-form';
import { aiService } from '@/services/ai-service';
import type { AiSkill } from '@/types/ai';
import type { ListQuery } from '@/types/resource';
import { AI_SKILLS_PATH, skillFormHref, skillPath } from './paths';
import { SkillVersionsTab } from './skill-versions-tab';
import { useSkillActions } from './use-skills-list-config';

export interface SkillFormValues {
  key: string;
  name: string;
  description: string;
  body: string;
}

export interface UseSkillFormResult {
  config: ResourceFormConfig<AiSkill> | null;
  form: UseFormReturn<SkillFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

const EMPTY_VALUES: SkillFormValues = { key: '', name: '', description: '', body: '' };

function toValues(skill: AiSkill): SkillFormValues {
  return {
    key: skill.key,
    name: skill.name,
    description: skill.description,
    body: skill.body,
  };
}

export function useSkillForm(
  skillId: string | undefined,
  initialEditing: boolean,
): UseSkillFormResult {
  const router = useRouter();
  const actions = useSkillActions();
  const isNew = skillId === undefined;

  const [skill, setSkill] = useState<AiSkill | null>(null);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [notFound, setNotFound] = useState(false);
  const [versionsToken, setVersionsToken] = useState(0);

  const form = useForm<SkillFormValues>({ defaultValues: EMPTY_VALUES });

  const refresh = useCallback(
    async (id: string) => {
      const fresh = await aiService.getSkill(id);
      if (fresh) {
        setSkill(fresh);
        form.reset(toValues(fresh));
      }
    },
    [form],
  );

  useEffect(() => {
    if (isNew) return;
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      const loaded = await aiService.getSkill(skillId);
      if (cancelled) return;
      if (!loaded) {
        setNotFound(true);
        setIsLoading(false);
        return;
      }
      setSkill(loaded);
      form.reset(toValues(loaded));
      setIsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [skillId, isNew, form]);

  const onSave = useCallback(async (): Promise<boolean> => {
    const values = form.getValues();
    if (!values.name.trim()) {
      toast.error('Name is required.');
      return false;
    }
    try {
      if (isNew) {
        if (!values.key.trim()) {
          toast.error('Key is required.');
          return false;
        }
        const created = await aiService.createSkill({
          key: values.key.trim(),
          name: values.name.trim(),
          description: values.description.trim(),
          body: values.body,
        });
        toast.success(`Skill "${created.name}" created.`);
        router.replace(skillPath(created.id));
      } else {
        const updated = await aiService.updateSkill(skillId, {
          name: values.name.trim(),
          description: values.description.trim(),
          body: values.body,
        });
        // Editing a PROVIDED (platform-tier) skill forks a tenant copy - follow
        // the new id rather than leaving the form pointed at the shared row.
        if (updated.id !== skillId) {
          toast.success('Saved as your workspace copy.');
          router.replace(skillPath(updated.id));
          return true;
        }
        setSkill(updated);
        form.reset(toValues(updated));
        setVersionsToken((t) => t + 1);
        toast.success(
          updated.activeVersionNumber
            ? `Saved - now on v${updated.activeVersionNumber}.`
            : 'Skill saved.',
        );
      }
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  }, [form, isNew, router, skillId]);

  const onCancel = useCallback(() => {
    if (isNew) {
      router.push(AI_SKILLS_PATH);
      return;
    }
    if (skill) form.reset(toValues(skill));
  }, [form, isNew, router, skill]);

  // Stable across renders (fix round 2, AC-DLA-30/31 D7) - see use-user-form.tsx.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      aiService.getSkillAt(query, index).then((r) => ({
        recordId: r.skill?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => skillFormHref(recordId, { ctx, index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<AiSkill> | null>(() => {
    if (!isNew && !skill) return null;
    return {
      breadcrumb: [
        { label: 'AI skills', href: AI_SKILLS_PATH },
        { label: isNew ? 'New skill' : (skill?.name ?? '') },
      ],
      backHref: AI_SKILLS_PATH,
      title: isNew ? 'New skill' : (skill?.name ?? ''),
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: FileText,
          render: ({ editing }) => (
            <>
              {skill?.isPlatform && (
                <Alert variant="secondary" className="mb-5">
                  <AlertTitle>
                    A provided skill - editing it creates your own copy.
                  </AlertTitle>
                </Alert>
              )}
              <Card>
                <CardContent className="py-1">
                  <FormRow label="Key" required={isNew}>
                    {isNew ? (
                      <FormField
                        control={form.control}
                        name="key"
                        render={({ field }) => (
                          <FormItem className="max-w-sm">
                            <FormControl>
                              <Input placeholder="e.g. grill-me-business" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    ) : (
                      <span className="font-mono text-xs">{skill?.key}</span>
                    )}
                  </FormRow>

                  <FormRow label="Name" required={editing}>
                    {editing ? (
                      <FormField
                        control={form.control}
                        name="name"
                        render={({ field }) => (
                          <FormItem className="max-w-sm">
                            <FormControl>
                              <Input {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    ) : (
                      (skill?.name ?? '-')
                    )}
                  </FormRow>

                  <FormRow label="Description">
                    {editing ? (
                      <FormField
                        control={form.control}
                        name="description"
                        render={({ field }) => (
                          <FormItem className="max-w-lg">
                            <FormControl>
                              <Textarea rows={2} {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    ) : (
                      (skill?.description || '-')
                    )}
                  </FormRow>

                  <FormRow label="Prompt">
                    {editing ? (
                      <FormField
                        control={form.control}
                        name="body"
                        render={({ field }) => (
                          <FormItem>
                            <FormControl>
                              <Textarea rows={16} className="font-mono text-xs" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    ) : (
                      <pre className="whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground">
                        {skill?.body || '-'}
                      </pre>
                    )}
                  </FormRow>
                </CardContent>
              </Card>
            </>
          ),
        },
        {
          id: 'versions',
          label: 'Versions',
          icon: History,
          render: () =>
            isNew || !skillId ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                Save the skill to create its first version.
              </p>
            ) : (
              <SkillVersionsTab
                skillId={skillId}
                reloadToken={versionsToken}
                onRolledBack={() => void refresh(skillId)}
              />
            ),
        },
      ],
      initialTabId: 'details',
      actions,
      actionRows: skill ? [skill] : [],
      editable: true,
      editPermission: 'ai_agents.manage',
      initialEditing: isNew ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: isNew
        ? undefined
        : { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [
    actions,
    form,
    initialEditing,
    isNew,
    onCancel,
    onSave,
    refresh,
    skill,
    skillId,
    versionsToken,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}
