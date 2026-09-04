'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ResourceList } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { whatsappTemplateService } from '@/services/whatsapp-template-service';
import { toMetaComponents, fromMetaComponents } from '@/lib/whatsapp-template';
import type { TemplateManageItem } from '@/types/whatsapp-template';
import { useTemplateList } from './use-template-list';
import { templateNewPath, templateEditPath } from './paths';

/** Templates tab - embedded ResourceList + Sync + the two-pane builder route. */
export function ChannelTemplatesTab({ channelId }: { channelId: string }) {
  const router = useRouter();
  const { can } = useCan();
  const canManage = can('wa_templates.manage');
  const [reloadKey, setReloadKey] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [payloadOf, setPayloadOf] = useState<TemplateManageItem | null>(null);
  const [payloadJson, setPayloadJson] = useState('');

  const onSubmitTemplate = useCallback(
    () => router.push(templateNewPath(channelId)),
    [router, channelId],
  );
  const onEdit = useCallback(
    (id: string) => router.push(templateEditPath(channelId, id)),
    [router, channelId],
  );
  const onViewPayload = useCallback(
    async (item: TemplateManageItem) => {
      setPayloadOf(item);
      setPayloadJson('Loading…');
      try {
        const detail = await whatsappTemplateService.get(channelId, item.id);
        // Render the canonical Meta component array (View payload, BR-12).
        const components =
          detail.components && detail.components.length
            ? detail.components
            : toMetaComponents(
                detail.doc ??
                  fromMetaComponents([], {
                    name: item.name,
                    category: (item.category as 'MARKETING' | 'UTILITY') || 'UTILITY',
                    language: item.language || 'en_US',
                  }),
              );
        setPayloadJson(JSON.stringify(components, null, 2));
      } catch {
        setPayloadJson('Could not load payload.');
      }
    },
    [channelId],
  );

  const { config } = useTemplateList(channelId, onSubmitTemplate, onEdit, onViewPayload);

  const runSync = async () => {
    setSyncing(true);
    try {
      await whatsappTemplateService.sync(channelId);
      toast.success('Templates synced from Meta.');
      setReloadKey((k) => k + 1);
    } catch {
      toast.error('Could not sync templates. Please try again.');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {canManage && (
        <div className="flex justify-end">
          <Button variant="outline" size="sm" onClick={runSync} disabled={syncing}>
            {syncing ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            {syncing ? 'Syncing…' : 'Sync'}
          </Button>
        </div>
      )}

      <ResourceList key={reloadKey} config={config} hideHeader />

      <Dialog open={payloadOf !== null} onOpenChange={(o) => !o && setPayloadOf(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Template payload - {payloadOf?.name}</DialogTitle>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3 text-xs">
            {payloadJson}
          </pre>
        </DialogContent>
      </Dialog>
    </div>
  );
}
