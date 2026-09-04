'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { Settings as SettingsIcon, MessageSquareText, IdCard, Webhook } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ListQuery } from '@/types/resource';
import { useCan } from '@/hooks/use-can';
import { channelService } from '@/services/channel-service';
import { ApiError } from '@/lib/api-client';
import type { Channel, ChannelProfile } from '@/types/omnichannel';
import { ConfigurationTab } from './channel-form-fields';
import { ChannelProfileTab } from './channel-profile-tab';
import { ChannelTemplatesTab } from './channel-templates-tab';
import { ChannelWebhooksTab } from './channel-webhooks-tab';
import { useChannelActions } from './use-channel-actions';
import { channelFormHref, channelsListPath } from './paths';
import { channelDetailSchema, type ChannelDetailValues } from './channel-schema';

function toFormValues(channel: Channel | null, profile: ChannelProfile | null): ChannelDetailValues {
  return {
    name: channel?.name ?? '',
    isActive: channel?.isActive ?? false,
    about: profile?.about ?? '',
    address: profile?.address ?? '',
    description: profile?.description ?? '',
    email: profile?.email ?? '',
    vertical: profile?.vertical ?? '',
    website1: profile?.website1 ?? '',
    website2: profile?.website2 ?? '',
  };
}

export interface UseChannelFormResult {
  config: ResourceFormConfig<Channel> | null;
  form: UseFormReturn<ChannelDetailValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** Loads the channel + profile, wires one RHF form, assembles the 3-tab config. */
export function useChannelForm(channelId: string, initialEditing: boolean): UseChannelFormResult {
  const actions = useChannelActions();
  const { can } = useCan();
  const canReadWebhooks = can('webhooks.read');
  const [channel, setChannel] = useState<Channel | null>(null);
  const [profile, setProfile] = useState<ChannelProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<ChannelDetailValues>({
    resolver: zodResolver(channelDetailSchema),
    defaultValues: toFormValues(null, null),
  });

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    Promise.all([channelService.get(channelId), channelService.getProfile(channelId)])
      .then(([c, p]) => {
        if (!active) return;
        setChannel(c);
        setProfile(p);
        form.reset(toFormValues(c, p));
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId]);

  // Stable across renders (fix round 2, AC-DLA-30/31 D7) - see use-user-form.tsx.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      channelService.getAt(query, index).then((r) => ({
        recordId: r.channel?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => channelFormHref(recordId, { ctx, index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<Channel> | null>(() => {
    if (isLoading || notFound) return null;

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        // Channel fields (our data). Reflect the result immediately so a later
        // profile-save failure can't leave a stale channel header/name on screen.
        const updatedChannel = await channelService.update(channelId, {
          name: values.name,
          isActive: values.isActive,
        });
        setChannel(updatedChannel);
        // Profile fields (write-through). Backend diffs vs its mirror so only
        // genuinely-changed fields are POSTed to Meta (BR-6).
        try {
          const updatedProfile = await channelService.saveProfile(channelId, {
            about: values.about ?? '',
            address: values.address ?? '',
            description: values.description ?? '',
            email: values.email ?? '',
            vertical: values.vertical ?? '',
            website1: values.website1 ?? '',
            website2: values.website2 ?? '',
          });
          setProfile(updatedProfile);
          form.reset(toFormValues(updatedChannel, updatedProfile));
          toast.success('Channel saved.');
          ok = true;
        } catch (err) {
          // Map server-side 422 field errors back onto the inputs (BR-8).
          if (err instanceof ApiError && err.status === 422) {
            const fieldErrors = (err.detail as { fieldErrors?: Record<string, string> } | undefined)
              ?.fieldErrors;
            if (fieldErrors) {
              for (const [field, message] of Object.entries(fieldErrors)) {
                form.setError(field as keyof ChannelDetailValues, { message });
              }
              toast.error('Please fix the highlighted fields.');
              return;
            }
          }
          toast.error('Could not save the profile. Your changes are kept - please retry.');
        }
      })();
      return ok;
    };

    const onCancel = () => form.reset(toFormValues(channel, profile));

    // Sync Profile pulls fresh data from Meta - reflect it in the editable
    // inputs too (not just the read view), else a later Edit shows stale values
    // and a Save would clobber the freshly-synced profile. Preserve any pending
    // channel-name / active edits.
    const handleProfileSynced = (p: ChannelProfile) => {
      setProfile(p);
      form.reset(
        {
          ...form.getValues(),
          about: p.about ?? '',
          address: p.address ?? '',
          description: p.description ?? '',
          email: p.email ?? '',
          vertical: p.vertical ?? '',
          website1: p.website1 ?? '',
          website2: p.website2 ?? '',
        },
        { keepDirty: false },
      );
    };

    const tabs = [
      {
        id: 'configuration',
        label: 'Configuration',
        icon: SettingsIcon,
        render: ({ editing }: { editing: boolean }) => (
          <ConfigurationTab
            form={form}
            editing={editing}
            channel={channel}
            onChannelSynced={setChannel}
          />
        ),
      },
      {
        id: 'templates',
        label: 'Templates',
        icon: MessageSquareText,
        render: () => <ChannelTemplatesTab channelId={channelId} />,
      },
      {
        id: 'profile',
        label: 'Profile',
        icon: IdCard,
        render: ({ editing }: { editing: boolean }) => (
          <ChannelProfileTab
            form={form}
            editing={editing}
            channel={channel}
            profile={profile}
            onProfileSynced={handleProfileSynced}
          />
        ),
      },
      ...(canReadWebhooks
        ? [
            {
              id: 'webhooks',
              label: 'Webhooks',
              icon: Webhook,
              render: () => <ChannelWebhooksTab channelId={channelId} />,
            },
          ]
        : []),
    ];

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Omnichannel', href: channelsListPath },
        { label: 'Channels', href: channelsListPath },
        { label: channel?.name ?? 'Channel' },
      ],
      backHref: channelsListPath,
      backLabel: 'Back to channels',
      title: channel?.name ?? 'Channel',
      subtitle: channel?.displayPhoneNumber ?? undefined,
      tabs,
      initialTabId: 'configuration',
      actions,
      actionRows: channel ? [channel] : [],
      editable: true,
      editPermission: 'channels.manage',
      initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [
    isLoading,
    notFound,
    channel,
    profile,
    actions,
    form,
    initialEditing,
    channelId,
    canReadWebhooks,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}
