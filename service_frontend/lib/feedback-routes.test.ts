import { describe, expect, it } from 'vitest';
import { FEEDBACK_REDIRECTS, feedbackRedirectFor } from './feedback-routes';

// Owner ruling 15 Nov (lane FEEDBACK-RENAME): no page URL says idea/ideas/
// ideation; every old URL keeps working through a PERMANENT redirect.
describe('feedback route redirects', () => {
  it.each([
    ['/ideation', '/feedback'],
    ['/ideation/ideas', '/feedback'],
    ['/ideation/ideas/new', '/feedback/new'],
    ['/ideation/ideas/abc-123', '/feedback/abc-123'],
    ['/ideation/board', '/feedback/board'],
    ['/ideation/business-requirements', '/feedback/business-requirements'],
    ['/ideation/business-requirements/br-1', '/feedback/business-requirements/br-1'],
    ['/ideation/embed-connections', '/feedback/embed-connections'],
    ['/embed/ideas', '/embed/feedback'],
    ['/embed/ideas/new', '/embed/feedback/new'],
    ['/embed/ideas/abc-123', '/embed/feedback/abc-123'],
    ['/embed/ideas/portal', '/embed/feedback/portal'],
    ['/embed/ideas/portal/feedback', '/embed/feedback/portal/list'],
    ['/embed/ideas/portal/changelog', '/embed/feedback/portal/changelog'],
    ['/embed/ideas/portal/abc-123', '/embed/feedback/portal/abc-123'],
    ['/public/ideas/tok_1', '/public/feedback/tok_1'],
    ['/portal/ideas', '/portal/feedback'],
    ['/portal/ideas/feedback', '/portal/feedback/list'],
    ['/portal/ideas/changelog', '/portal/feedback/changelog'],
    ['/portal/ideas/abc-123', '/portal/feedback/abc-123'],
  ])('%s -> %s', (from, to) => {
    expect(feedbackRedirectFor(from)).toBe(to);
  });

  it('every rule is permanent and no destination says idea', () => {
    expect(FEEDBACK_REDIRECTS.length).toBeGreaterThan(0);
    for (const r of FEEDBACK_REDIRECTS) {
      expect(r.permanent).toBe(true);
      expect(r.destination).not.toMatch(/idea/i);
    }
  });

  it('leaves unrelated paths alone', () => {
    expect(feedbackRedirectFor('/feedback')).toBeNull();
    expect(feedbackRedirectFor('/users')).toBeNull();
    expect(feedbackRedirectFor('/embed/omnichannel/inbox')).toBeNull();
  });
});
