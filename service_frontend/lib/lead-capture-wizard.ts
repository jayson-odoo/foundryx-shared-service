/**
 * Hosted Lead Capture wizard - the pure step engine (plan 64 L-C, AC-64-12/15/16/21).
 *
 * One question per step; a step appears only after the one before it is
 * answered; answered steps fold to one line (question + answer) and reopen on
 * click with their answer kept. A blocked Continue carries its reason.
 * No React here so every rule is unit-tested on its own.
 */
import type { WizardConsumerField, WizardPage, WizardQuestion } from '@/types/lead-capture-wizard';

export type WizardStepKey = 'channel' | 'signin' | 'page' | 'forms' | 'fields' | 'test' | 'copy' | 'account';

export interface WizardStepDef {
  key: WizardStepKey;
  /** Progress-bar name. */
  label: string;
  /** The step's one question. */
  question: string;
}

export const WIZARD_STEPS: readonly WizardStepDef[] = [
  { key: 'channel', label: 'Channel', question: 'Where do the leads come from?' },
  { key: 'signin', label: 'Sign in', question: 'Sign in to Facebook' },
  { key: 'page', label: 'Page', question: 'Which Page do the leads come from?' },
  { key: 'forms', label: 'Forms', question: 'Which lead forms?' },
  { key: 'fields', label: 'Fields', question: 'Where does each answer go?' },
  { key: 'test', label: 'Test', question: 'Send a test lead' },
];

/** Google Ads lead forms, guided path (card 68a R9): the person pastes our
 * URL + key into the Google Ads form, Google's "Send test data" passes Test,
 * and the Fields step maps the columns that test lead carried. */
export const GOOGLE_STEPS: readonly WizardStepDef[] = [
  WIZARD_STEPS[0],
  { key: 'copy', label: 'Copy', question: 'Paste these into your Google Ads lead form' },
  { key: 'test', label: 'Test', question: 'Send test data from Google Ads' },
  { key: 'fields', label: 'Fields', question: 'Where does each answer go?' },
];

/** Google Ads with Google sign-in (plan 68 G-D4): we write the URL + key
 * into the ticked forms; Test and Fields work as on the guided path. */
export const GOOGLE_SIGNIN_STEPS: readonly WizardStepDef[] = [
  WIZARD_STEPS[0],
  { key: 'signin', label: 'Sign in', question: 'Sign in to Google' },
  { key: 'account', label: 'Account', question: 'Which Google Ads account?' },
  { key: 'forms', label: 'Forms', question: 'Which lead forms?' },
  { key: 'test', label: 'Test', question: 'Send test data from Google Ads' },
  { key: 'fields', label: 'Fields', question: 'Where does each answer go?' },
];

/** The steps of the chosen channel (Facebook until one is chosen). */
export function stepsFor(channel: string | null | undefined, googleSignIn = false): readonly WizardStepDef[] {
  if (channel !== 'google') return WIZARD_STEPS;
  return googleSignIn ? GOOGLE_SIGNIN_STEPS : GOOGLE_STEPS;
}

function stepsOf(s: WizardState): readonly WizardStepDef[] {
  return stepsFor(s.channel, s.googleSignIn);
}

export interface GuidedSecret {
  url: string;
  key: string;
}

export type FormsChoice = 'all' | 'pick';

export interface WizardState {
  channel: string | null;
  signedIn: boolean;
  pages: WizardPage[] | null;
  pageId: string | null;
  /** Set once the Page is connected (the source exists). */
  sourceId: string | null;
  formsMode: FormsChoice | null;
  formIds: string[];
  formsSaved: boolean;
  fieldsSaved: boolean;
  testPassed: boolean;
  /** Google: the inbound URL + key, held only in this tab. */
  guided: GuidedSecret | null;
  copiedUrl: boolean;
  copiedKey: boolean;
  copyConfirmed: boolean;
  /** Google: the sign-in path (plan 68) instead of the guided copy path. */
  googleSignIn: boolean;
  googleAccounts: WizardPage[] | null;
  accountId: string | null;
  /** The chosen account's lead forms (set = the Account step is answered). */
  googleForms: WizardPage[] | null;
}

