import type { ReactNode } from 'react';
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { useFx, useFxControls, useFxSetting } from '@/hooks/use-fx';
import { FxProvider } from '@/providers/fx-provider';
import { FxComponentsOff } from './fx-components-off';
import { FxOff } from './fx-off';

function resetHtml() {
  const html = document.documentElement;
  for (const attr of Array.from(html.attributes)) {
    if (attr.name.startsWith('data-fx')) html.removeAttribute(attr.name);
  }
  html.removeAttribute('style');
}

beforeEach(() => {
  resetHtml();
  window.localStorage.clear();
});
afterEach(resetHtml);

function wrap(inner?: (children: ReactNode) => ReactNode) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={true} initialTheme={FX_DEFAULT_THEME}>
        {inner ? inner(children) : children}
      </FxProvider>
    );
  };
}

const componentsOff = wrap((c) => <FxComponentsOff>{c}</FxComponentsOff>);

describe('FxComponentsOff', () => {
  it('leaves components on outside the boundary', () => {
    const { result } = renderHook(() => useFx(), { wrapper: wrap() });
    expect(result.current).toBe(true);
  });

  it('turns useFx and useFxSetting off inside it, switch on', () => {
    expect(
      renderHook(() => useFx(), { wrapper: componentsOff }).result.current,
    ).toBe(false);
    expect(
      renderHook(() => useFxSetting('anything'), { wrapper: componentsOff })
        .result.current,
    ).toBeUndefined();
  });

  it('keeps the global look on <html> and the switch controls', () => {
    document.documentElement.setAttribute('data-fx', 'on');
    document.documentElement.style.setProperty('--fx-scale', '0.9');
    const { result } = renderHook(() => useFxControls(), {
      wrapper: componentsOff,
    });
    expect(result.current?.on).toBe(true);
    expect(document.documentElement.getAttribute('data-fx')).toBe('on');
    expect(document.documentElement.style.getPropertyValue('--fx-scale')).toBe(
      '0.9',
    );
  });

  it('FxOff still clears the global look (unchanged)', () => {
    document.documentElement.setAttribute('data-fx', 'on');
    renderHook(() => useFx(), { wrapper: wrap((c) => <FxOff>{c}</FxOff>) });
    expect(document.documentElement.hasAttribute('data-fx')).toBe(false);
  });
});
