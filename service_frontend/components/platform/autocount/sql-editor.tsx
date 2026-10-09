'use client';

import { useEffect, useMemo, useRef } from 'react';
import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
} from '@codemirror/autocomplete';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { MSSQL, MySQL, PostgreSQL, StandardSQL, sql } from '@codemirror/lang-sql';
import {
  bracketMatching,
  defaultHighlightStyle,
  syntaxHighlighting,
} from '@codemirror/language';
import { Compartment, EditorState } from '@codemirror/state';
import { EditorView, keymap, lineNumbers } from '@codemirror/view';
import { schemaCompletionConfig } from '@/lib/autocount-etl';
import type { AutocountSqlSchema } from '@/types/autocount';

export interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Read-only under the shell's global Edit toggle (like every form field). */
  editing: boolean;
  /** Introspected tree feeding table/column autocomplete (AC-22-07). */
  schema: AutocountSqlSchema | null;
  /** Dialect for keyword highlighting (`mssql` / `postgresql` / `mysql`). */
  dialect?: string | null;
  ariaLabel?: string;
  /** Test hook for the host element. */
  testId?: string;
}

/** Same chrome as the workflow Code node's editor - one editor look system-wide. */
const editorTheme = EditorView.theme({
  '&': {
    minHeight: '10rem',
    border: '1px solid var(--input)',
    borderRadius: '0.5rem',
    backgroundColor: 'var(--background)',
    fontSize: '0.8125rem',
  },
  '&.cm-focused': { outline: '2px solid var(--ring)', outlineOffset: '1px' },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
    lineHeight: '1.6',
  },
  '.cm-content': { padding: '0.625rem 0', minHeight: '9rem' },
  '.cm-gutters': {
    backgroundColor: 'var(--muted)',
    color: 'var(--muted-foreground)',
    border: 'none',
    borderRadius: '0.5rem 0 0 0.5rem',
  },
  '.cm-activeLineGutter': { backgroundColor: 'transparent' },
  '.cm-tooltip.cm-tooltip-autocomplete': {
    border: '1px solid var(--border)',
    borderRadius: '0.5rem',
    backgroundColor: 'var(--popover)',
    color: 'var(--popover-foreground)',
  },
  '.cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]': {
    backgroundColor: 'var(--accent)',
    color: 'var(--accent-foreground)',
  },
});

function dialectFor(key: string | null | undefined) {
  if (key === 'mssql') return MSSQL;
  if (key === 'postgresql') return PostgreSQL;
  if (key === 'mysql') return MySQL;
  return StandardSQL;
}

/**
 * CodeMirror 6 SQL editor (plan 22 AC-22-07): dialect keyword highlighting,
 * bracket match + auto-close, undo/redo, and autocomplete fed by the
 * introspected schema (tables + columns) - never a plain textarea.
 */
export function SqlEditor({
  value,
  onChange,
  editing,
  schema,
  dialect,
  ariaLabel = 'SQL query',
  testId = 'sql-editor',
}: SqlEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const editable = useRef(new Compartment());
  const language = useRef(new Compartment());
  onChangeRef.current = onChange;

  const languageExtension = useMemo(
    () =>
      sql({
        dialect: dialectFor(dialect),
        upperCaseKeywords: true,
        ...schemaCompletionConfig(schema),
      }),
    [dialect, schema],
  );

  useEffect(() => {
    if (!hostRef.current) return;
    const view = new EditorView({
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          history(),
          bracketMatching(),
          closeBrackets(),
          autocompletion(),
          syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
          keymap.of([
            ...closeBracketsKeymap,
            ...completionKeymap,
            ...historyKeymap,
            ...defaultKeymap,
          ]),
          language.current.of(languageExtension),
          editorTheme,
          editable.current.of(EditorView.editable.of(editing)),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) onChangeRef.current(update.state.doc.toString());
          }),
        ],
      }),
      parent: hostRef.current,
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Initial document captured once; later changes are dispatched below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || view.state.doc.toString() === value) return;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
  }, [value]);

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: editable.current.reconfigure(EditorView.editable.of(editing)),
    });
  }, [editing]);

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: language.current.reconfigure(languageExtension),
    });
  }, [languageExtension]);

  return (
    <div
      ref={hostRef}
      className="min-w-0"
      aria-label={ariaLabel}
      aria-readonly={!editing}
      data-testid={testId}
    />
  );
}
