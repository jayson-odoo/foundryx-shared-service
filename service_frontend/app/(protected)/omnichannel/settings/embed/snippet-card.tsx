'use client';

import { useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select/search-select';
import type { EmbedWorkspaceOption } from '@/services/embed-config-service';
import { CopyField } from './copy-field';

/**
 * `mode: 'embed'` (default) builds the iframe snippet from a workspace + a
 * route picker (below). `mode: 'raw'` (plan 34 / A7b Widget tab, AC-WEB-05)
 * skips the builder entirely and renders EXACTLY the string the caller
 * supplies (the backend-served `<script>` install snippet - no workspace or
 * route concept applies to it) through the same `CopyField`.
 */
export type SnippetCardProps =
  | { mode?: 'embed'; host: string; connectionId: string; workspaces: EmbedWorkspaceOption[] }
  | { mode: 'raw'; title: string; description: string; snippet: string };

type EmbedRoute = 'thread' | 'thread-full' | 'inbox';

const ROUTE_OPTIONS = [
  { value: 'thread', label: 'Compact thread' },
  { value: 'thread-full', label: 'Full thread' },
  { value: 'inbox', label: 'Full inbox' },
];

/** Build the iframe snippet for the chosen route + workspace. The assertion (minted
 * on the consumer's backend) carries the workspaceId - surfaced here as a comment
 * so the consumer knows which id to sign. */
export function buildSnippet(
  host: string,
  connectionId: string,
  route: EmbedRoute,
  workspaceId: string,
): string {
  const src = `${host.replace(/\/$/, '')}/embed/omnichannel/${route}?c=${connectionId}`;
  return [
    `<!-- workspaceId for your assertion: ${workspaceId || '<workspace-id>'} -->`,
    `<iframe`,
    `  src="${src}"`,
    `  style="width:100%; height:100%; border:0;"`,
    `  allow="clipboard-write">`,
    `</iframe>`,
  ].join('\n');
}

/**
 * The iframe snippet builder - pick a workspace + a route (single thread / full
 * inbox) and copy the ready-to-paste `<iframe>`. The connection id rides the
 * `?c=` param; the assertion (minted on the consumer's own backend) carries the
 * workspace + scope.
 */
export function SnippetCard(props: SnippetCardProps) {
  const isRaw = props.mode === 'raw';
  const embedWorkspaces = isRaw ? [] : props.workspaces;
  const embedHost = isRaw ? '' : props.host;
  const embedConnectionId = isRaw ? '' : props.connectionId;

  const [route, setRoute] = useState<EmbedRoute>('thread');
  const [workspaceId, setWorkspaceId] = useState<string>(embedWorkspaces[0]?.id ?? '');

  // The embed pages (`/embed/omnichannel/*`) are served by THIS Next app, so the
  // iframe host is the frontend origin - NOT the backend `host` (public_base_url,
  // which may be a different port/prefix and has no embed *page* routes). Fall
  // back to `host` only for SSR where `window` is absent.
  const embedOrigin = typeof window !== 'undefined' ? window.location.origin : embedHost;

  const builtSnippet = useMemo(
    () => buildSnippet(embedOrigin, embedConnectionId, route, workspaceId),
    [embedOrigin, embedConnectionId, route, workspaceId],
  );

  if (isRaw) {
    return (
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>{props.title}</CardTitle>
            <CardDescription>{props.description}</CardDescription>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <CopyField value={props.snippet} ariaLabel={props.title} multiline />
        </CardContent>
      </Card>
    );
  }

  const workspaceOptions = embedWorkspaces.map((w) => ({ value: w.id, label: w.name }));

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Iframe snippet</CardTitle>
          <CardDescription>Paste this into the page that hosts the widget.</CardDescription>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label>Workspace</Label>
            <SearchSelect
              options={workspaceOptions}
              value={workspaceId}
              onChange={setWorkspaceId}
              ariaLabel="Snippet workspace"
              placeholder="Select a workspace…"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>View</Label>
            <SearchSelect
              options={ROUTE_OPTIONS}
              value={route}
              onChange={(v) => setRoute(v as EmbedRoute)}
              ariaLabel="Snippet view"
            />
          </div>
        </div>
        <CopyField value={builtSnippet} ariaLabel="iframe snippet" multiline />
      </CardContent>
    </Card>
  );
}