export const INITIAL_WIZARD_STATE: WizardState = {
  channel: null,
  signedIn: false,
  pages: null,
  pageId: null,
  sourceId: null,
  formsMode: null,
  formIds: [],
  formsSaved: false,
  fieldsSaved: false,
  testPassed: false,
  guided: null,
  copiedUrl: false,
  copiedKey: false,
  copyConfirmed: false,
  googleSignIn: false,
  googleAccounts: null,
  accountId: null,
  googleForms: null,
};

/** Has this step got its answer? */
export function isAnswered(step: WizardStepKey, s: WizardState): boolean {
  switch (step) {
    case 'channel':
      return Boolean(s.channel);
    case 'signin':
      return s.signedIn;
    case 'page':
      return Boolean(s.sourceId);
    case 'forms':
      return s.formsSaved;
    case 'fields':
      return s.fieldsSaved;
    case 'test':
      return s.testPassed;
    case 'copy':
      return s.copyConfirmed;
    case 'account':
      return s.googleForms !== null;
    default:
      return false;
  }
}

/** The first step still waiting for an answer; null = every step answered. */
export function currentStep(s: WizardState): WizardStepKey | null {
  const step = stepsOf(s).find((d) => !isAnswered(d.key, s));
  return step ? step.key : null;
}

/** Steps shown: every answered step plus the current one, never a later one. */
export function visibleSteps(s: WizardState): WizardStepDef[] {
  const current = currentStep(s);
  const out: WizardStepDef[] = [];
  for (const def of stepsOf(s)) {
    out.push(def);
    if (def.key === current) break;
  }
  return out;
}

/** 0..100 for the progress bar. */
export function progressPercent(s: WizardState): number {
  const steps = stepsOf(s);
  const done = steps.filter((d) => isAnswered(d.key, s)).length;
  return Math.round((done / steps.length) * 100);
}

export interface FoldedAnswer {
  text: string;
  /** "(the only Page you shared)" style note. */
  note?: string;
}

/** The answer chip of a folded step. */
export function answerLabel(
  step: WizardStepKey,
  s: WizardState,
  extras: { channelLabel?: string; formNames?: Record<string, string> } = {},
): FoldedAnswer | null {
  if (!isAnswered(step, s)) return null;
  switch (step) {
    case 'channel':
      return { text: extras.channelLabel ?? s.channel ?? '' };
    case 'signin':
      return { text: 'Signed in' };
    case 'page': {
      const page = s.pages?.find((p) => p.id === s.pageId);
      const onlyOne = (s.pages?.length ?? 0) === 1;
      return { text: page?.name ?? s.pageId ?? '', note: onlyOne ? '(the only Page you shared)' : undefined };
    }
    case 'account': {
      const account = s.googleAccounts?.find((a) => a.id === s.accountId);
      const onlyOne = (s.googleAccounts?.length ?? 0) === 1;
      return { text: account?.name ?? '', note: onlyOne ? '(the only account you can reach)' : undefined };
    }
    case 'forms':
      if (s.channel === 'google') {
        const names = Object.fromEntries((s.googleForms ?? []).map((f) => [f.id, f.name]));
        return { text: s.formIds.length === 1 ? (names[s.formIds[0]] ?? '1 form') : `${s.formIds.length} forms` };
      }
      if (s.formsMode === 'all') return { text: 'All forms, including new ones' };
      return {
        text:
          s.formIds.length === 1
            ? (extras.formNames?.[s.formIds[0]] ?? '1 form')
            : `${s.formIds.length} forms`,
      };
    case 'fields':
      return { text: 'Mapped' };
    case 'test':
      return { text: 'Test lead received' };
    case 'copy':
      return { text: 'Copied' };
    default:
      return null;
  }
}

