'use client';

import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DynamicContentField, type DynamicContentGroup } from './dynamic-content-picker';
import type { WorkflowCodeInput } from '@/types/workflows';

export interface CodeInputsEditorProps {
  inputs: WorkflowCodeInput[];
  groups: DynamicContentGroup[];
  editing: boolean;
  onChange: (inputs: WorkflowCodeInput[]) => void;
}

export function CodeInputsEditor({ inputs, groups, editing, onChange }: CodeInputsEditorProps) {
  return (
    <div className="flex flex-col gap-2" data-testid="code-inputs-editor">
      {inputs.map((input, index) => (
        <div key={index} className="flex items-start gap-1.5">
          <Input
            value={input.key}
            disabled={!editing}
            aria-label={`Code input ${index + 1} key`}
            placeholder="name"
            onChange={(event) =>
              onChange(inputs.map((row, rowIndex) => rowIndex === index ? { ...row, key: event.target.value } : row))
            }
            className="w-28 shrink-0"
          />
          <DynamicContentField
            value={input.value}
            groups={groups}
            disabled={!editing}
            aria-label={`Code input ${index + 1} value`}
            placeholder="Value"
            onChange={(value) =>
              onChange(inputs.map((row, rowIndex) => rowIndex === index ? { ...row, value } : row))
            }
          />
          {editing && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 text-destructive"
              aria-label={`Remove code input ${index + 1}`}
              onClick={() => onChange(inputs.filter((_, rowIndex) => rowIndex !== index))}
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      ))}
      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="add-code-input"
          onClick={() => onChange([...inputs, { key: '', value: '' }])}
        >
          <Plus className="size-3.5" /> Add input
        </Button>
      )}
      {!inputs.length && !editing && <p className="text-xs text-muted-foreground">No input mappings.</p>}
    </div>
  );
}
