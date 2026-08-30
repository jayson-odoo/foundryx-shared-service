'use client';

/** Trigger-aware draft-run data collector. Manual triggers keep their declared
 * inputs; event triggers receive a typed synthetic event instead of pretending
 * their data belongs under `trigger.input.*`. */
import { useEffect, useMemo, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import type {
  WorkflowManualInput,
  WorkflowNode,
  WorkflowOmnichannelTestSource,
  WorkflowRunRequest,
} from '@/types/workflows';
import { Alert, AlertDescription, AlertIcon } from '@/components/ui/alert';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { SearchSelect } from '@/components/platform/search-select';

export interface RunDialogSideEffects {
  callsAi: boolean;
  sendsMessage: boolean;
  mutatesRedis?: boolean;
  runsCode?: boolean;
  codeRunnerAvailable?: boolean;
}

export interface RunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: WorkflowNode | null | undefined;
  testSources: WorkflowOmnichannelTestSource[];
  testOptionsLoading: boolean;
  testOptionsError: boolean;
  sideEffects: RunDialogSideEffects;
  codeRunnerAvailable?: boolean;
  busy: boolean;
  onRun: (request: WorkflowRunRequest) => void;
}

function sideEffectWarning(sideEffects: RunDialogSideEffects): string | null {
  if (sideEffects.mutatesRedis && sideEffects.runsCode)
    return 'Testing will mutate Redis data and run the configured Code action.';
  if (sideEffects.mutatesRedis) return 'Testing will mutate Redis data.';
  if (sideEffects.runsCode)
    return 'Testing will run the configured Code action.';
  if (sideEffects.callsAi && sideEffects.sendsMessage) {
    return 'Testing will call the configured AI model and send a message through the selected sandbox channel.';
  }
  if (sideEffects.callsAi) return 'Testing will call the configured AI model.';
  if (sideEffects.sendsMessage) {
    return 'Testing will send a message through the selected sandbox channel.';
  }
  return null;
}