/** One granted Page is chosen automatically (AC-64-21). */
export function autoPage(pages: WizardPage[] | null): string | null {
  return pages && pages.length === 1 ? pages[0].id : null;
}

/** Why Continue is disabled on this step right now (null = allowed). */
export function blockReason(step: WizardStepKey, s: WizardState): string | null {
  switch (step) {
    case 'channel':
      return s.channel ? null : 'Pick a channel.';
    case 'page':
      return s.pageId ? null : 'Pick a Page.';
    case 'copy':
      if (!s.guided) return 'Show the URL and key first.';
      return s.copiedUrl && s.copiedKey ? null : 'Copy the URL and the key first.';
    case 'account':
      return s.accountId ? null : 'Pick an account.';
    case 'forms':
      if (s.channel === 'google') return s.formIds.length ? null : 'Tick at least one form.';
      if (!s.formsMode) return 'Choose which forms.';
      if (s.formsMode === 'pick' && s.formIds.length === 0) return 'Tick at least one form.';
      return null;
    default:
      return null;
  }
}

/** Reopening an answered step keeps every answer (AC-64-12). Re-answering the
 * forms step re-saves it; nothing later is cleared. */
export function withForms(s: WizardState, mode: FormsChoice, ids: string[]): WizardState {
  return { ...s, formsMode: mode, formIds: mode === 'all' ? [] : ids };
}

/** Error codes the backend answers, mapped to the screen the wizard shows. */
export type WizardErrorScreen =
  | 'permission-declined' // E1
  | 'no-pages' // E2
  | 'leads-access' // E3
  | 'page-in-use' // E4
  | 'reconnect' // E5
  | 'expired'
  | 'generic';

export function errorScreenFor(code: string | null | undefined): WizardErrorScreen {
  switch (code) {
    case 'PERMISSION_DECLINED':
    case 'LOGIN_FAILED':
      return 'permission-declined';
    case 'PAGE_IN_USE':
      return 'page-in-use';
    case 'token_invalid':
    case 'LOGIN_REQUIRED':
      return 'reconnect';
    case 'SESSION_EXPIRED':
    case 'invalid_token':
      return 'expired';
    default:
      return 'generic';
  }
}

/** Leads Access refusal on the form read (Meta code 103 family / text). */
export function isLeadsAccessMessage(message: string | null | undefined): boolean {
  return Boolean(message && /leads access|\(#103\)|crm/i.test(message));
}

const STANDARD_TARGETS: Record<string, string[]> = {
  FULL_NAME: ['name', 'full_name', 'fullName'],
  FIRST_NAME: ['first_name', 'firstName', 'name'],
  LAST_NAME: ['last_name', 'lastName'],
  EMAIL: ['email'],
  WORK_EMAIL: ['email'],
  PHONE: ['phone', 'phone_number', 'mobile'],
  PHONE_NUMBER: ['phone', 'phone_number', 'mobile'],
  WORK_PHONE: ['phone', 'phone_number', 'mobile'],
};
const NOTES_KEYS = ['notes', 'note', 'remarks'];

/**
 * The default target of one form question (AC-64-24): standard questions
 * (full name, email, phone) go to the matching consumer field; anything else
 * to Lead notes. Only keys the consumer actually published are returned.
 */
export function defaultTarget(question: WizardQuestion, fields: WizardConsumerField[]): string | null {
  const keys = new Set(fields.map((f) => f.key));
  const byType = STANDARD_TARGETS[(question.type || '').toUpperCase()] ?? [];
  const byKey = STANDARD_TARGETS[(question.key || '').toUpperCase()] ?? [];
  for (const candidate of [...byType, ...byKey, question.key]) {
    if (keys.has(candidate)) return candidate;
  }
  return NOTES_KEYS.find((k) => keys.has(k)) ?? null;
}
