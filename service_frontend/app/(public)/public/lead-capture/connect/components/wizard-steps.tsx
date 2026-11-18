'use client';

/**
 * Hosted wizard step bodies (plan 64 L-C, AC-64-12..16/20..24). Each body is
 * one question; data + actions come from `useLeadCaptureWizard` only.
 */
import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, Copy, ExternalLink, Facebook, Loader2, Megaphone } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ClampedText } from '@/components/platform/clamped-text';
import { SearchSelect } from '@/components/platform/search-select';
import type { UseLeadCaptureWizard } from '@/hooks/use-lead-capture-wizard';
import { blockReason, defaultTarget } from '@/lib/lead-capture-wizard';
import { cn } from '@/lib/utils';
import { CREATE_FORM_GUIDE, GOOGLE_TEST_DATA_GUIDE, GuidePlayer } from './guide-player';

interface StepProps {
  wizard: UseLeadCaptureWizard;
}

/** A main action that, when blocked, says why under it and pulses (AC-64-15). */
export function StepAction({
  label,
  onClick,
  reason,
  busy,
}: {
  label: string;
  onClick: () => void;
  reason?: string | null;
  busy?: boolean;
}) {
  return (
    <div className="flex flex-col items-start gap-1.5">
      <Button type="button" onClick={onClick} disabled={Boolean(reason) || busy}>
        {busy ? <Loader2 className="animate-spin" /> : null}
        {label}
      </Button>
      {reason ? <p className="animate-pulse text-xs text-muted-foreground">{reason}</p> : null}
    </div>
  );
}

export function ChannelStep({ wizard }: StepProps) {
  const channels = wizard.context?.channels ?? [];
  if (channels.length === 0) {
    return <p className="text-sm text-muted-foreground">No channel is available right now.</p>;
  }
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {channels.map((channel) => (
        <button
          key={channel.key}
          type="button"
          onClick={() => wizard.chooseChannel(channel.key)}
          className={cn(
            'flex items-center gap-3 rounded-lg border p-3 text-start hover:bg-accent',
            wizard.state.channel === channel.key ? 'border-primary ring-1 ring-primary' : 'border-border',
          )}
        >
          {channel.key === 'facebook' ? (
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[#1877F2] text-white">
              <Facebook className="size-5" aria-hidden />
            </span>
          ) : (
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-foreground">
              <Megaphone className="size-5" aria-hidden />
            </span>
          )}
          <span className="flex min-w-0 flex-col">
            <span className="text-sm font-medium text-foreground">{channel.label}</span>
            <Badge variant="secondary" appearance="light" size="sm" className="mt-1 w-fit">
              {channel.setup === 'automatic' ? 'Automatic' : 'Guided'}
            </Badge>
          </span>
        </button>
      ))}
    </div>
  );
}

export function SignInStep({ wizard }: StepProps) {
  return (
    <Button
      type="button"
      onClick={() => void wizard.signIn()}
      disabled={wizard.busy === 'signin'}
      className="bg-[#1877F2] text-white hover:bg-[#1877F2]/90"
    >
      {wizard.busy === 'signin' ? <Loader2 className="animate-spin" /> : <Facebook aria-hidden />}
      Continue with Facebook
    </Button>
  );
}

export function PageStep({ wizard }: StepProps) {
  const { state } = wizard;
  const bound = wizard.context?.source?.pageId ?? null;
  const options = (state.pages ?? []).map((p) => ({ label: p.name, value: p.id }));
  const connected = Boolean(state.sourceId);
  return (
    <div className="flex flex-col gap-3">
      <SearchSelect
        options={options}
        value={state.pageId}
        onChange={(v) => wizard.pickPage(v)}
        placeholder="Pick a Page"
        searchPlaceholder="Search Pages"
        ariaLabel="Facebook Page"
        disabled={connected || Boolean(bound)}
        className="w-full sm:max-w-sm"
      />
      {connected ? null : (
        <StepAction
          label="Connect Page"
          onClick={() => void wizard.connectPage()}
          reason={blockReason('page', state)}
          busy={wizard.busy === 'connect'}
        />
      )}
    </div>
  );
}

