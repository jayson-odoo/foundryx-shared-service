'use client';

/**
 * Public Lead Capture guide (lane META-LEADS-GUIDE-PAGE, owner-approved mock
 * v2): one page for a partner app's developers and for its customer. No
 * login; content lives in `lib/lead-capture-guide.ts`; screenshots + video
 * come from `npm run capture:lead-capture-guide`.
 */
import Image from 'next/image';
import { AlertTriangle } from 'lucide-react';
import { Alert, AlertDescription, AlertIcon } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { BrandMark } from '@/components/platform/branding';
import { StatusBadge } from '@/components/platform/status-badge';
import { SOURCE_STATUS_REGISTRY } from '@/app/(protected)/lead-capture/sources/components/source-status';
import {
  GUIDE_PROBLEMS,
  LEAD_FIELD_MAP,
  SAMPLE_PARTNER_ORIGIN,
  customerSteps,
  developerSamples,
  type CustomerStep,
} from '@/lib/lead-capture-guide';
import shots from '@/lib/lead-capture-guide-shots.json';
import type { LeadSourceStatus } from '@/types/lead-capture-wizard';
import type { PublicBranding } from '@/types/branding';
import { CodeSample } from './code-sample';

export interface LeadCaptureGuideProps {
  /** The host tenant's name (one tenant = one partner app); null = generic. */
  partnerName: string | null;
  /** `<backend>/api/v1/lead-capture`, resolved on the server. */
  apiBase: string;
  branding?: PublicBranding | null;
}

interface ShotBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface Shot {
  file: string;
  width: number;
  height: number;
  /** The shot is shown down to here (the wizard's content end). */
  visibleHeight?: number;
  box: ShotBox | null;
}

const SHOTS = shots.steps as Record<string, Shot>;

/** The wizard's one message to the opener (`types/lead-capture-wizard.ts:111-114`). */
const POPUP_MESSAGES: ReadonlyArray<{ type: string; when: string }> = [
  { type: 'lead-capture:done', when: 'Finished; the Page passed its test lead and is Live. Always has sourceId.' },
  { type: 'lead-capture:closed', when: 'Closed before the end. Has sourceId once a Page was connected.' },
];

export interface GuideSectionProps {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}

export interface GuideTextProps {
  children: React.ReactNode;
}

export interface StepShotProps {
  step: CustomerStep;
  number: number;
}

function Section({ eyebrow, title, children }: GuideSectionProps) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{eyebrow}</span>
        <h2 className="font-heading text-lg font-semibold text-foreground">{title}</h2>
        {children}
      </CardContent>
    </Card>
  );
}

function Sub({ children }: GuideTextProps) {
  return <h3 className="mt-2 text-sm font-semibold text-foreground">{children}</h3>;
}

