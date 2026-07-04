'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useChannelForm } from './use-channel-form';
import { channelsListPath } from './paths';

export interface ChannelFormViewProps {
  channelId: string;
  initialEditing: boolean;
}

/** Loads + renders a channel detail form (read by default, global Edit toggle). */
export function ChannelFormView({ channelId, initialEditing }: ChannelFormViewProps) {
  const { config, form, isLoading, notFound } = useChannelForm(channelId, initialEditing);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Channel not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={channelsListPath}>Back to channels</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
