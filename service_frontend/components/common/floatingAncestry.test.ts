/**
 * T3 fix round 2 finding 5 - direct unit coverage for `focusIsInsideFloating`
 * and `createOutsideInteractionGuard`, which `dialog.tsx`/`alert-dialog.tsx`/
 * `sheet.tsx` all wire onto Radix's `onPointerDownOutside`/`onInteractOutside`/
 * `onFocusOutside`. Fix round 1 only covered these indirectly (via the
 * dialog/alert-dialog/sheet component tests' Escape/close-button flows) -
 * the guard's own branches (floating-surface target, mount-grace window,
 * neither) had no dedicated test.
 */
import { describe, expect, it, vi } from 'vitest';
import { createOutsideInteractionGuard, focusIsInsideFloating } from './floatingAncestry';

function makeCustomEvent(originalTarget: Element | null): CustomEvent<{ originalEvent?: Event }> {
  // Radix wraps the real DOM event in a CustomEvent whose OWN `target` is the
  // Content node itself; the actual click/pointer/focus target lives on
  // `detail.originalEvent.target` - mirrored here rather than using a real
  // MouseEvent, since jsdom's `target` on a dispatched event reflects where it
  // was actually dispatched, not an arbitrary value.
  const originalEvent = originalTarget ? ({ target: originalTarget } as unknown as Event) : undefined;
  return new CustomEvent('dismissableLayer.pointerDownOutside', {
    cancelable: true,
    detail: { originalEvent },
  });
}

describe('focusIsInsideFloating', () => {
  it('returns false for null', () => {
    expect(focusIsInsideFloating(null)).toBe(false);
  });

  it('returns false for a plain page element', () => {
    const div = document.createElement('div');
    document.body.appendChild(div);
    expect(focusIsInsideFloating(div)).toBe(false);
    div.remove();
  });

  it('returns true for an element inside a dropdown-menu-content', () => {
    const content = document.createElement('div');
    content.setAttribute('data-slot', 'dropdown-menu-content');
    const item = document.createElement('button');
    content.appendChild(item);
    document.body.appendChild(content);

    expect(focusIsInsideFloating(item)).toBe(true);
    expect(focusIsInsideFloating(content)).toBe(true);

    content.remove();
  });

  it('returns true for an element inside a stacked dialog-content', () => {
    const content = document.createElement('div');
    content.setAttribute('data-slot', 'dialog-content');
    const button = document.createElement('button');
    content.appendChild(button);
    document.body.appendChild(content);

    expect(focusIsInsideFloating(button)).toBe(true);

    content.remove();
  });
});

describe('createOutsideInteractionGuard (T3 fix round 2 finding 5)', () => {
  it('prevents an interaction whose originalEvent.target is inside a dropdown-menu-content', () => {
    const menu = document.createElement('div');
    menu.setAttribute('data-slot', 'dropdown-menu-content');
    const item = document.createElement('div');
    menu.appendChild(item);
    document.body.appendChild(menu);

    const mountedAtRef = { current: performance.now() - 10_000 }; // long past the grace window
    const guard = createOutsideInteractionGuard(mountedAtRef);
    const event = makeCustomEvent(item);

    guard(event);

    expect(event.defaultPrevented).toBe(true);
    menu.remove();
  });

  it('does not prevent an interaction outside any floating surface, after the mount grace window', () => {
    const outside = document.createElement('div');
    document.body.appendChild(outside);

    const mountedAtRef = { current: performance.now() - 10_000 }; // well past 300ms
    const guard = createOutsideInteractionGuard(mountedAtRef);
    const event = makeCustomEvent(outside);

    guard(event);

    expect(event.defaultPrevented).toBe(false);
    outside.remove();
  });

  it('prevents an interaction outside any floating surface within the 300ms mount grace window', () => {
    const outside = document.createElement('div');
    document.body.appendChild(outside);

    const mountedAtRef = { current: performance.now() }; // just mounted
    const guard = createOutsideInteractionGuard(mountedAtRef);
    const event = makeCustomEvent(outside);

    guard(event);

    expect(event.defaultPrevented).toBe(true);
    outside.remove();
  });

  it('does not prevent an interaction outside any floating surface once the grace window has elapsed', () => {
    // `vi.useFakeTimers()` does not fake `performance.now()` by default in
    // this vitest version - spying on it directly is the reliable way to
    // move wall-clock time forward past the 300ms boundary without a real
    // sleep.
    const outside = document.createElement('div');
    document.body.appendChild(outside);

    const now = vi.spyOn(performance, 'now').mockReturnValue(1_000);
    const mountedAtRef = { current: 1_000 };
    const guard = createOutsideInteractionGuard(mountedAtRef);

    now.mockReturnValue(1_301); // 301ms later - just past the 300ms grace window
    const event = makeCustomEvent(outside);
    guard(event);

    expect(event.defaultPrevented).toBe(false);
    outside.remove();
    now.mockRestore();
  });

  it('falls back to event.target when there is no detail.originalEvent', () => {
    const menu = document.createElement('div');
    menu.setAttribute('data-slot', 'select-content');
    document.body.appendChild(menu);

    const mountedAtRef = { current: performance.now() - 10_000 };
    const guard = createOutsideInteractionGuard(mountedAtRef);
    const event = new CustomEvent('dismissableLayer.pointerDownOutside', { cancelable: true, detail: {} });
    Object.defineProperty(event, 'target', { value: menu, configurable: true });

    guard(event);

    expect(event.defaultPrevented).toBe(true);
    menu.remove();
  });

  it('mountedAtRef.current === 0 (unmounted content) never triggers the grace window', () => {
    const outside = document.createElement('div');
    document.body.appendChild(outside);

    const mountedAtRef = { current: 0 };
    const guard = createOutsideInteractionGuard(mountedAtRef);
    const event = makeCustomEvent(outside);

    guard(event);

    expect(event.defaultPrevented).toBe(false);
    outside.remove();
  });
});
