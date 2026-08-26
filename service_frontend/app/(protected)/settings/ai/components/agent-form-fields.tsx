'use client';

import type { UseFormReturn } from 'react-hook-form';
import Link from 'next/link';
import { TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { FormRow } from '@/components/platform/resource-form';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
import type { AiAgent, AiConnectionOption, AiModelOption, AiSkillOption } from '@/types/ai';

export interface AgentFormValues {
  name: string;
  description: string;
  connectionId: string;
  model: string;
  temperature: string;
  /** The equipped skill ids (AC-BI-06b) - an agent equips a SET of skills. */
  skillIds: string[];
  isEnabled: boolean;
}

export interface AgentFormFieldsProps {
  form: UseFormReturn<AgentFormValues>;
  editing: boolean;
  agent: AiAgent | null;
  connections: AiConnectionOption[];
  skills: AiSkillOption[];
  models: AiModelOption[];
  modelsLoading: boolean;
  /** False = the live model list failed; the curated static list is showing. */
  modelsLive: boolean;
  /** AC-BI-11 - no LLM connection configured anywhere. */
  hasConnection: boolean;
}

export function AgentFormFields({
  form,
  editing,
  agent,
  connections,
  skills,
  models,
  modelsLoading,
  modelsLive,
  hasConnection,
}: AgentFormFieldsProps) {
  const connectionId = form.watch('connectionId');
  const selectedConnection = connections.find((c) => c.id === connectionId);

  // A pinned model the provider no longer lists must stay selectable - dropping
  // it would silently blank the agent's model on the next save (AC-BI-05).
  const pinned = form.watch('model');
  const modelOptions = models.map((m) => ({ label: m.label, value: m.id }));
  if (pinned && !modelOptions.some((o) => o.value === pinned)) {
    modelOptions.unshift({ label: `${pinned} (not in the provider's list)`, value: pinned });
  }

  return (
    <>
      {!hasConnection && (
        <Alert variant="warning" className="mb-5">
          <TriangleAlert />
          <AlertTitle>No AI connection configured</AlertTitle>
          <AlertDescription>
            <div className="flex flex-col items-start gap-2">
              <span>An agent needs an AI provider connection before it can run.</span>
              <Button variant="outline" size="sm" asChild>
                <Link href="/settings/integrations/new">Add a connection</Link>
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {hasConnection && agent?.warning && (
        <Alert variant="warning" className="mb-5">
          <TriangleAlert />
          <AlertTitle>{agent.warning}</AlertTitle>
        </Alert>
      )}

      <Card>
        <CardContent className="py-1">
          <FormRow label="Name" required={editing}>
            {editing ? (
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <Input placeholder="e.g. Business griller" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              (agent?.name ?? '-')
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
              (agent?.description || '-')
            )}
          </FormRow>

          <FormRow label="Connection" required={editing}>
            {editing ? (
              <FormField
                control={form.control}
                name="connectionId"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <SearchSelect
                        // Only real LLM connections are offered (foolproof-UI).
                        options={connections.map((c) => ({
                          label: c.isPlatform ? `${c.name} (shared default)` : c.name,
                          value: c.id,
                        }))}
                        value={field.value || null}
                        onChange={(value) => {
                          field.onChange(value);
                          // A different provider has a different catalog - the
                          // old pinned model would be invalid.
                          form.setValue('model', '', { shouldDirty: true });
                        }}
                        placeholder="Pick a connection…"
                        ariaLabel="Connection"
                        disabled={!hasConnection}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <div className="flex flex-col">
                <span>{agent?.connectionName ?? '-'}</span>
                {agent?.provider && (
                  <span className="text-xs text-muted-foreground">{agent.provider}</span>
                )}
              </div>
            )}
          </FormRow>

          <FormRow label="Model" required={editing}>
            {editing ? (
              <FormField
                control={form.control}
                name="model"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      {/* Searchable picker, never a free-text input - only
                          offer models that will actually work (AC-BI-05). */}
                      <SearchSelect
                        options={modelOptions}
                        value={field.value || null}
                        onChange={field.onChange}
                        placeholder={
                          modelsLoading
                            ? 'Loading models…'
                            : selectedConnection
                              ? 'Pick a model…'
                              : 'Pick a connection first'
                        }
                        ariaLabel="Model"
                        disabled={!selectedConnection || modelsLoading}
                        emptyText="No models available."
                      />
                    </FormControl>
                    {!modelsLive && modelOptions.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        Showing the built-in list - the provider&apos;s catalog was unavailable.
                      </p>
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              (agent?.model || '-')
            )}
          </FormRow>

          <FormRow label="Temperature">
            {editing ? (
              <FormField
                control={form.control}
                name="temperature"
                render={({ field }) => (
                  <FormItem className="max-w-[8rem]">
                    <FormControl>
                      <Input type="number" min={0} max={2} step={0.1} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              String(agent?.temperature ?? 0)
            )}
          </FormRow>

          <FormRow label="Skills">
            {editing ? (
              <FormField
                control={form.control}
                name="skillIds"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      {/* An agent equips a SET of skills (AC-BI-06b) - search +
                          select-all + pills, never a single SearchSelect. */}
                      <MultiSelect
                        options={skills.map((s) => ({ label: s.name, value: s.id }))}
                        value={field.value ?? []}
                        onChange={field.onChange}
                        placeholder="Equip skills…"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : agent?.skills.length ? (
              <div className="flex flex-wrap gap-1.5">
                {agent.skills.map((s) => (
                  <Badge key={s.id} variant="secondary" appearance="light" size="sm">
                    {s.name}
                  </Badge>
                ))}
              </div>
            ) : (
              '-'
            )}
          </FormRow>

          <FormRow label="Enabled">
            {editing ? (
              <FormField
                control={form.control}
                name="isEnabled"
                render={({ field }) => (
                  <FormItem>
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />
            ) : agent?.isEnabled ? (
              'Yes'
            ) : (
              'No'
            )}
          </FormRow>
        </CardContent>
      </Card>
    </>
  );
}
