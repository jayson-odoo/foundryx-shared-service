import { describe, expect, it } from 'vitest';
import {
  INITIAL_WIZARD_STATE,
  WIZARD_STEPS,
  answerLabel,
  blockReason,
  currentStep,
  defaultTarget,
  progressPercent,
  stepsFor,
  visibleSteps,
  type WizardState,
} from './lead-capture-wizard';

const google: WizardState = { ...INITIAL_WIZARD_STATE, channel: 'google' };

describe('lead capture wizard, Google Ads guided path (card 68a R9)', () => {
  it('runs Channel, Copy, Test, Fields for Google and keeps Facebook unchanged', () => {
    expect(stepsFor('google').map((s) => s.key)).toEqual(['channel', 'copy', 'test', 'fields']);
    expect(stepsFor('facebook')).toBe(WIZARD_STEPS);
    expect(stepsFor(null)).toBe(WIZARD_STEPS);
  });

  it('opens Copy right after the channel is picked', () => {
    expect(currentStep(google)).toBe('copy');
    expect(visibleSteps(google).map((s) => s.key)).toEqual(['channel', 'copy']);
  });

  it('blocks Continue on Copy until both the URL and the key are copied', () => {
    const shown: WizardState = { ...google, sourceId: 'src', guided: { url: 'https://x/in/a', key: 'k' } };
    expect(blockReason('copy', shown)).toBeTruthy();
    expect(blockReason('copy', { ...shown, copiedUrl: true })).toBeTruthy();
    expect(blockReason('copy', { ...shown, copiedUrl: true, copiedKey: true })).toBeNull();
  });

  it('goes Test then Fields once Copy is confirmed, and is complete after the map is saved', () => {
    const copied: WizardState = { ...google, sourceId: 'src', copyConfirmed: true };
    expect(currentStep(copied)).toBe('test');
    expect(currentStep({ ...copied, testPassed: true })).toBe('fields');
    const all = { ...copied, testPassed: true, fieldsSaved: true };
    expect(currentStep(all)).toBeNull();
    expect(progressPercent(all)).toBe(100);
    expect(answerLabel('copy', all)?.text).toBe('Copied');
  });

  it('matches Google standard columns to the consumer fields', () => {
    const fields = [
      { key: 'name', label: 'Name', type: 'name' },
      { key: 'phone', label: 'Phone', type: 'phone' },
      { key: 'email', label: 'Email', type: 'email' },
      { key: 'notes', label: 'Lead notes', type: 'notes' },
    ];
    expect(defaultTarget({ key: 'PHONE_NUMBER', label: 'User Phone', type: 'text' }, fields)).toBe('phone');
    expect(defaultTarget({ key: 'WORK_EMAIL', label: 'Work email', type: 'text' }, fields)).toBe('email');
    expect(defaultTarget({ key: 'FULL_NAME', label: 'Full Name', type: 'text' }, fields)).toBe('name');
    expect(defaultTarget({ key: 'What is your budget?', label: 'Budget', type: 'text' }, fields)).toBe('notes');
  });
});
