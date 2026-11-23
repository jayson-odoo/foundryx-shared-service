/**
 * Switch-off parity: Button and Input (see parity-utils.ts). Fixed props,
 * rendered with the Foundryx UIUX switch off (no provider = off).
 */
import { render } from '@testing-library/react';
import { Plus } from 'lucide-react';
import { describe, expect, it } from 'vitest';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { parityHtml } from './parity-utils';

describe('parity (switch off): Button', () => {
  it('renders every variant as before', () => {
    const { container } = render(
      <div>
        <Button>Add user</Button>
        <Button variant="primary">Save user</Button>
        <Button variant="destructive">Delete user</Button>
        <Button variant="outline">Export users</Button>
        <Button variant="ghost" mode="icon" aria-label="Add">
          <Plus />
        </Button>
        <Button variant="mono" size="sm">
          Small
        </Button>
        <Button disabled>Disabled action</Button>
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Input', () => {
  it('renders the plain, sized and invalid inputs as before', () => {
    const { container } = render(
      <div>
        <Input placeholder="Name" defaultValue="Alpha" />
        <Input variant="sm" placeholder="Small" />
        <Input variant="lg" type="number" defaultValue={3} />
        <Input aria-invalid="true" defaultValue="bad" />
        <Input disabled defaultValue="locked" />
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
