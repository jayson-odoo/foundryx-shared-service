'use client';

/**
 * Search rules shared by the Foundryx UIUX dropdowns (playbook 0.71.0
 * "Searchable dropdowns"): match any word in the name, code or second line,
 * bold the matched letters, show at most 50 results, and wait a 0.25 s pause
 * in typing before asking the server for more.
 */
import { Fragment, useEffect, useRef, type ReactNode } from 'react';

export const FX_MENU_LIMIT = 50;
export const FX_FETCH_PAUSE_MS = 250;

export interface FxSearchable {
  label: string;
  value: string;
  description?: string;
}

/** The typed words, lower-cased. */
export function queryWords(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/** True when every typed word appears in the name, the code or the second line. */
export function fxMatches(option: FxSearchable, words: string[]): boolean {
  if (!words.length) return true;
  const hay = `${option.label} ${option.value} ${option.description ?? ''}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** The text with every typed word's letters in bold. */
export function FxHighlight({ text, words }: { text: string; words: string[] }): ReactNode {
  if (!words.length) return text;
  const lower = text.toLowerCase();
  const marks = new Array<boolean>(text.length).fill(false);
  for (const w of words) {
    let at = lower.indexOf(w);
    while (at >= 0) {
      for (let i = at; i < at + w.length; i += 1) marks[i] = true;
      at = lower.indexOf(w, at + w.length);
    }
  }
  const out: ReactNode[] = [];
  let i = 0;
  while (i < text.length) {
    const bold = marks[i];
    let j = i;
    while (j < text.length && marks[j] === bold) j += 1;
    const piece = text.slice(i, j);
    out.push(bold ? <b key={i} className="font-semibold">{piece}</b> : <Fragment key={i}>{piece}</Fragment>);
    i = j;
  }
  return out;
}

/** "Keep typing to narrow 1,240 results" past the 50 shown. */
export function narrowText(total: number): string {
  return `Keep typing to narrow ${total.toLocaleString('en-US')} results`;
}

/** What an empty search says: "No products match "oak 18"". */
export function nothingMatchesText(query: string, noun?: string): string {
  return noun ? `No ${noun} match "${query}"` : `Nothing matches "${query}"`;
}

/**
 * Calls `send` with the latest query after a 0.25 s pause in typing; an empty
 * query (the list closing) goes at once.
 */
export function usePausedQuery(send: ((query: string) => void) | undefined) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendRef = useRef(send);
  sendRef.current = send;
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (query: string) => {
    if (!sendRef.current) return;
    if (timer.current) clearTimeout(timer.current);
    if (!query) {
      sendRef.current(query);
      return;
    }
    timer.current = setTimeout(() => sendRef.current?.(query), FX_FETCH_PAUSE_MS);
  };
}
