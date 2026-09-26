/**
 * Issue #90 W1 (AC-90-108) - the "what happens next" line for the idea's
 * current status. Backend-derived (single source, white-label copy) - this
 * just renders whatever string the API sent.
 */
import { Card, CardContent } from '@/components/ui/card';

export interface NextStepCalloutProps {
  nextStep: string;
}

export function NextStepCallout({ nextStep }: NextStepCalloutProps) {
  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardContent className="py-4">
        <p className="text-sm">{nextStep}</p>
      </CardContent>
    </Card>
  );
}