export function FormsStep({ wizard }: StepProps) {
  const { state, forms } = wizard;
  if (!forms) {
    return (
      <StepAction label="Check again" onClick={() => void wizard.reloadForms()} busy={wizard.busy === 'forms'} />
    );
  }
  if (forms.data.length === 0) {
    return (
      <div className="flex flex-col gap-3">
        <p className="flex items-start gap-2 text-sm text-foreground">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          This Page has no lead forms yet.
        </p>
        <GuidePlayer frames={CREATE_FORM_GUIDE} />
        <div className="flex flex-wrap items-center gap-3">
          <StepAction label="Check again" onClick={() => void wizard.reloadForms()} busy={wizard.busy === 'forms'} />
          <Button variant="outline" asChild>
            <a href="https://business.facebook.com/latest/instant_forms" target="_blank" rel="noopener noreferrer">
              <ExternalLink aria-hidden />
              Open Instant Forms
            </a>
          </Button>
        </div>
      </div>
    );
  }
  const mode = state.formsMode ?? 'all';
  const toggle = (id: string, on: boolean) =>
    wizard.setFormsChoice('pick', on ? [...state.formIds, id] : state.formIds.filter((f) => f !== id));
  return (
    <div className="flex flex-col gap-3">
      {forms.tosAccepted === false ? (
        <p className="flex items-start gap-2 text-sm text-foreground">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>
            Leads from real ads need this Page to accept the Lead Ads Terms.{' '}
            <a
              className="text-primary underline"
              href="https://www.facebook.com/ads/leadgen/tos"
              target="_blank"
              rel="noopener noreferrer"
            >
              Open the terms
            </a>
          </span>
        </p>
      ) : null}
      <RadioGroup
        value={mode}
        onValueChange={(v) => wizard.setFormsChoice(v === 'pick' ? 'pick' : 'all', state.formIds)}
        className="gap-2"
      >
        <label className="flex items-center gap-2 text-sm">
          <RadioGroupItem value="all" />
          All forms, including new ones
        </label>
        <label className="flex items-center gap-2 text-sm">
          <RadioGroupItem value="pick" />
          Only the forms I tick
        </label>
      </RadioGroup>
      {mode === 'pick' ? (
        <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto rounded-md border border-border p-2">
          {forms.data.map((form) => (
            <li key={form.id}>
              <label className="flex min-w-0 items-center gap-2 rounded px-1 py-1.5 text-sm hover:bg-accent">
                <Checkbox
                  checked={state.formIds.includes(form.id)}
                  onCheckedChange={(v) => toggle(form.id, v === true)}
                />
                <ClampedText text={form.name ?? form.id} lines={1} className="min-w-0" />
              </label>
            </li>
          ))}
        </ul>
      ) : null}
      <StepAction
        label="Save forms"
        onClick={() => void wizard.saveForms()}
        reason={state.formsSaved ? null : blockReason('forms', state)}
        busy={wizard.busy === 'forms'}
      />
    </div>
  );
}

function usableForms(wizard: UseLeadCaptureWizard) {
  const all = wizard.forms?.data ?? [];
  return wizard.state.formsMode === 'pick' ? all.filter((f) => wizard.state.formIds.includes(f.id)) : all;
}

