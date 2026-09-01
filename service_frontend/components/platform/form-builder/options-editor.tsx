'use client';

/**
 * Choice-options editor (plan sprint-3/01 D8) - value+label rows with
 * add/remove/reorder; value auto-derives from the label slug on add. Shared by
 * choice fields and repeater sub-fields. Pure presentation over `doc-ops`.
 */
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { FormChoiceItem } from '@/types/forms';

export interface OptionsEditorProps {
  items: FormChoiceItem[];
  onAdd: () => void;
  onUpdate: (index: number, patch: Partial<FormChoiceItem>) => void;
  onRemove: (index: number) => void;
  onMove: (index: number, direction: -1 | 1) => void;
}

export function OptionsEditor({ items, onAdd, onUpdate, onRemove, onMove }: OptionsEditorProps) {
  return (
    <div className="flex flex-col gap-1.5" data-testid="options-editor">
      {items.map((item, index) => (
        <div key={index} className="flex items-center gap-1">
          <Input
            value={item.label}
            placeholder="Label"
            aria-label={`Option ${index + 1} label`}
            data-testid={`option-label-${index}`}
            onChange={(e) => onUpdate(index, { label: e.target.value })}
            className="h-8 flex-1 text-xs"
          />
          <Input
            value={item.value}
            placeholder="value"
            aria-label={`Option ${index + 1} value`}
            data-testid={`option-value-${index}`}
            onChange={(e) => onUpdate(index, { value: e.target.value })}
            className="h-8 w-24 font-mono text-xs"
          />
          <div className="flex flex-col">
            <button
              type="button"
              aria-label="Move option up"
              disabled={index === 0}
              onClick={() => onMove(index, -1)}
              className="text-muted-foreground hover:text-foreground disabled:opacity-30"
            >
              <ChevronUp className="size-3.5" />
            </button>
            <button
              type="button"
              aria-label="Move option down"
              disabled={index === items.length - 1}
              onClick={() => onMove(index, 1)}
              className="text-muted-foreground hover:text-foreground disabled:opacity-30"
            >
              <ChevronDown className="size-3.5" />
            </button>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 text-destructive"
            aria-label="Remove option"
            data-testid={`option-remove-${index}`}
            onClick={() => onRemove(index)}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 self-start text-xs"
        data-testid="option-add"
        onClick={onAdd}
      >
        <Plus className="size-3.5" /> Add option
      </Button>
    </div>
  );
}