export function RunDialog({
  open,
  onOpenChange,
  trigger,
  testSources,
  testOptionsLoading,
  testOptionsError,
  sideEffects,
  codeRunnerAvailable,
  busy,
  onRun,
}: RunDialogProps) {
  const isOmnichannel = trigger?.type === 'omnichannel.message_received';
  const manualInputs = useMemo<WorkflowManualInput[]>(() => {
    const inputs = trigger?.config.inputs;
    return Array.isArray(inputs) ? (inputs as WorkflowManualInput[]) : [];
  }, [trigger]);
  const configuredChannelId =
    isOmnichannel &&
    typeof trigger.config.channelId === 'string' &&
    trigger.config.channelId
      ? trigger.config.channelId
      : '';

  const [values, setValues] = useState<Record<string, string>>({});
  const [channelId, setChannelId] = useState('');
  const [contactId, setContactId] = useState('');
  const [messageText, setMessageText] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingRequest, setPendingRequest] =
    useState<WorkflowRunRequest | null>(null);

  useEffect(() => {
    if (!open) return;
    setValues(Object.fromEntries(manualInputs.map((input) => [input.key, ''])));
    setChannelId(configuredChannelId);
    setContactId('');
    setMessageText('');
  }, [open, manualInputs, configuredChannelId]);

  const eligibleSources = configuredChannelId
    ? testSources.filter((source) => source.channelId === configuredChannelId)
    : testSources;
  const channelOptions = Array.from(
    new Map(
      eligibleSources.map((source) => [
        source.channelId,
        { value: source.channelId, label: source.channelName },
      ]),
    ).values(),
  );
  const contactOptions = eligibleSources
    .filter((source) => source.channelId === channelId)
    .map((source) => ({
      value: source.contactId,
      label: source.contactPhone
        ? `${source.contactName} · ${source.contactPhone}`
        : source.contactName,
    }));
  const validSource = eligibleSources.some(
    (source) =>
      source.channelId === channelId && source.contactId === contactId,
  );
  const noSafeSource =
    !testOptionsLoading && !testOptionsError && eligibleSources.length === 0;
  const warning = sideEffectWarning(sideEffects);
  const runnerUnavailable =
    sideEffects.runsCode && codeRunnerAvailable === false;
  const canSubmitOmnichannel = validSource && messageText.trim().length > 0;

  const submit = () => {
    if (runnerUnavailable) return;
    const request: WorkflowRunRequest = isOmnichannel
      ? {
          inputs: {},
          isTest: true,
          testTrigger: {
            type: 'omnichannel.message_received',
            channelId,
            contactId,
            messageText: messageText.trim(),
          },
        }
      : { inputs: values };
    if (isOmnichannel) {
      if (!canSubmitOmnichannel) return;
    }
    if (sideEffects.mutatesRedis) {
      setPendingRequest(request);
      setConfirmOpen(true);
      return;
    }
    onRun(request);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          aria-describedby={undefined}
          className="max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] max-w-lg overflow-hidden"
        >
          <DialogHeader>
            <DialogTitle>
              {isOmnichannel ? 'Test workflow' : 'Run workflow'}
            </DialogTitle>
          </DialogHeader>
          <DialogBody className="min-h-0 space-y-4 overflow-y-auto">
            {warning && (
              <Alert
                variant="warning"
                appearance="light"
                size="sm"
                data-testid="test-side-effects-warning"
              >
                <AlertIcon>
                  <TriangleAlert />
                </AlertIcon>
                <AlertDescription>{warning}</AlertDescription>
              </Alert>
            )}
            {runnerUnavailable && (
              <Alert
                variant="warning"
                appearance="light"
                size="sm"
                data-testid="code-runner-blocked"
              >
                <AlertIcon>
                  <TriangleAlert />
                </AlertIcon>
                <AlertDescription>
                  Code runner is unavailable. Manual execution is blocked.
                </AlertDescription>
              </Alert>
            )}
            {isOmnichannel ? (
              <>
                {testOptionsError && (
                  <Alert
                    variant="warning"
                    appearance="light"
                    size="sm"
                    data-testid="test-source-warning"
                  >
                    <AlertIcon>
                      <TriangleAlert />
                    </AlertIcon>
                    <AlertDescription>
                      Test data could not be loaded.
                    </AlertDescription>
                  </Alert>
                )}
                {noSafeSource && (
                  <Alert
                    variant="warning"
                    appearance="light"
                    size="sm"
                    data-testid="test-source-warning"
                  >
                    <AlertIcon>
                      <TriangleAlert />
                    </AlertIcon>
                    <AlertDescription>
                      No sandbox contacts are available for this trigger.
                    </AlertDescription>
                  </Alert>
                )}

                <div className="space-y-1.5">
                  <Label>
                    Channel <span className="text-destructive">*</span>
                  </Label>
                  <SearchSelect
                    options={channelOptions}
                    value={channelId || null}
                    onChange={(value) => {
                      setChannelId(value);
                      setContactId('');
                    }}
                    placeholder={
                      testOptionsLoading ? 'Loading…' : 'Choose a channel…'
                    }
                    searchPlaceholder="Search channels…"
                    emptyText="No sandbox channels available."
                    ariaLabel="Channel"
                    disabled={
                      busy ||
                      testOptionsLoading ||
                      testOptionsError ||
                      noSafeSource
                    }
                  />
                </div>

                <div className="space-y-1.5">
                  <Label>
                    Contact <span className="text-destructive">*</span>
                  </Label>
                  <SearchSelect
                    options={contactOptions}
                    value={contactId || null}
                    onChange={setContactId}
                    placeholder="Choose a contact…"
                    searchPlaceholder="Search contacts…"
                    emptyText="No sandbox contacts available."
                    ariaLabel="Contact"
                    disabled={
                      busy ||
                      !channelId ||
                      testOptionsLoading ||
                      testOptionsError ||
                      noSafeSource
                    }
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="workflow-test-message">
                    Message <span className="text-destructive">*</span>
                  </Label>
                  <Textarea
                    id="workflow-test-message"
                    aria-label="Message"
                    className="min-h-28 resize-y"
                    maxLength={4096}
                    value={messageText}
                    onChange={(event) => setMessageText(event.target.value)}
                    disabled={busy || noSafeSource || testOptionsError}
                  />
                </div>
              </>
            ) : (
              <div className="flex flex-col gap-3">
                {manualInputs.map((input) => (
                  <div key={input.key} className="flex flex-col gap-1.5">
                    <Label className="text-xs font-medium">
                      {input.label || input.key}
                    </Label>
                    <Input
                      value={values[input.key] ?? ''}
                      aria-label={input.label || input.key}
                      data-testid={`run-input-${input.key}`}
                      onChange={(event) =>
                        setValues((current) => ({
                          ...current,
                          [input.key]: event.target.value,
                        }))
                      }
                    />
                  </div>
                ))}
              </div>
            )}
          </DialogBody>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={busy || (isOmnichannel && !canSubmitOmnichannel)}
              data-testid="run-dialog-submit"
              onClick={submit}
            >
              {isOmnichannel ? 'Test workflow' : 'Run'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Redis mutation</AlertDialogTitle>
            <AlertDialogDescription>
              This run will change Redis data.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="redis-confirm-cancel">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              data-testid="redis-confirm-run"
              onClick={() => {
                if (pendingRequest) onRun(pendingRequest);
                setPendingRequest(null);
              }}
            >
              Run
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
