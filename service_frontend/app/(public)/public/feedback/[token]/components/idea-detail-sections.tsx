/**
 * Issue #90 W1 (AC-90-104/110) - problem/solution/impact/department as
 * labelled sections. Labels match `idea-form-fields.tsx` exactly ("Problem
 * statement" / "Proposed solution" / "Impact" / "Department") - the SAME
 * words an operator sees. Every section ALWAYS renders (design-language s6):
 * a blank field shows "Not provided", never omission - an idea missing a
 * field must never look like the page is broken.
 */
import { Card, CardContent } from '@/components/ui/card';

export interface IdeaDetailSectionsProps {
  problem: string | null;
  proposedSolution: string | null;
  impact: string | null;
  department: string | null;
}

const NOT_PROVIDED = 'Not provided';

function Section({ label, value }: { label: string; value: string | null }) {
  return (
    <Card>
      <CardContent className="space-y-1 py-4">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        <p className={value ? 'whitespace-pre-wrap text-sm' : 'text-sm text-muted-foreground'}>
          {value || NOT_PROVIDED}
        </p>
      </CardContent>
    </Card>
  );
}

export function IdeaDetailSections({
  problem,
  proposedSolution,
  impact,
  department,
}: IdeaDetailSectionsProps) {
  return (
    <div className="flex flex-col gap-3">
      <Section label="Problem statement" value={problem} />
      <Section label="Proposed solution" value={proposedSolution} />
      <Section label="Impact" value={impact} />
      <Section label="Department" value={department} />
    </div>
  );
}
