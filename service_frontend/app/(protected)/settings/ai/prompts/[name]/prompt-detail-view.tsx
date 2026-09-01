'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, LoaderCircleIcon, Rocket, SquarePen } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { useDatetime } from '@/hooks/use-datetime';
import { aiPromptsService } from '@/services/ai-prompts-service';
import type { AiPromptDetail, AiPromptVersion } from '@/types/ai-prompt';
import { AI_PROMPTS_PATH } from '../paths';
import { PublishDialog } from '../components/publish-dialog';
import { VarChips } from '../components/var-chips';

const PRESS = 'transition-transform duration-100 active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100';

export interface PromptDetailViewProps {
  name: string;
}

export function PromptDetailView({ name }: PromptDetailViewProps) {
  const [prompt, setPrompt] = useState<AiPromptDetail | null | undefined>(undefined);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [commitMessage, setCommitMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [publishTarget, setPublishTarget] = useState<AiPromptVersion | null>(null);
  const [publishing, setPublishing] = useState(false);
  const { formatDateTime } = useDatetime();

  useEffect(() => {
    let cancelled = false;
    aiPromptsService.getPrompt(name).then((loaded) => {
      if (cancelled) return;
      setPrompt(loaded);
      const initial = loaded?.labels.production ?? loaded?.versions[0]?.version ?? null;
      const initialVersion = loaded?.versions.find((v) => v.version === initial);
      setSelectedVersionId(initialVersion?.id ?? loaded?.versions[0]?.id ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [name]);

  const selected = useMemo(
    () => prompt?.versions.find((v) => v.id === selectedVersionId) ?? prompt?.versions[0] ?? null,
    [prompt, selectedVersionId],
  );

  if (prompt === undefined) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (prompt === null) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-sm font-medium">Prompt not found.</p>
        <Button variant="outline" size="sm" asChild>
          <Link href={AI_PROMPTS_PATH}>Back to prompts</Link>
        </Button>
      </div>
    );
  }

  const startNewVersion = () => {
    setDraft(selected?.template ?? '');
    setCommitMessage('');
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setDraft('');
    setCommitMessage('');
  };

  const saveVersion = async () => {
    if (!commitMessage.trim()) {
      toast.error('Commit message is required.');
      return;
    }
    setSaving(true);
    try {
      const created = await aiPromptsService.createVersion(name, {
        template: draft,
        commitMessage: commitMessage.trim(),
      });
      setPrompt((p) => (p ? { ...p, versions: [created, ...p.versions] } : p));
      setSelectedVersionId(created.id);
      setEditing(false);
      toast.success(`Saved v${created.version}.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the new version.');
    } finally {
      setSaving(false);
    }
  };

  const confirmPublish = async () => {
    if (!publishTarget) return;
    setPublishing(true);
    try {
      const updated = await aiPromptsService.publishVersion(name, {
        versionId: publishTarget.id,
        label: 'production',
      });
      setPrompt(updated);
      toast.success(`v${publishTarget.version} is now production.`);
      setPublishTarget(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not publish.');
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link
          href={AI_PROMPTS_PATH}
          className="mb-1 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> All prompts
        </Link>
        <h1 className="font-mono text-xl font-semibold tracking-[-0.02em] text-foreground">{name}</h1>
      </div>

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        {/* Version history */}
        <div className="flex flex-col gap-2">
          <p className="px-1 text-[0.72rem] font-medium uppercase tracking-[0.05em] text-muted-foreground">
            Version history
          </p>
          <div className="divide-y divide-border rounded-lg border border-border">
            {prompt.versions.map((v) => {
              const isSelected = v.id === selected?.id;
              const isProduction = v.labels.includes('production');
              return (
                <button
                  type="button"
                  key={v.id}
                  data-testid={`version-row-${v.version}`}
                  disabled={editing}
                  onClick={() => setSelectedVersionId(v.id)}
                  className={cn(
                    'flex w-full flex-col gap-1 px-3 py-2.5 text-left transition-colors duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-60',
                    isSelected ? 'bg-muted/60' : 'hover:bg-muted/40',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium tracking-[-0.01em] text-foreground">
                      v{v.version}
                    </span>
                    <div className="flex gap-1">
                      {isProduction && (
                        <Badge variant="success" appearance="light" size="sm">
                          Production
                        </Badge>
                      )}
                      {v.labels.includes('staging') && (
                        <Badge variant="warning" appearance="light" size="sm">
                          Staging
                        </Badge>
                      )}
                    </div>
                  </div>
                  <p className="truncate text-xs text-muted-foreground" title={v.commitMessage ?? ''}>
                    {v.commitMessage || <span className="italic">(no commit message)</span>}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {v.createdByName ?? 'unknown'}
                    {v.createdAt ? ` · ${formatDateTime(v.createdAt)}` : ''}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        {/* Template well */}
        <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[0.72rem] font-medium uppercase tracking-[0.05em] text-muted-foreground">
              {editing ? `New version (base: v${selected?.version})` : `Template · v${selected?.version}`}
            </p>
            {!editing && (
              <div className="flex gap-2">
                {selected && !selected.labels.includes('production') && (
                  <Button
                    type="button"
                    size="sm"
                    className={PRESS}
                    onClick={() => setPublishTarget(selected)}
                    data-testid="publish-button"
                  >
                    <Rocket className="size-3.5" /> Publish
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className={PRESS}
                  onClick={startNewVersion}
                  data-testid="new-version-button"
                >
                  <SquarePen className="size-3.5" /> New version
                </Button>
              </div>
            )}
          </div>

          {editing ? (
            <div className="flex flex-col gap-3">
              <Textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={16}
                spellCheck={false}
                className="font-mono text-xs"
                data-testid="prompt-editor"
              />
              <VarChips template={draft} variables={prompt.variables} />
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <div className="flex-1 space-y-1">
                  <Label htmlFor="prompt-commit-message" className="text-xs text-muted-foreground">
                    Commit message
                  </Label>
                  <Input
                    id="prompt-commit-message"
                    value={commitMessage}
                    onChange={(e) => setCommitMessage(e.target.value)}
                    placeholder="What changed and why?"
                    data-testid="commit-message"
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className={PRESS}
                    disabled={saving}
                    onClick={cancelEdit}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    className={PRESS}
                    disabled={saving || !commitMessage.trim()}
                    onClick={() => void saveVersion()}
                    data-testid="save-version"
                  >
                    {saving ? <LoaderCircleIcon className="size-4 animate-spin" /> : 'Save version'}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 font-mono text-xs text-foreground">
                {selected?.template || '-'}
              </pre>
              <VarChips template={selected?.template ?? ''} variables={prompt.variables} />
            </div>
          )}
        </div>
      </div>

      <PublishDialog
        open={publishTarget != null}
        onOpenChange={(open) => !open && setPublishTarget(null)}
        name={name}
        version={publishTarget?.version ?? null}
        pending={publishing}
        onConfirm={() => void confirmPublish()}
      />
    </div>
  );
}