function Note({ children }: GuideTextProps) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function Mono({ children }: GuideTextProps) {
  return <code className="rounded bg-muted px-1 font-mono text-xs text-foreground">{children}</code>;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function pct(part: number, whole: number): string {
  return `${((part / whole) * 100).toFixed(2)}%`;
}

function StepShot({ step, number }: StepShotProps) {
  const shot = step.shot ? SHOTS[step.shot] : undefined;
  if (!shot) return null;
  const visible = Math.min(shot.visibleHeight ?? shot.height, shot.height);
  return (
    <div className="relative border-b border-border bg-muted p-3">
      <div
        className="relative overflow-hidden rounded-md border border-border bg-background"
        style={{ aspectRatio: `${shot.width} / ${visible}` }}
      >
        <Image
          src={`/${shot.file}`}
          alt={`${step.title}: ${step.click}`}
          width={shot.width}
          height={shot.height}
          className="absolute start-0 top-0 h-auto w-full max-w-none"
          sizes="(max-width: 640px) 100vw, 460px"
        />
        {shot.box ? (
          <span
            aria-hidden
            className="pointer-events-none absolute rounded-md ring-4 ring-primary"
            style={{
              left: pct(shot.box.x, shot.width),
              top: pct(shot.box.y, visible),
              width: pct(shot.box.width, shot.width),
              height: pct(shot.box.height, visible),
            }}
          >
            <span className="absolute -start-3 -top-3 flex size-6 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground ring-2 ring-background">
              {number}
            </span>
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function LeadCaptureGuide({ partnerName, apiBase, branding }: LeadCaptureGuideProps) {
  const partner = partnerName?.trim() || 'your app';
  const samples = developerSamples(apiBase);
  const steps = customerSteps(partner);
  const statuses = Object.keys(SOURCE_STATUS_REGISTRY) as LeadSourceStatus[];

  return (
    <main className="flex min-h-screen justify-center bg-background px-4 py-6 sm:py-10">
      <div className="flex w-full min-w-0 max-w-4xl flex-col gap-5">
        {branding ? (
          <header className="flex items-center">
            <BrandMark branding={branding} />
          </header>
        ) : null}

        <div className="flex flex-col gap-1">
          <h1 className="font-heading text-2xl font-semibold text-foreground">Receive Facebook leads in {partner}</h1>
          <p className="text-sm text-muted-foreground">
            What is set up for you, the two things your developers build, and what your customer clicks. All sample
            data on this page is fake.
          </p>
        </div>

        <Alert variant="warning" appearance="light">
          <AlertIcon>
            <AlertTriangle />
          </AlertIcon>
          <AlertDescription>
            Pilot first. Until Meta approves the app for all businesses, only Facebook accounts added as testers can
            connect a Page. Send support the Facebook name of the Page admin before a pilot.
          </AlertDescription>
        </Alert>

        <ol className="grid gap-3 sm:grid-cols-3">
          {[
            'Someone fills in a lead form on a Facebook ad.',
            'Facebook sends it to the Lead Capture service within seconds, which reads and keeps the answers.',
            `${capitalize(partner)} collects the lead: every minute by a scheduled job, or at once by an optional push.`,
          ].map((text, i) => (
            <li key={text} className="flex gap-3 rounded-xl border border-border bg-card p-4">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                {i + 1}
              </span>
              <span className="text-sm text-foreground">{text}</span>
            </li>
          ))}
        </ol>

        <Tabs defaultValue="developers" className="flex min-w-0 flex-col gap-4">
          <TabsList>
            <TabsTrigger value="developers">For developers</TabsTrigger>
            <TabsTrigger value="customer">For your customer</TabsTrigger>
          </TabsList>

          <TabsContent value="developers" className="flex flex-col gap-4">
            <Section eyebrow="Done once for you" title="Setup">
              <ul className="flex list-disc flex-col gap-1 ps-5 text-sm text-foreground">
                <li>Lead Capture is switched on for {partner}.</li>
                <li>
                  Your backend gets one key, <Mono>fxl_live_...</Mono>. Keep it in the backend environment only, never
                  in a browser.
                </li>
                <li>
                  Your web address is listed on that key (for example <Mono>{SAMPLE_PARTNER_ORIGIN}</Mono>), so the
                  Connect window can report back to your page. https only (http only for localhost), no path, at most
                  10.
                </li>
              </ul>
            </Section>

            <Section eyebrow="Built by your developers" title='A. A "Connect Facebook Page" button'>
              <Note>Put it in your app&apos;s settings. When the user clicks it:</Note>
              <Sub>1. Your backend asks for a one-time link</Sub>
              <CodeSample testId="code-connect-session" code={samples.connectSession} />
              <Note>
                The link works once, for 10 minutes: ask for a new one on every click. To reopen it for one Page
                (Reconnect, or new form fields), add <Mono>&quot;sourceId&quot;</Mono> with that Page&apos;s source id.
              </Note>
              <Sub>2. Your page opens it in a popup and waits for one message</Sub>
              <CodeSample testId="code-popup" code={samples.popup} />
              <dl className="flex flex-col divide-y divide-border rounded-lg border border-border text-sm">
                {POPUP_MESSAGES.map((m) => (
                  <div key={m.type} className="flex flex-col gap-1 p-3 sm:flex-row sm:gap-4">
                    <dt className="shrink-0 sm:w-48">
                      <Mono>{m.type}</Mono>
                    </dt>
                    <dd className="text-foreground">{m.when}</dd>
                  </div>
                ))}
              </dl>
              <Sub>3. Show the connected Pages</Sub>
              <Note>
                From <Mono>GET /sources</Mono>: <Mono>pageName</Mono> and <Mono>status</Mono>, shown as:
              </Note>
              <div className="flex flex-wrap gap-2">
                {statuses.map((status) => (
                  <StatusBadge key={status} status={status} registry={SOURCE_STATUS_REGISTRY} />
                ))}
              </div>
            </Section>

            <Section eyebrow="Built by your developers" title="B. One scheduled job that collects leads">
              <Note>Every minute your backend asks for new leads and creates them.</Note>
              <CodeSample testId="code-pull" code={samples.pull} />
              <Note>
                On the very first run use <Mono>?since=2026-11-18T00:00:00Z</Mono> instead of <Mono>cursor</Mono>. The
                answer:
              </Note>
              <CodeSample testId="code-pull-answer" code={samples.pullAnswer} />
              <Sub>The job, in four steps</Sub>
              <ol className="flex list-decimal flex-col gap-2 ps-5 text-sm text-foreground">
                <li>
                  For each item create a lead (status New, source Facebook):
                  <ul className="mt-1 flex flex-col gap-0.5">
                    {LEAD_FIELD_MAP.map((m) => (
                      <li key={m.from}>
                        <Mono>{m.from}</Mono> &rarr; {m.to}
                      </li>
                    ))}
                  </ul>
                </li>
                <li>
                  Save <Mono>id</Mono> on the lead with a unique constraint. If it already exists, skip the item, so a
                  re-run never creates a duplicate.
                </li>
                <li>
                  Save <Mono>nextCursor</Mono> and use it on the next run. An empty first <Mono>since</Mono> page has{' '}
                  <Mono>nextCursor: null</Mono>: call with the same <Mono>since</Mono> again.
                </li>
                <li>
                  If <Mono>hasMore</Mono> is true, call again straight away.
                </li>
              </ol>
              <Note>
                <Mono>isTest: true</Mono> marks Meta&apos;s test lead: show it or skip it. A lead appears in the pull
                about 5 seconds after it is stored.
              </Note>
            </Section>

            <Section eyebrow="Optional, later" title="Faster delivery and your own field names">
              <Sub>Instant push instead of every minute</Sub>
              <Note>Register one backend URL. Keep the secret from the answer: it is shown only once.</Note>
              <CodeSample testId="code-webhook" code={samples.webhook} />
              <Note>
                Each lead is then posted to it the moment it arrives, wrapped in an event. The lead is{' '}
                <Mono>data</Mono>: save it on <Mono>data.id</Mono> (the same id the pull returns), never on the
                event&apos;s own <Mono>id</Mono>, so push and pull never create the lead twice.
              </Note>
              <CodeSample testId="code-webhook-body" code={samples.webhookBody} />
              <Note>Check the signature with the secret over the raw body:</Note>
              <CodeSample testId="code-verify" code={samples.verify} />
              <Note>Answer any 2xx once the lead is saved. Retries run after 1 min, 5 min, 30 min, 2 h, 6 h, 24 h.</Note>
              <Sub>Your own field names</Sub>
              <CodeSample testId="code-fields" code={samples.fields} />
              <Note>
                The Fields step then offers these instead of the default name, phone, email and notes. Types: name,
                phone, email, notes, text; at most 50.
              </Note>
            </Section>
          </TabsContent>

          <TabsContent value="customer" className="flex flex-col gap-4">
            <Note>
              Who: an admin of the Facebook Page that runs the ads, with their own Facebook account. About 2 minutes.
            </Note>

            <video
              controls
              preload="metadata"
              poster={SHOTS.channel ? `/${SHOTS.channel.file}` : undefined}
              className="aspect-video w-full rounded-xl border border-border bg-muted"
              aria-label="Walkthrough of the Connect window"
            >
              <source src={`/${shots.video}`} type="video/webm" />
              <track kind="captions" src={`/${shots.captions}`} srcLang="en" label="English" default />
            </video>

            <ol className="grid items-start gap-4 sm:grid-cols-2">
              {steps.map((step, i) => (
                <li key={step.key} className="flex flex-col overflow-hidden rounded-xl border border-border bg-card">
                  <StepShot step={step} number={i + 1} />
                  <div className="flex flex-col gap-1 p-4">
                    <h3 className="text-sm font-semibold text-foreground">
                      {i + 1}. {step.title}
                    </h3>
                    <p className="text-sm text-muted-foreground">{step.line}</p>
                  </div>
                </li>
              ))}
            </ol>

            <Section eyebrow="If something goes wrong" title="What they might see instead">
              <dl className="flex flex-col divide-y divide-border rounded-lg border border-border text-sm">
                {GUIDE_PROBLEMS.map((p) => (
                  <div key={p.message} className="flex flex-col gap-1 p-3 sm:flex-row sm:gap-4">
                    <dt className="shrink-0 font-medium text-foreground sm:w-2/5">&quot;{p.message}&quot;</dt>
                    <dd className="text-muted-foreground">{p.action}</dd>
                  </div>
                ))}
              </dl>
            </Section>
          </TabsContent>
        </Tabs>
      </div>
    </main>
  );
}
