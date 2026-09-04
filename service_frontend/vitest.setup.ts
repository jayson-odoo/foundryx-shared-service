import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
});

// jsdom polyfills for components that measure (OverflowPills) or use Radix
// (pointer capture / scrollIntoView are not implemented in jsdom). Guarded
// on `typeof Element` because a handful of tests (e.g. the repo-tracked-
// content guard, AC-DLA-69) run under `@vitest-environment node`, which has
// no DOM globals at all - this setup file still runs for them, so it must
// not crash before those tests get a chance to run.
if (typeof Element !== 'undefined') {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).ResizeObserver = ResizeObserverStub;
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false;
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
}

// next/navigation router stub (overridable per-test via vi.mocked)
const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/signin',
  useSearchParams: () => new URLSearchParams(),
}));
