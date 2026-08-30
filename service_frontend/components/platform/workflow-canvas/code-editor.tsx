'use client';

import { useEffect, useMemo, useRef } from 'react';
import { python } from '@codemirror/lang-python';
import { linter } from '@codemirror/lint';
import { Compartment, EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { TriangleAlert } from 'lucide-react';
import { codeSourceIssues } from '@/lib/workflow-doc';
import { Alert, AlertDescription, AlertIcon } from '@/components/ui/alert';

export interface CodeEditorProps {
  value: string;
  editing: boolean;
  onChange: (value: string) => void;
}

const editorTheme = EditorView.theme({
  '&': {
    minHeight: '12rem',
    border: '1px solid var(--input)',
    borderRadius: '0.5rem',
  },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: 'var(--font-mono, ui-monospace)',
  },
  '.cm-content': { padding: '0.75rem', minHeight: '10rem' },
  '.cm-gutters': {
    backgroundColor: 'var(--muted)',
    color: 'var(--muted-foreground)',
    border: 'none',
  },
});

/** CodeMirror 6 Python editor. Diagnostics remain intentionally conservative:
 * syntax feedback does not imply runtime safety; S4 performs AST enforcement. */
export function CodeEditor({ value, editing, onChange }: CodeEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const editable = useRef(new Compartment());
  onChangeRef.current = onChange;
  const diagnostic = useMemo(() => {
    return codeSourceIssues(value)[0] ?? null;
  }, [value]);

  useEffect(() => {
    if (!hostRef.current) return;
    const view = new EditorView({
      state: EditorState.create({
        doc: value,
        extensions: [
          python(),
          linter((view) =>
            codeSourceIssues(view.state.doc.toString()).map((message) => ({
              from: 0,
              to: view.state.doc.length,
              severity: 'error' as const,
              message,
            })),
          ),
          editorTheme,
          editable.current.of(EditorView.editable.of(editing)),
          EditorView.updateListener.of((update) => {
            if (update.docChanged)
              onChangeRef.current(update.state.doc.toString());
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
    // Initial document is captured once; later changes are dispatched below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || view.state.doc.toString() === value) return;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: value },
    });
  }, [value]);

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: editable.current.reconfigure(EditorView.editable.of(editing)),
    });
  }, [editing]);

  return (
    <div className="flex flex-col gap-2" data-testid="code-editor">
      <div
        ref={hostRef}
        aria-label="Python source"
        aria-invalid={Boolean(diagnostic)}
      />
      {diagnostic && (
        <Alert
          variant="warning"
          appearance="light"
          size="sm"
          data-testid="code-syntax-diagnostic"
        >
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertDescription>{diagnostic}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/** Mirrors the runner's language policy (`code_runner/policy.py`
 * CAPABILITIES) - the backend serves the live list via workflow metadata so
 * the editor never drifts from what the deployed runner actually allows. */
export const CODE_CAPABILITIES_FALLBACK = [
  'Read-only `input` dictionary of the mapped values',
  'Assign a JSON dictionary to `result`',
  'Pure builtins: abs, all, any, bool, dict, enumerate, filter, float, int, len, list, map, max, min, range, round, set, sorted, str, sum, tuple, zip, print',
  'Helpers: json, math, re',
  'No imports, files, network, environment, subprocesses, or reflection',
];

export interface CodeCapabilitiesProps {
  items?: string[];
}

export function CodeCapabilities({ items }: CodeCapabilitiesProps) {
  const list = items && items.length ? items : CODE_CAPABILITIES_FALLBACK;
  return (
    <ul
      className="grid gap-1 text-xs text-muted-foreground"
      data-testid="code-capabilities"
    >
      {list.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
