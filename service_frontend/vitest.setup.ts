import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { MotionGlobalConfig } from 'motion/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
});

// T3 (AC-DLA-20): Dialog/AlertDialog/Sheet/Popover/DropdownMenu/ContextMenu/
// HoverCard/Menubar/Select now open and close on a real JS spring
// (`motion/react`'s `AnimatePresence` + `forceMount`) instead of the CSS
// `animate-in`/`animate-out` classes they replaced. Unlike those classes,
// a spring genuinely ticks over wall-clock time even in jsdom - without this,
// every test that opens then closes one of those surfaces would leave the
// closing content mounted (mid-exit) for the rest of the test, so a
// synchronous `getByRole` query for whatever is BEHIND or AFTER it finds a
// stale, still-`aria-expanded` element instead. `skipAnimations` makes
// motion apply the final keyframe and report completion immediately instead
// of animating, so a closed surface is actually gone from the DOM by the
// time the next assertion runs. A test that cares about the spring itself
// (`lib/motion.test.ts`) asserts the transition object it was handed rather
// than an in-flight animated value, so this does not weaken that coverage.
MotionGlobalConfig.skipAnimations = true;

// jsdom polyfills for components that measure (OverflowPills) or use Radix
// (pointer capture / scrollIntoView are not implemented in jsdom). Guarded
// on `typeof Element` because a handful of tests (e.g. the repo-tracked-
// content guard, AC-DLA-69) run under `@vitest-environment node`, which has
// no DOM globals at all - this setup file still runs for them, so it must
// not crash before those tests get a chance to run.
if (typeof Element !== 'undefined') {
  class ResizeObserverStub implements ResizeObserver {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false;
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
}
// jsdom doesn't implement matchMedia (useIsMobile, useMediaQuery). Default to
// "no match" (desktop) - tests that care about a specific breakpoint override
// window.matchMedia per-test. Guarded on `typeof window` for the same
// node-environment tests the ResizeObserver block above guards against.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList;
}

// next/navigation router stub (overridable per-test via vi.mocked)
const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/signin',
  useSearchParams: () => new URLSearchParams(),
}));
