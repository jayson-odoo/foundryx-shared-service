/**
 * Crew pass 03f97ef6 (#259): the same-path click guard compared only the path,
 * so on Leads opened from a source (`/lead-capture/leads?source=<id>`) the
 * sidebar "Leads" link (`/lead-capture/leads`) was cancelled and the full list
 * could not be opened. Only a link that differs from the current URL by `ctx`
 * alone is the page you are on.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { keepListCtxOnSamePathClick } from './list-url-state';

let stop: () => void = () => {};

function clickLink(href: string): boolean {
  const a = document.createElement('a');
  a.href = href;
  a.textContent = 'link';
  document.body.appendChild(a);
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
  a.dispatchEvent(event);
  a.remove();
  return event.defaultPrevented;
}

beforeEach(() => {
  window.history.replaceState(null, '', '/lead-capture/leads?source=abc&ctx=XYZ');
  stop = keepListCtxOnSamePathClick();
});

afterEach(() => stop());

describe('keepListCtxOnSamePathClick', () => {
  it('lets a link that drops the page\'s own query (sidebar "Leads" on a filtered list) navigate', () => {
    expect(clickLink('/lead-capture/leads')).toBe(false);
  });

  it('lets a link with a different query navigate', () => {
    expect(clickLink('/lead-capture/leads?source=def')).toBe(false);
  });

  it('keeps a link that would only drop ctx from navigating (the page you are on)', () => {
    expect(clickLink('/lead-capture/leads?source=abc')).toBe(true);
  });

  it('never touches a link to another page', () => {
    expect(clickLink('/lead-capture/sources')).toBe(false);
  });

  it('a list with no other query: its bare sidebar link is the page you are on', () => {
    window.history.replaceState(null, '', '/lead-capture/keys?ctx=XYZ');
    expect(clickLink('/lead-capture/keys')).toBe(true);
  });
});
