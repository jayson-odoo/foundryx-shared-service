import { describe, expect, it } from 'vitest';
import {
  INITIAL_WIZARD_STATE,
  answerLabel,
  blockReason,
  currentStep,
  progressPercent,
  stepsFor,
  visibleSteps,
  type WizardState,
} from './lead-capture-wizard';

const accounts = [{ id: '1', name: 'Acme Ads' }];
const forms = [
  { id: 'f1', name: 'Solar quote' },
  { id: 'f2', name: 'Battery quote' },
];
const signin: WizardState = { ...INITIAL_WIZARD_STATE, channel: 'google', googleSignIn: true };

describe('lead capture wizard, Google sign-in path (plan 68 G-D4)', () => {
  it('runs Channel, Sign in, Account, Forms, Test, Fields', () => {
    expect(stepsFor('google', true).map((s) => s.label)).toEqual(['Channel', 'Sign in', 'Account', 'Forms', 'Test', 'Fields']);
    expect(stepsFor('google', true)[1].question).toBe('Sign in to Google');
    expect(stepsFor('google', false).map((s) => s.key)).toEqual(['channel', 'copy', 'test', 'fields']);
  });

  it('asks for the account after sign-in and folds a single account with a note', () => {
    const signed = { ...signin, signedIn: true, googleAccounts: accounts, accountId: '1' };
    expect(currentStep(signed)).toBe('account');
    expect(blockReason('account', { ...signed, accountId: null })).toBeTruthy();
    const chosen = { ...signed, googleForms: forms };
    expect(currentStep(chosen)).toBe('forms');
    expect(answerLabel('account', chosen)).toEqual({ text: 'Acme Ads', note: '(the only account you can reach)' });
  });

  it('blocks Connect until a form is ticked; no "all forms" choice for Google', () => {
    const atForms = { ...signin, signedIn: true, googleAccounts: accounts, accountId: '1', googleForms: forms };
    expect(blockReason('forms', atForms)).toBe('Tick at least one form.');
    expect(blockReason('forms', { ...atForms, formIds: ['f1'] })).toBeNull();
    const saved = { ...atForms, formIds: ['f1'], formsSaved: true, sourceId: 's' };
    expect(answerLabel('forms', saved)?.text).toBe('Solar quote');
    expect(currentStep(saved)).toBe('test');
    expect(visibleSteps(saved).map((s) => s.key)).toEqual(['channel', 'signin', 'account', 'forms', 'test']);
    expect(progressPercent({ ...saved, testPassed: true, fieldsSaved: true })).toBe(100);
  });
});
