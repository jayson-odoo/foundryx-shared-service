'use client';

/**
 * useGrill (Phase B-i slice 3, AC-BI-29) — the Grill tab's data hook. UI →
 * THIS hook → grill-service → api-client (the enforced layering; a component
 * never calls the service directly).
 *
 * Owns: the transcript + coverage + readiness, the in-flight turn indicator, and
 * Generate (which returns the refreshed BR detail so the Details tab can refresh
 * via `onGenerated`). The human always ends the grill — Generate is always
 * enabled (AC-BI-22).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { grillService } from '@/services/grill-service';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import type { GrillField, GrillMessage } from '@/types/grill';

export interface UseGrillOptions {
  /** Called with the refreshed BR after a successful Generate so the Details
   * tab reflects the new answers. */
  onGenerated?: (br: BusinessRequirementDetail) => void;
  /** When true, fire the opening turn EXACTLY ONCE on a fresh BR with an empty
   * transcript once the grill is ready (AC-BI-29b). Pass `true` only when the BR
   * has ≥1 linked idea; a BR that already has messages never re-opens. */
  autoOpen?: boolean;
}

export interface UseGrillResult {
  isLoading: boolean;
  ready: boolean;
  warning: string | null;
  agentName: string;
  fields: GrillField[];
  messages: GrillMessage[];
  coveredFields: string[];
  /** The running per-field captured summary (AC-BI-24c) — values understood so
   * far, keyed by field key; updates each turn. */
  capturedSummary: Record<string, string>;
  /** Fields with no coverage yet (for the "missing: …" indicator). */
  missingFields: GrillField[];
  sending: boolean;
  generating: boolean;
  error: string | null;
  /** Field errors surfaced when a Generate needs human review (AC-BI-25). */
  fieldErrors: Record<string, string>;
  sendTurn: (message: string) => Promise<void>;
  generate: () => Promise<void>;
  reload: () => Promise<void>;
}

export function useGrill(brId: string, options: UseGrillOptions = {}): UseGrillResult {
  const { onGenerated, autoOpen = false } = options;
  const [isLoading, setIsLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);
  const [agentName, setAgentName] = useState('');
  const [fields, setFields] = useState<GrillField[]>([]);
  const [messages, setMessages] = useState<GrillMessage[]>([]);
  const [coveredFields, setCoveredFields] = useState<string[]>([]);
  const [capturedSummary, setCapturedSummary] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    setIsLoading(true);
    try {
      const s = await grillService.state(brId);
      setReady(s.ready);
      setWarning(s.warning);
      setAgentName(s.agentName);
      setFields(s.fields);
      setMessages(s.messages);
      setCoveredFields(s.coveredFields);
      setCapturedSummary(s.capturedSummary ?? {});
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the grill.');
    } finally {
      setIsLoading(false);
    }
  }, [brId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Auto-open on a fresh promoted BR (AC-BI-29b): fire the opening turn EXACTLY
  // ONCE once loaded + ready + the transcript is still empty. The guard tracks
  // the BR the open was fired for (not a boolean) so it survives a re-render /
  // StrictMode double-invoke AND re-arms cleanly on record-nav to another BR — a
  // double-fire would mean two opening messages + a wasted LLM call.
  const openedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!autoOpen || isLoading || !ready) return;
    if (messages.length > 0) return;
    if (openedForRef.current === brId) return;
    openedForRef.current = brId;
    void (async () => {
      setSending(true);
      setError(null);
      try {
        await grillService.open(brId);
        const s = await grillService.state(brId);
        setMessages(s.messages);
        setCoveredFields(s.coveredFields);
        setCapturedSummary(s.capturedSummary ?? {});
      } catch (e) {
        setError(e instanceof Error ? e.message : 'The grill could not start.');
      } finally {
        setSending(false);
      }
    })();
  }, [autoOpen, isLoading, ready, messages.length, brId]);

  // `generatingRef` lets `sendTurn` skip an auto-fire while a Generate is already
  // in flight WITHOUT taking `generate` as a dependency (which would re-create
  // `sendTurn` each render) — the prompt-to-generate path fires at most once.
  const generatingRef = useRef(false);

  const generate = useCallback(async () => {
    if (generatingRef.current) return;
    generatingRef.current = true;
    setGenerating(true);
    setError(null);
    setFieldErrors({});
    try {
      const result = await grillService.generate(brId);
      if (result.status === 'needs_review') {
        setFieldErrors(result.fieldErrors);
        setError('The generated requirement needs review — some fields could not be filled.');
        return;
      }
      if (result.br) onGenerated?.(result.br);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Generate failed.');
    } finally {
      generatingRef.current = false;
      setGenerating(false);
    }
  }, [brId, onGenerated]);

  const sendTurn = useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || sending) return;
      setSending(true);
      setError(null);
      // Optimistically show the human turn while the model thinks.
      const optimistic: GrillMessage = {
        id: `pending-${Date.now()}`,
        role: 'user',
        content: text,
        coveredFields: [],
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);
      let signalled = false;
      try {
        const turn = await grillService.turn(brId, text);
        // Re-sync from the server so the transcript is authoritative (no
        // half-written turn on the client either, AC-BI-23).
        const s = await grillService.state(brId);
        setMessages(s.messages);
        setCoveredFields(turn.coveredFields);
        setCapturedSummary(turn.capturedSummary ?? {});
        signalled = turn.generateSignal === true;
      } catch (e) {
        // Roll back the optimistic turn — keep the transcript consistent.
        setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
        setError(e instanceof Error ? e.message : 'The grill could not respond.');
      } finally {
        setSending(false);
      }
      // Prompt-to-generate (AC-BI-24c): the MODEL signalled finalize intent → the
      // APP fires the existing Generate call (once per intent — a normal turn with
      // generateSignal=false does nothing new; `generate` guards against overlap).
      if (signalled) void generate();
    },
    [brId, sending, generate],
  );

  const missingFields = useMemo(
    () => fields.filter((f) => !coveredFields.includes(f.key)),
    [fields, coveredFields],
  );

  return {
    isLoading,
    ready,
    warning,
    agentName,
    fields,
    messages,
    coveredFields,
    capturedSummary,
    missingFields,
    sending,
    generating,
    error,
    fieldErrors,
    sendTurn,
    generate,
    reload,
  };
}
