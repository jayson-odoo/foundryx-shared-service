import type { ReactNode } from 'react';
import { act, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { FX_DEFAULT_THEME, readCookie } from '@/lib/fx/cookies';
import { FX_PLAYBOOK_VERSION, FX_SWITCH_NAME } from '@/lib/fx/version';
import { useFx, useFxControls, useFxSetting } from '@/hooks/use-fx';
import { FxOff } from '@/components/fx/fx-off';
import { FxProvider } from './fx-provider';

function clearCookies() {
  for (const name of ['fx_uiux', 'fx_theme'])
    document.cookie = `${name}=; Path=/; Max-Age=0`;
}

function resetHtml() {
  const html = document.documentElement;
  for (const attr of Array.from(html.attributes)) {
    if (attr.name.startsWith('data-fx')) html.removeAttribute(attr.name);
  }
  html.removeAttribute('style');
  document.head
    .querySelectorAll('link[data-fx-fonts]')
    .forEach((link) => link.remove());
}

beforeEach(() => {
  clearCookies();
  resetHtml();
  window.localStorage.clear();
});

afterEach(() => {
  clearCookies();
  resetHtml();
});

function wrap(initial: boolean) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={initial} initialTheme={FX_DEFAULT_THEME}>
        {children}
      </FxProvider>
    );
  };
}

describe('FxProvider and useFx', () => {
  it('is off with no provider and off by default (no cookie)', () => {
    expect(renderHook(() => useFx()).result.current).toBe(false);
    expect(
      renderHook(() => useFx(), { wrapper: wrap(false) }).result.current,
    ).toBe(false);
    expect(document.documentElement.hasAttribute('data-fx')).toBe(false);
    expect(readCookie(document.cookie, 'fx_uiux')).toBeUndefined();
  });

  it('renders no DOM of its own', () => {
    const { container } = render(
      <FxProvider initial={false} initialTheme={FX_DEFAULT_THEME}>
        <span>child</span>
      </FxProvider>,
    );
    expect(container.innerHTML).toBe('<span>child</span>');
  });

  it('turning on writes the cookie, the <html> attributes and the font link; off deletes them', () => {
    const { result } = renderHook(() => useFxControls(), {
      wrapper: wrap(false),
    });
    act(() => result.current!.setOn(true));
    const html = document.documentElement;
    expect(result.current!.on).toBe(true);
    expect(readCookie(document.cookie, 'fx_uiux')).toBe('on');
    expect(html.getAttribute('data-fx')).toBe('on');
    expect(html.getAttribute('data-fx-pal')).toBe('slate');
    expect(html.getAttribute('data-fx-dpal')).toBe('midnight');
    expect(html.getAttribute('data-fx-font')).toBe('geist');
    expect(html.style.getPropertyValue('--fx-scale')).toBe('0.9');
    expect(document.head.querySelectorAll('link[data-fx-fonts]')).toHaveLength(
      1,
    );

    act(() => result.current!.setOn(false));
    expect(result.current!.on).toBe(false);
    expect(readCookie(document.cookie, 'fx_uiux')).toBeUndefined();
    for (const attr of [
      'data-fx',
      'data-fx-pal',
      'data-fx-dpal',
      'data-fx-font',
    ]) {
      expect(html.hasAttribute(attr), attr).toBe(false);
    }
    expect(html.style.getPropertyValue('--fx-scale')).toBe('');
  });

  it('a theme choice writes fx_theme and applies at once while on', () => {
    const { result } = renderHook(() => useFxControls(), {
      wrapper: wrap(true),
    });
    act(() => result.current!.setTheme({ pal: 'sand', scale: 110 }));
    expect(readCookie(document.cookie, 'fx_theme')).toBe(
      'sand.midnight.geist.110',
    );
    expect(document.documentElement.getAttribute('data-fx-pal')).toBe('sand');
    expect(document.documentElement.style.getPropertyValue('--fx-scale')).toBe(
      '1.1',
    );
  });

  it('a theme choice while off is remembered but changes nothing on the page', () => {
    const { result } = renderHook(() => useFxControls(), {
      wrapper: wrap(false),
    });
    act(() => result.current!.setTheme({ font: 'inter' }));
    expect(readCookie(document.cookie, 'fx_theme')).toBe(
      'slate.midnight.inter.90',
    );
    expect(document.documentElement.hasAttribute('data-fx-font')).toBe(false);
  });

  it('stores only changed settings and reflects them on <html> while on', () => {
    const { result } = renderHook(
      () => ({ controls: useFxControls(), motion: useFxSetting('motion') }),
      {
        wrapper: wrap(true),
      },
    );
    expect(result.current.motion).toBe(true);
    act(() => result.current.controls!.setSetting('motion', false));
    act(() => result.current.controls!.setSetting('scroll-size', 8));
    expect(result.current.motion).toBe(false);
    expect(JSON.parse(window.localStorage.getItem('fx_settings')!)).toEqual({
      motion: false,
      'scroll-size': 8,
    });
    expect(document.documentElement.getAttribute('data-fx-motion')).toBe('off');
    expect(
      document.documentElement.style.getPropertyValue('--fx-scroll-size'),
    ).toBe('8px');

    act(() => result.current.controls!.setSetting('motion', true));
    expect(JSON.parse(window.localStorage.getItem('fx_settings')!)).toEqual({
      'scroll-size': 8,
    });

    act(() => result.current.controls!.setOn(false));
    expect(document.documentElement.hasAttribute('data-fx-motion')).toBe(false);
    expect(
      document.documentElement.style.getPropertyValue('--fx-scroll-size'),
    ).toBe('');
  });

  it('FxOff forces off inside it and clears the <html> attributes', () => {
    document.documentElement.setAttribute('data-fx', 'on');
    const { result } = renderHook(
      () => ({
        on: useFx(),
        controls: useFxControls(),
        s: useFxSetting('motion'),
      }),
      {
        wrapper: ({ children }) => (
          <FxProvider initial={true} initialTheme={FX_DEFAULT_THEME}>
            <FxOff>{children}</FxOff>
          </FxProvider>
        ),
      },
    );
    expect(result.current).toEqual({ on: false, controls: null, s: undefined });
    expect(document.documentElement.hasAttribute('data-fx')).toBe(false);
  });
});

describe('switch identity', () => {
  it('is "Foundryx UIUX" built from playbook 0.71.0', () => {
    render(
      <span>
        {FX_SWITCH_NAME} ({FX_PLAYBOOK_VERSION})
      </span>,
    );
    expect(screen.getByText('Foundryx UIUX (0.71.0)')).toBeInTheDocument();
  });
});
