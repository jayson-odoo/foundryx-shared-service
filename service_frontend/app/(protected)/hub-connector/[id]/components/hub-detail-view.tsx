'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Info, LoaderCircleIcon, RefreshCw, Send, History, KeyRound, Users, KeySquare } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from '@/lib/toast';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { RecordHistory } from '@/components/platform/record-history';
import { ClampedText } from '@/components/platform/clamped-text';
import { OneTimeSecret } from '@/components/platform/one-time-secret';
import { FormRow, ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import { ResourceList } from '@/components/platform/resource-list';
import type { ResourceAction } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { hubConnectorErrorMessage, useHub } from '@/hooks/use-hub-connector';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { Hub, HubCustomer } from '@/types/hub-connector';
import {
  HUBS_PATH,
  HUB_ACTIVE_REGISTRY,
  HUB_KEYS_MANAGE,
  HUB_MANAGE,
  hubActiveStatus,
} from '../../components/hub-meta';
import { HUB_DELETE_ACTION } from '../../components/use-hubs-list-config';
import { HubKeysDialog } from '../../components/hub-keys-dialog';
import { CustomerDialog } from './customer-dialog';
import { PreviewDialog } from './preview-dialog';
import { useCustomersListConfig } from './use-customers-list-config';
import { useDeliveriesListConfig } from './use-deliveries-list-config';

export function HubDetailView({ hubId }: { hubId: string }) {
  const { hub, isLoading, notFound, reload } = useHub(hubId);
  const form = useForm({ mode: 'onTouched' });

  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [exposePrice, setExposePrice] = useState(false);
  const [active, setActive] = useState(true);
  const [secret, setSecret] = useState<string | null>(null);
  const [customerOpen, setCustomerOpen] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState<HubCustomer | null>(null);
  const [previewing, setPreviewing] = useState<HubCustomer | null>(null);
  const [keysOpen, setKeysOpen] = useState(false);
  const [customersKey, setCustomersKey] = useState(0);
  // Remounts the History tab after any save or action on this page.
  const [historyVersion, setHistoryVersion] = useState(0);
  const bumpHistory = useCallback(() => setHistoryVersion((v) => v + 1), []);
  const loadHistory = useCallback(() => hubConnectorService.hubHistory(hubId), [hubId]);

  const loaded = hub;
  const seed = useCallback((h: Hub) => {
    setName(h.name);
    setUrl(h.callbackUrl ?? '');
    setExposePrice(h.exposePrice);
    setActive(h.active);
  }, []);
  useEffect(() => {
    if (loaded) seed(loaded);
  }, [loaded, seed]);

  const dirty =
    !!loaded &&
    (name.trim() !== loaded.name ||
      url.trim() !== (loaded.callbackUrl ?? '') ||
      exposePrice !== loaded.exposePrice ||
      active !== loaded.active);

  const onSave = useCallback(async (): Promise<boolean> => {
    if (!name.trim()) {
      toast.error('Name is required.');
      return false;
    }
    try {
      await hubConnectorService.updateHub(hubId, {
        name: name.trim(),
        callbackUrl: url.trim(),
        exposePrice,
        active,
      });
      toast.success('Hub saved.');
      reload();
      bumpHistory();
      return true;
    } catch (err) {
      toast.error(hubConnectorErrorMessage(err, 'Could not save the hub. Please try again.'));
      return false;
    }
  }, [active, bumpHistory, exposePrice, hubId, name, reload, url]);

  const onCancel = useCallback(() => {
    if (loaded) seed(loaded);
  }, [loaded, seed]);

  const openAdd = useCallback(() => {
    setEditingCustomer(null);
    setCustomerOpen(true);
  }, []);
  const openEdit = useCallback((row: HubCustomer) => {
    setEditingCustomer(row);
    setCustomerOpen(true);
  }, []);
  const openPreview = useCallback((row: HubCustomer) => setPreviewing(row), []);

  const customersConfig = useCustomersListConfig({
    hubId,
    onCreate: openAdd,
    onEdit: openEdit,
    onPreview: openPreview,
    refreshKey: customersKey,
  });
  const deliveriesConfig = useDeliveriesListConfig(hubId);

  const config = useMemo<ResourceFormConfig<Hub> | null>(() => {
    if (!loaded) return null;
    const actions: ResourceAction<Hub>[] = [
      {
        id: 'rotate-secret',
        label: 'Rotate signing secret',
        icon: KeyRound,
        permission: HUB_MANAGE,
        surfaces: { form: true },
        run: async () => {
          try {
            const res = await hubConnectorService.rotateSecret(hubId);
            setSecret(res.signingSecret);
            bumpHistory();
          } catch (err) {
            toast.error(hubConnectorErrorMessage(err, 'Could not rotate the secret. Please try again.'));
          }
        },
      },
      {
        id: 'resync',
        label: 'Resync all customers',
        icon: RefreshCw,
        permission: HUB_MANAGE,
        surfaces: { form: true },
        run: async () => {
          try {
            const res = await hubConnectorService.resync(hubId);
            bumpHistory();
            toast.success(`Queued ${res.queued} customer${res.queued === 1 ? '' : 's'} to send again.`);
          } catch (err) {
            toast.error(hubConnectorErrorMessage(err, 'Could not resync. Please try again.'));
          }
        },
      },
      {
        id: 'hub-keys',
        label: 'Hub keys',
        icon: KeySquare,
        permission: HUB_KEYS_MANAGE,
        surfaces: { form: true },
        run: () => setKeysOpen(true),
      },
      HUB_DELETE_ACTION,
    ];

    return {
      breadcrumb: [
        { label: 'Hub Connector' },
        { label: 'Hubs', href: HUBS_PATH },
        { label: loaded.name },
      ],
      backHref: HUBS_PATH,
      title: loaded.name,
      subtitle: loaded.code,
      entityNoun: 'hub',
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col py-2">
              <FormRow label="Name" required>
                {editing ? (
                  <Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
                ) : (
                  <ClampedText text={loaded.name} lines={2} />
                )}
              </FormRow>
              <FormRow label="Code">
                <span className="font-mono text-sm">{loaded.code}</span>
              </FormRow>
              <FormRow label="Receiver URL">
                {editing ? (
                  <Input value={url} type="url" inputMode="url" maxLength={500} onChange={(e) => setUrl(e.target.value)} />
                ) : (
                  <ClampedText text={loaded.callbackUrl ?? '-'} lines={2} />
                )}
              </FormRow>
              <FormRow label="Show price">
                {editing ? (
                  <Switch checked={exposePrice} onCheckedChange={setExposePrice} aria-label="Show price" />
                ) : (
                  <span>{loaded.exposePrice ? 'Yes' : 'No'}</span>
                )}
              </FormRow>
              <FormRow label="Active">
                {editing ? (
                  <Switch checked={active} onCheckedChange={setActive} aria-label="Active" />
                ) : (
                  <div className="flex items-start">
                    <StatusBadge status={hubActiveStatus(loaded.active)} registry={HUB_ACTIVE_REGISTRY} />
                  </div>
                )}
              </FormRow>
            </div>
          ),
        },
        {
          id: 'customers',
          label: 'Customers',
          icon: Users,
          render: () => (
            <div className="py-2">
              <ResourceList config={customersConfig} hideHeader />
            </div>
          ),
        },
        {
          id: 'deliveries',
          label: 'Deliveries',
          icon: Send,
          render: () => (
            <div className="py-2">
              <ResourceList config={deliveriesConfig} hideHeader />
            </div>
          ),
        },
        {
          id: 'history',
          label: 'History',
          icon: History,
          render: () => <RecordHistory key={historyVersion} viewKey="hub-connector.hub.history" load={loadHistory} />,
        },
      ],
      initialTabId: 'details',
      compactTabs: true,
      actions,
      actionRows: [loaded],
      onReload: reload,
      editable: true,
      editPermission: HUB_MANAGE,
      isDirty: dirty,
      onSave,
      onCancel,
    };
  }, [active, bumpHistory, customersConfig, deliveriesConfig, dirty, exposePrice, historyVersion, hubId, loadHistory, loaded, name, onCancel, onSave, reload, url]);

  if (isLoading && !hub) {
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
          <p className="text-sm font-medium">Hub not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={HUBS_PATH}>Back to hubs</Link>
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
      <CustomerDialog
        hubId={hubId}
        open={customerOpen}
        customer={editingCustomer}
        onOpenChange={setCustomerOpen}
        onSaved={() => {
          setCustomersKey((k) => k + 1);
          bumpHistory();
          reload();
        }}
      />
      <HubKeysDialog hubId={hubId} open={keysOpen} onOpenChange={(o) => {
          setKeysOpen(o);
          if (!o) bumpHistory();
        }}
      />
      <PreviewDialog hubId={hubId} customer={previewing} showPrice={loaded?.exposePrice ?? false} onClose={() => setPreviewing(null)} />
      <Dialog open={secret !== null} onOpenChange={(o) => !o && setSecret(null)}>
        <DialogContent className="max-w-lg" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>New signing secret</DialogTitle>
          </DialogHeader>
          <DialogBody>{secret && <OneTimeSecret value={secret} label="Signing secret" />}</DialogBody>
          <DialogFooter>
            <Button variant="primary" onClick={() => setSecret(null)}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Container>
  );
}
