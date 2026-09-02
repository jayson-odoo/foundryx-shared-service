'use client';

import { useParams } from 'next/navigation';
import { Container } from '@/components/common/container';
import { RequirePlatformPermission } from '@/components/common/require-platform-permission';
import { PromptDetailView } from './prompt-detail-view';

const PROMPTS_PERMISSION = 'ai_prompts.manage';

export default function AiPromptDetailPage() {
  const params = useParams();

  return (
    <RequirePlatformPermission permission={PROMPTS_PERMISSION}>
      <Container width="fluid">
        <PromptDetailView name={String(params.name)} />
      </Container>
    </RequirePlatformPermission>
  );
}