export function FieldsStep({ wizard }: StepProps) {
  const { questions, fields } = wizard;
  const forms = usableForms(wizard);
  const [map, setMap] = useState<Record<string, string | null>>({});
  const saved = useMemo(
    () => (wizard.mapFormId ? (wizard.source?.fieldMap?.[wizard.mapFormId] ?? {}) : {}),
    [wizard.source, wizard.mapFormId],
  );

  useEffect(() => {
    if (!questions) return;
    const next: Record<string, string | null> = {};
    for (const q of questions.data) next[q.key] = saved[q.key] ?? defaultTarget(q, fields);
    setMap(next);
  }, [fields, questions, saved]);

  const targetOptions = fields.map((f) => ({ label: f.label || f.key, value: f.key }));
  return (
    <div className="flex flex-col gap-3">
      {forms.length > 1 ? (
        <SearchSelect
          options={forms.map((f) => ({ label: f.name ?? f.id, value: f.id }))}
          value={wizard.mapFormId}
          onChange={(v) => void wizard.chooseMapForm(v)}
          searchPlaceholder="Search forms"
          ariaLabel="Lead form"
          className="w-full sm:max-w-sm"
        />
      ) : null}
      <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
        {(questions?.data ?? []).map((q) => (
          <li key={q.key} className="flex flex-col gap-2 p-2.5 sm:flex-row sm:items-center sm:justify-between">
            <ClampedText text={q.label} lines={2} className="min-w-0 text-sm text-foreground sm:max-w-[45%]" />
            <SearchSelect
              options={targetOptions}
              value={map[q.key] ?? null}
              onChange={(v) => setMap((m) => ({ ...m, [q.key]: v }))}
              placeholder="Lead field"
              searchPlaceholder="Search lead fields"
              ariaLabel={`Lead field for ${q.label}`}
              className="w-full sm:w-56"
            />
          </li>
        ))}
      </ul>
      <StepAction
        label="Save fields"
        onClick={() => void wizard.saveFieldMap(map)}
        busy={wizard.busy === 'fields' || wizard.busy === 'questions'}
      />
    </div>
  );
}

function CopyRow({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1.5">
        <ClampedText text={value} lines={1} className="min-w-0 flex-1 font-mono text-sm text-foreground" />
        <Button type="button" variant="outline" size="sm" onClick={onCopy} aria-label={`Copy ${label}`}>
          {copied ? <Check className="text-success" aria-hidden /> : <Copy aria-hidden />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
    </div>
  );
}

/** Google Ads: the inbound URL + key, each copied once (AC-64-40). */
export function CopyStep({ wizard }: StepProps) {
  const { state } = wizard;
  if (!state.guided) {
    return (
      <StepAction label="Show URL and key" onClick={() => void wizard.showGuided()} busy={wizard.busy === 'copy'} />
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <CopyRow
        label="Webhook URL"
        value={state.guided.url}
        copied={state.copiedUrl}
        onCopy={() => void wizard.copyGuided('url')}
      />
      <CopyRow label="Key" value={state.guided.key} copied={state.copiedKey} onCopy={() => void wizard.copyGuided('key')} />
      {state.copyConfirmed ? null : (
        <StepAction label="Continue" onClick={() => void wizard.confirmCopy()} reason={blockReason('copy', state)} />
      )}
    </div>
  );
}

function GoogleTestStep({ wizard }: StepProps) {
  return (
    <div className="flex flex-col gap-3">
      <GuidePlayer frames={GOOGLE_TEST_DATA_GUIDE} />
      {wizard.testWaiting ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Waiting for the test data
        </p>
      ) : (
        <StepAction
          label="Check again"
          onClick={() => void wizard.waitForGoogleTest()}
          busy={wizard.busy === 'test'}
        />
      )}
    </div>
  );
}

export function TestStep({ wizard }: StepProps) {
  const forms = usableForms(wizard);
  if (wizard.state.testPassed) {
    return null;
  }
  if (wizard.state.channel === 'google') {
    return <GoogleTestStep wizard={wizard} />;
  }
  return (
    <div className="flex flex-col gap-3">
      {forms.length > 1 ? (
        <SearchSelect
          options={forms.map((f) => ({ label: f.name ?? f.id, value: f.id }))}
          value={wizard.testFormId}
          onChange={(v) => wizard.setTestFormId(v)}
          searchPlaceholder="Search forms"
          ariaLabel="Test form"
          className="w-full sm:max-w-sm"
        />
      ) : null}
      {wizard.testWaiting ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Waiting for the test lead
        </p>
      ) : (
        <StepAction
          label="Send test lead"
          onClick={() => void wizard.sendTestLead()}
          reason={wizard.testFormId ? null : 'Pick a form.'}
          busy={wizard.busy === 'test'}
        />
      )}
    </div>
  );
}
