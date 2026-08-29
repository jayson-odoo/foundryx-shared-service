'use client';

import { useMemo } from 'react';
import { Alert, AlertDescription, AlertIcon } from '@/components/ui/alert';
import { Textarea } from '@/components/ui/textarea';
import { TriangleAlert } from 'lucide-react';
import { codeSourceIssues } from '@/lib/workflow-doc';

export interface CodeEditorProps {
  value: string;
  editing: boolean;
  onChange: (value: string) => void;
}

/** Small maintained Python editor for the first slice. It deliberately keeps
 * diagnostics conservative: static checks identify obvious unsupported syntax
 * without implying that runtime safety or success has been proven. */
export function CodeEditor({ value, editing, onChange }: CodeEditorProps) {
  const diagnostic = useMemo(() => {
    return codeSourceIssues(value)[0] ?? null;
  }, [value]);

  return (
    <div className="flex flex-col gap-2" data-testid="code-editor">
      <Textarea
        value={value}
        disabled={!editing}
        onChange={(event) => onChange(event.target.value)}
        aria-label="Python source"
        aria-invalid={Boolean(diagnostic)}
        placeholder="result = {}"
        rows={10}
        className="font-mono text-xs leading-5"
      />
      {diagnostic && (
        <Alert variant="warning" appearance="light" size="sm" data-testid="code-syntax-diagnostic">
          <AlertIcon><TriangleAlert /></AlertIcon>
          <AlertDescription>{diagnostic}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

export function CodeCapabilities() {
  return (
    <ul className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2" data-testid="code-capabilities">
      <li>Python</li>
      <li>JSON input</li>
      <li>Declared outputs</li>
      <li>No network or filesystem</li>
    </ul>
  );
}
