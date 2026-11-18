'use client';

/**
 * Hosted Lead Capture wizard state (plan 64 L-C). Opens the session from the
 * URL fragment ONCE (the secret is single-use; it is removed from the address
 * bar at once and the scoped token is kept in this tab's sessionStorage so a
 * reload keeps going), then drives each step through
 * `leadCaptureWizardService` and the pure step engine.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { copyText } from '@/lib/clipboard';
import { launchMetaOAuth } from '@/lib/embedded-signup';
import { postToOpener } from '@/lib/lead-capture-post-message';
import {
  INITIAL_WIZARD_STATE,
  autoPage,
  errorScreenFor,
  isLeadsAccessMessage,
  withForms,
  type FormsChoice,
  type WizardErrorScreen,
  type WizardState,
} from '@/lib/lead-capture-wizard';
import { leadCaptureWizardService as svc } from '@/services/lead-capture-wizard-service';
import type {
  WizardConsumerField,
  WizardContext,
  WizardDone,
  WizardFormList,
  WizardQuestionList,
  WizardSource,
  WizardTestLead,
} from '@/types/lead-capture-wizard';

const STORAGE_KEY = 'lead-capture-wizard';
const POLL_MS = 3000;
const POLL_LIMIT = 40; // two minutes
/** Google sends "Send test data" when the person presses it in Google Ads:
 * wait longer, then offer Check again. */
const GOOGLE_POLL_LIMIT = 200; // ten minutes

interface StoredGrant {
  token: string;
  expiresAt: string;
}

function readStored(): StoredGrant | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const grant = JSON.parse(raw) as StoredGrant;
    return Date.parse(grant.expiresAt) > Date.now() ? grant : null;
  } catch {
    return null;
  }
}

function writeStored(grant: StoredGrant | null): void {
  try {
    if (grant) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(grant));
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage blocked: the wizard still works until a reload */
  }
}

export type WizardPhase = 'opening' | 'ready' | 'expired' | 'done';

export interface WizardProblem {
  screen: WizardErrorScreen | 'leads-access' | 'no-pages';
  message: string;
}

export interface UseLeadCaptureWizard {
  phase: WizardPhase;
  context: WizardContext | null;
  state: WizardState;
  busy: string | null;
  problem: WizardProblem | null;
  forms: WizardFormList | null;
  fields: WizardConsumerField[];
  questions: WizardQuestionList | null;
  mapFormId: string | null;
  testFormId: string | null;
  testWaiting: boolean;
  done: WizardDone | null;
  /** The source as the server last answered (saved field maps). */
  source: WizardSource | null;
  chooseChannel: (key: string) => void;
  /** Google: make (or re-key) this session's source and show its URL + key. */
  showGuided: () => Promise<void>;
  copyGuided: (which: 'url' | 'key') => Promise<void>;
  /** Google: URL + key copied; wait for Google's test data. */
  confirmCopy: () => Promise<void>;
  /** Google: wait again after the wait ran out. */
  waitForGoogleTest: () => Promise<void>;
  signIn: () => Promise<void>;
  pickPage: (pageId: string) => void;
  connectPage: () => Promise<void>;
  setFormsChoice: (mode: FormsChoice, ids: string[]) => void;
  saveForms: () => Promise<void>;
  reloadForms: () => Promise<void>;
  chooseMapForm: (formId: string) => Promise<void>;
  saveFieldMap: (map: Record<string, string | null>) => Promise<void>;
  setTestFormId: (formId: string) => void;
  sendTestLead: () => Promise<void>;
  finish: () => Promise<void>;
  close: () => void;
  dismissProblem: () => void;
}

function problemOf(error: unknown): WizardProblem {
  if (error instanceof ApiError) {
    return { screen: errorScreenFor(error.code), message: error.message };
  }
  return { screen: 'generic', message: error instanceof Error ? error.message : 'Something went wrong. Try again.' };
}

