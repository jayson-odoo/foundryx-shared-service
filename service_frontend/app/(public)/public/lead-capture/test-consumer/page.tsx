import { notFound } from 'next/navigation';
import { testConsumerConfig } from '@/lib/lead-capture-test-consumer';
import { TestConsumer } from './test-consumer';

export const dynamic = 'force-dynamic';

/**
 * TEST CONSUMER (hand tests only, plan 64 L-C): a stand-in product page with
 * a "Connect a source" button and the leads it received. 404 unless the test
 * copy switched it on (`lib/lead-capture-test-consumer.ts`); production never
 * does.
 */
export default function LeadCaptureTestConsumerPage() {
  if (!testConsumerConfig()) notFound();
  return <TestConsumer />;
}
