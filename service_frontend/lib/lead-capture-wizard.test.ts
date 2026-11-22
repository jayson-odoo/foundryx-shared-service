import { describe, expect, it } from 'vitest';
import {
  INITIAL_WIZARD_STATE,
  WIZARD_STEPS,
  answerLabel,
  autoPage,
  blockReason,
  defaultTarget,
  currentStep,
  errorScreenFor,
  isLeadsAccessMessage,
  progressPercent,
  visibleSteps,
  withForms,
  type WizardState,
} from './lead-capture-wizard';

const pages = [
  { id: '1', name: 'Home Page' },
  { id: '2', name: 'Store Page' },
];

function answered(upTo: number): WizardState {
  const s: WizardState = { ...INITIAL_WIZARD_STATE };
  if (upTo >= 1) s.channel = 'facebook';
  if (upTo >= 2) s.signedIn = true;
  if (upTo >= 3) Object.assign(s, { pages, pageId: '1', sourceId: 'src' });
  if (upTo >= 4) Object.assign(s, { formsMode: 'all', formsSaved: true });
  if (upTo >= 5) s.fieldsSaved = true;
  if (upTo >= 6) s.testPassed = true;
  return s;
}

describe('lead capture wizard step engine', () => {
  it('names every step of the Facebook channel in order', () => {
    expect(WIZARD_STEPS.map((s) => s.label)).toEqual(['Channel', 'Sign in', 'Page', 'Forms', 'Fields', 'Test']);
  });

  it('shows a step only after the one before is answered', () => {
    expect(visibleSteps(INITIAL_WIZARD_STATE).map((s) => s.key)).toEqual(['channel']);
    expect(visibleSteps(answered(1)).map((s) => s.key)).toEqual(['channel', 'signin']);
    expect(visibleSteps(answered(3)).map((s) => s.key)).toEqual(['channel', 'signin', 'page', 'forms']);
    expect(currentStep(answered(6))).toBeNull();
    expect(visibleSteps(answered(6))).toHaveLength(6);
  });

  it('progress follows answered steps', () => {
    expect(progressPercent(INITIAL_WIZARD_STATE)).toBe(0);
    expect(progressPercent(answered(3))).toBe(50);
    expect(progressPercent(answered(6))).toBe(100);
  });

  it('a Page is answered only once it is connected, not merely picked', () => {
    const picked = { ...answered(2), pages, pageId: '1' };
    expect(currentStep(picked)).toBe('page');
    expect(currentStep({ ...picked, sourceId: 'src' })).toBe('forms');
  });

  it('folds answered steps to their answer and notes the only shared Page', () => {
    expect(answerLabel('channel', answered(1), { channelLabel: 'Facebook' })).toEqual({ text: 'Facebook' });
    expect(answerLabel('page', answered(3))?.text).toBe('Home Page');
    const only = { ...answered(3), pages: [pages[0]] };
    expect(answerLabel('page', only)?.note).toBe('(the only Page you shared)');
    expect(answerLabel('forms', answered(4))?.text).toBe('All forms, including new ones');
    expect(answerLabel('fields', answered(3))).toBeNull();
  });

  it('auto-picks the Page only when exactly one was shared', () => {
    expect(autoPage([pages[0]])).toBe('1');
    expect(autoPage(pages)).toBeNull();
    expect(autoPage([])).toBeNull();
    expect(autoPage(null)).toBeNull();
  });

  it('blocks Continue with the reason', () => {
    expect(blockReason('channel', INITIAL_WIZARD_STATE)).toBe('Pick a channel.');
    expect(blockReason('page', answered(2))).toBe('Pick a Page.');
    const pick = withForms(answered(3), 'pick', []);
    expect(blockReason('forms', pick)).toBe('Tick at least one form.');
    expect(blockReason('forms', withForms(pick, 'pick', ['9']))).toBeNull();
    expect(blockReason('forms', withForms(pick, 'all', ['9']))).toBeNull();
  });

  it('keeps later answers when an earlier step is reopened and answered again', () => {
    const done = answered(6);
    const again = withForms(done, 'pick', ['7']);
    expect(again.fieldsSaved).toBe(true);
    expect(again.testPassed).toBe(true);
    expect(again.formIds).toEqual(['7']);
    expect(withForms(again, 'all', ['7']).formIds).toEqual([]);
  });

  it('maps backend codes to the error screens', () => {
    expect(errorScreenFor('PERMISSION_DECLINED')).toBe('permission-declined');
    expect(errorScreenFor('PAGE_IN_USE')).toBe('page-in-use');
    expect(errorScreenFor('token_invalid')).toBe('reconnect');
    expect(errorScreenFor('SESSION_EXPIRED')).toBe('expired');
    expect(errorScreenFor('something_else')).toBe('generic');
    expect(errorScreenFor(null)).toBe('generic');
    expect(isLeadsAccessMessage('(#103) Leads Access restricted')).toBe(true);
    expect(isLeadsAccessMessage('Meta could not be reached.')).toBe(false);
  });
});

describe('default field map', () => {
  const fields = [
    { key: 'name', label: 'Name', type: 'text' },
    { key: 'phone', label: 'Phone', type: 'text' },
    { key: 'email', label: 'Email', type: 'text' },
    { key: 'notes', label: 'Lead notes', type: 'text' },
  ];
  it('matches standard questions and sends the rest to notes', () => {
    expect(defaultTarget({ key: 'full_name', label: 'Full name', type: 'FULL_NAME' }, fields)).toBe('name');
    expect(defaultTarget({ key: 'email', label: 'Email', type: 'EMAIL' }, fields)).toBe('email');
    expect(defaultTarget({ key: 'phone_number', label: 'Phone', type: 'PHONE' }, fields)).toBe('phone');
    expect(defaultTarget({ key: 'budget', label: 'Budget', type: 'CUSTOM' }, fields)).toBe('notes');
  });
  it('uses only fields the consumer published', () => {
    const custom = [{ key: 'contact_email', label: 'Email', type: 'text' }];
    expect(defaultTarget({ key: 'email', label: 'Email', type: 'EMAIL' }, custom)).toBeNull();
    expect(defaultTarget({ key: 'contact_email', label: 'E', type: 'CUSTOM' }, custom)).toBe('contact_email');
  });
});