export function useLeadCaptureWizard(): UseLeadCaptureWizard {
  const [phase, setPhase] = useState<WizardPhase>('opening');
  const [token, setToken] = useState<string | null>(null);
  const [context, setContext] = useState<WizardContext | null>(null);
  const [state, setState] = useState<WizardState>(INITIAL_WIZARD_STATE);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<WizardProblem | null>(null);
  const [forms, setForms] = useState<WizardFormList | null>(null);
  const [fields, setFields] = useState<WizardConsumerField[]>([]);
  const [questions, setQuestions] = useState<WizardQuestionList | null>(null);
  const [mapFormId, setMapFormId] = useState<string | null>(null);
  const [testFormId, setTestFormId] = useState<string | null>(null);
  const [testWaiting, setTestWaiting] = useState(false);
  const [done, setDone] = useState<WizardDone | null>(null);
  const opened = useRef(false);
  /** Google: the newest test lead when the URL + key were shown. A test lead
   * Google sends after that (even before Continue) passes the Test step. */
  const googleBaseline = useRef<string | null | undefined>(undefined);
  const pollTimer = useRef<number | null>(null);
  /** False once the wizard closed, unmounted or its session ended: a poll
   * in flight checks it after every await and stops. */
  const polling = useRef(false);
  /** The source as the server last answered (its saved field maps). */
  const [source, setSource] = useState<WizardSource | null>(null);

  // ── open the session once ────────────────────────────────────────────────
  useEffect(() => {
    if (opened.current) return;
    opened.current = true;
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const secret = hash.get('s');
    if (secret) {
      // The secret is single-use: off the address bar (and history) at once.
      window.history.replaceState(null, '', window.location.pathname);
    }
    const open = async () => {
      try {
        let grant = secret ? null : readStored();
        if (secret) {
          const g = await svc.redeem(secret);
          grant = { token: g.accessToken, expiresAt: g.expiresAt };
          writeStored(grant);
        }
        if (!grant) {
          setPhase('expired');
          return;
        }
        const ctx = await svc.context(grant.token);
        setToken(grant.token);
        setContext(ctx);
        if (ctx.source) {
          setSource(ctx.source);
          // Reopened for an existing source (Reconnect / Map fields).
          setState((s) => ({
            ...s,
            channel: ctx.source?.platform ?? 'facebook',
            sourceId: ctx.source?.platform === 'google' ? (ctx.source?.id ?? null) : s.sourceId,
          }));
        }
        setPhase('ready');
      } catch {
        writeStored(null);
        setPhase('expired');
      }
    };
    void open();
  }, []);

  useEffect(
    () => () => {
      polling.current = false;
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
    },
    [],
  );

  const run = useCallback(
    async (label: string, fn: (t: string) => Promise<void>) => {
      if (!token) return;
      setBusy(label);
      setProblem(null);
      try {
        await fn(token);
      } catch (error) {
        const p = problemOf(error);
        if (p.screen === 'expired') {
          polling.current = false;
          writeStored(null);
          setPhase('expired');
        }
        setProblem(p);
      } finally {
        setBusy(null);
      }
    },
    [token],
  );

  // ── steps ────────────────────────────────────────────────────────────────
  const showGuided = useCallback(
    () =>
      run('copy', async (t) => {
        const made = await svc.googleSource(t);
        try {
          googleBaseline.current = (await svc.lastTestLead(t, made.source.id)).leadId;
        } catch {
          googleBaseline.current = undefined; // read again at Continue; never blocks the URL + key
        }
        setSource(made.source);
        setState((s) => ({
          ...s,
          sourceId: made.source.id,
          guided: { url: made.url, key: made.key },
          copiedUrl: false,
          copiedKey: false,
        }));
      }),
    [run],
  );

  const chooseChannel = useCallback(
    (key: string) => {
      setState((s) => ({ ...s, channel: key }));
      if (key === 'google' && !state.guided) void showGuided();
    },
    [showGuided, state.guided],
  );

  const copyGuided = useCallback(
    async (which: 'url' | 'key') => {
      const value = which === 'url' ? state.guided?.url : state.guided?.key;
      if (!value) return;
      if (!(await copyText(value))) {
        setProblem({ screen: 'generic', message: 'Copy did not work. Select the text and copy it.' });
        return;
      }
      setState((s) => (which === 'url' ? { ...s, copiedUrl: true } : { ...s, copiedKey: true }));
    },
    [state.guided],
  );

  const signIn = useCallback(
    () =>
      run('signin', async (t) => {
        const login = context?.login;
        if (!login?.available) throw new Error('Facebook is not available right now.');
        let code = 'simulated';
        let redirectUri: string | undefined;
        if (!login.simulated) {
          const result = await launchMetaOAuth({
            appId: login.appId ?? '',
            configId: login.configId ?? '',
            graphVersion: login.graphVersion,
            windowName: 'lead_capture_login',
          });
          code = result.code;
          redirectUri = result.redirectUri;
        }
        const pages = await svc.login(t, code, redirectUri);
        if (pages.length === 0) {
          setProblem({ screen: 'no-pages', message: 'No Page was shared. You need to be an admin of the Page that runs the ads.' });
          return;
        }
        const bound = context?.source?.pageId ?? null;
        const pick = bound && pages.some((p) => p.id === bound) ? bound : autoPage(pages);
        setState((s) => ({ ...s, signedIn: true, pages, pageId: pick ?? s.pageId }));
      }),
    [context, run],
  );

  const pickPage = useCallback((pageId: string) => {
    setState((s) => ({ ...s, pageId }));
  }, []);

  const loadForms = useCallback(async (t: string, sourceId: string) => {
    try {
      const list = await svc.forms(t, sourceId);
      setForms(list);
      setState((s) => ({
        ...s,
        formsMode: (list.formsMode === 'pick' ? 'pick' : 'all') as FormsChoice,
        formIds: list.formIds,
      }));
      const first = list.data[0]?.id ?? null;
      setTestFormId((cur) => cur ?? first);
    } catch (error) {
      setForms(null);
      if (error instanceof ApiError && isLeadsAccessMessage(error.message)) {
        setProblem({ screen: 'leads-access', message: error.message });
        return;
      }
      throw error;
    }
  }, []);

  const connectPage = useCallback(
    () =>
      run('connect', async (t) => {
        if (!state.pageId) return;
        const connected: WizardSource = await svc.connect(t, state.pageId);
        setSource(connected);
        setState((s) => ({ ...s, sourceId: connected.id }));
        await loadForms(t, connected.id);
      }),
    [loadForms, run, state.pageId],
  );

  const reloadForms = useCallback(
    () =>
      run('forms', async (t) => {
        if (state.sourceId) await loadForms(t, state.sourceId);
      }),
    [loadForms, run, state.sourceId],
  );

  const setFormsChoice = useCallback((mode: FormsChoice, ids: string[]) => {
    setState((s) => withForms({ ...s, formsSaved: false }, mode, ids));
  }, []);

  const chooseMapForm = useCallback(
    (formId: string) =>
      run('questions', async (t) => {
        if (!state.sourceId) return;
        // Form and questions change together, only once the questions arrived.
        const list = await svc.questions(t, state.sourceId, formId);
        setQuestions(list);
        setMapFormId(formId);
      }),
    [run, state.sourceId],
  );

  const saveForms = useCallback(
    () =>
      run('forms', async (t) => {
        if (!state.sourceId || !state.formsMode) return;
        setSource(await svc.saveForms(t, state.sourceId, state.formsMode, state.formIds));
        const [consumer] = await Promise.all([svc.fields(t)]);
        setFields(consumer);
        const usable = state.formsMode === 'pick' ? state.formIds : (forms?.data.map((f) => f.id) ?? []);
        const first = usable[0] ?? null;
        setTestFormId(first);
        if (first) {
          setQuestions(await svc.questions(t, state.sourceId, first));
          setMapFormId(first);
        }
        setState((s) => ({ ...s, formsSaved: true }));
      }),
    [forms, run, state.formIds, state.formsMode, state.sourceId],
  );

  const saveFieldMap = useCallback(
    (map: Record<string, string | null>) =>
      run('fields', async (t) => {
        if (!state.sourceId || !mapFormId) {
          setState((s) => ({ ...s, fieldsSaved: true }));
          return;
        }
        setSource(await svc.saveFieldMap(t, state.sourceId, mapFormId, map));
        setState((s) => ({ ...s, fieldsSaved: true }));
      }),
    [mapFormId, run, state.sourceId],
  );

  /** What a newly arrived test lead does: Facebook = Test passed; Google =
   * Test passed AND the Fields step opens on that lead's form. */
  const arrive = useCallback(async (t: string, sourceId: string, latest: WizardTestLead) => {
    if (state.channel === 'google' && latest.formId) {
      const [consumer, list] = await Promise.all([svc.fields(t), svc.questions(t, sourceId, latest.formId)]);
      setFields(consumer);
      setQuestions(list);
      setMapFormId(latest.formId);
      setTestFormId(latest.formId);
    }
    setState((s) => ({ ...s, testPassed: true }));
  }, [state.channel]);

  /** Wait for a test lead NEWER than `baseline` (a reconnected source is
   * LIVE already, so its status proves nothing). */
  const poll = useCallback((t: string, sourceId: string, baseline: string | null, left: number) => {
    pollTimer.current = window.setTimeout(async () => {
      if (!polling.current) return;
      try {
        const latest = await svc.lastTestLead(t, sourceId);
        if (!polling.current) return;
        if (latest.leadId && latest.leadId !== baseline) {
          polling.current = false;
          setTestWaiting(false);
          await arrive(t, sourceId, latest);
          return;
        }
      } catch {
        if (!polling.current) return;
      }
      if (left <= 1) {
        polling.current = false;
        setTestWaiting(false);
        setProblem({ screen: 'generic', message: 'The test lead has not arrived yet. Send it again.' });
        return;
      }
      poll(t, sourceId, baseline, left - 1);
    }, POLL_MS);
  }, [arrive]);

  const waitForGoogleTest = useCallback(
    () =>
      run('test', async (t) => {
        if (!state.sourceId) return;
        const baseline =
          googleBaseline.current !== undefined
            ? googleBaseline.current
            : (await svc.lastTestLead(t, state.sourceId)).leadId;
        polling.current = true;
        setTestWaiting(true);
        poll(t, state.sourceId, baseline, GOOGLE_POLL_LIMIT);
      }),
    [poll, run, state.sourceId],
  );

  const confirmCopy = useCallback(async () => {
    setState((s) => ({ ...s, copyConfirmed: true }));
    await waitForGoogleTest();
  }, [waitForGoogleTest]);

  const sendTestLead = useCallback(
    () =>
      run('test', async (t) => {
        if (!state.sourceId || !testFormId) return;
        const baseline = (await svc.lastTestLead(t, state.sourceId)).leadId;
        await svc.sendTestLead(t, state.sourceId, testFormId);
        const latest = await svc.lastTestLead(t, state.sourceId);
        if (latest.leadId && latest.leadId !== baseline) {
          await arrive(t, state.sourceId, latest);
          return;
        }
        polling.current = true;
        setTestWaiting(true);
        poll(t, state.sourceId, baseline, POLL_LIMIT);
      }),
    [arrive, poll, run, state.sourceId, testFormId],
  );

  const returnOrigin = context?.returnOrigin ?? null;

  const finish = useCallback(
    () =>
      run('finish', async (t) => {
        const summary = await svc.finish(t);
        setDone(summary);
        setPhase('done');
      }),
    [run],
  );

  const close = useCallback(() => {
    polling.current = false;
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    const sourceId = done?.source.id ?? state.sourceId ?? undefined;
    const message = done
      ? ({ type: 'lead-capture:done', sourceId: done.source.id } as const)
      : ({ type: 'lead-capture:closed', ...(sourceId ? { sourceId } : {}) } as const);
    postToOpener(window.opener as Window | null, returnOrigin, message);
    writeStored(null);
    if (window.opener) window.close();
  }, [done, returnOrigin, state.sourceId]);

  return useMemo(
    () => ({
      phase,
      context,
      state,
      busy,
      problem,
      forms,
      fields,
      questions,
      mapFormId,
      testFormId,
      testWaiting,
      done,
      source,
      chooseChannel,
      showGuided,
      copyGuided,
      confirmCopy,
      waitForGoogleTest,
      signIn,
      pickPage,
      connectPage,
      setFormsChoice,
      saveForms,
      reloadForms,
      chooseMapForm,
      saveFieldMap,
      setTestFormId,
      sendTestLead,
      finish,
      close,
      dismissProblem: () => setProblem(null),
    }),
    [
      phase, context, state, busy, problem, forms, fields, questions, mapFormId, testFormId, testWaiting, done, source,
      chooseChannel, showGuided, copyGuided, confirmCopy, waitForGoogleTest, signIn, pickPage, connectPage, setFormsChoice, saveForms, reloadForms, chooseMapForm,
      saveFieldMap, sendTestLead, finish, close,
    ],
  );
}
