'use client';

import { Blocks, Palette } from 'lucide-react';
import type { UseFormReturn } from 'react-hook-form';
import type { TenantDetail } from '@/types/tenant-admin';
import { useDatetime } from '@/hooks/use-datetime';
import { useCan } from '@/hooks/use-can';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ResourceList } from '@/components/platform/resource-list';
import { useModuleListConfig } from '@/components/platform/app-store';
import { BrandingEditor } from '@/components/platform/branding';
import { FormRow } from '@/components/platform/resource-form';
import { StatusBadge } from '@/components/platform/status-badge';
import type { TenantFormValues } from './tenant-schema';
import { tenantStatusRegistry } from './tenant-status';

/* ─────────────────────────── Details tab ─────────────────────────── */

interface TextRowProps {
  form: UseFormReturn<TenantFormValues>;
  name: keyof TenantFormValues;
  label: string;
  editing: boolean;
  required?: boolean;
  placeholder?: string;
  readValue: string | null | undefined;
  type?: string;
  /** Renders the read-mode value in mono (slug / domain). */
  mono?: boolean;
}

function TextRow({
  form,
  name,
  label,
  editing,
  required,
  placeholder,
  readValue,
  type,
  mono,
}: TextRowProps) {
  return (
    <FormRow label={label} required={editing && required}>
      {editing ? (
        <FormField
          control={form.control}
          name={name}
          render={({ field }) => (
            <FormItem className="max-w-sm">
              <FormControl>
                <Input type={type} placeholder={placeholder} {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      ) : (
        <span
          className={
            readValue
              ? mono
                ? 'font-mono text-xs'
                : ''
              : 'text-muted-foreground'
          }
        >
          {readValue || '-'}
        </span>
      )}
    </FormRow>
  );
}

export interface DetailsTabProps {
  form: UseFormReturn<TenantFormValues>;
  editing: boolean;
  tenant: TenantDetail | null;
  creating: boolean;
}

export function DetailsTab({
  form,
  editing,
  tenant,
  creating,
}: DetailsTabProps) {
  const { formatDate } = useDatetime();
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="py-1">
          <TextRow
            form={form}
            name="name"
            label="Tenant name"
            editing={editing}
            required
            placeholder="e.g. Acme Events"
            readValue={tenant?.name}
          />

          {/* Slug is the tenant's URL identity - editable only at create (plan 07 §4). */}
          <FormRow label="Slug" required={creating && editing}>
            {creating && editing ? (
              <FormField
                control={form.control}
                name="slug"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <Input placeholder="e.g. acme-events" {...field} />
                    </FormControl>
                    <p className="text-xs text-muted-foreground">
                      The tenant&apos;s subdomain - lowercase, immutable after
                      creation.
                    </p>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <span className="flex items-center gap-2">
                <span className="font-mono text-xs">{tenant?.slug ?? '-'}</span>
                {tenant?.isPlatform && (
                  <Badge variant="secondary" appearance="light" size="sm">
                    Platform
                  </Badge>
                )}
              </span>
            )}
          </FormRow>

          {!creating && tenant && (
            <FormRow label="Status">
              <StatusBadge
                status={tenant.status}
                registry={tenantStatusRegistry(tenant)}
              />
            </FormRow>
          )}

          <TextRow
            form={form}
            name="contactName"
            label="Contact name"
            editing={editing}
            placeholder="Primary contact"
            readValue={tenant?.contactName}
          />
          <TextRow
            form={form}
            name="contactEmail"
            label="Contact email"
            editing={editing}
            placeholder="contact@tenant.com"
            readValue={tenant?.contactEmail}
          />

          {/* Custom domain is schema-ready; CNAME/infra wiring is BL-034. */}
          {!creating && (
            <TextRow
              form={form}
              name="customDomain"
              label="Custom domain"
              editing={editing}
              placeholder="events.acme.com"
              readValue={tenant?.customDomain}
              mono
            />
          )}

          <FormRow label="Notes">
            {editing ? (
              <FormField
                control={form.control}
                name="notes"
                render={({ field }) => (
                  <FormItem className="max-w-md">
                    <FormControl>
                      <Textarea
                        rows={3}
                        placeholder="Internal operator notes…"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <span className={tenant?.notes ? '' : 'text-muted-foreground'}>
                {tenant?.notes || '-'}
              </span>
            )}
          </FormRow>

          {!creating && tenant && (
            <FormRow label="Created">{formatDate(tenant.createdAt)}</FormRow>
          )}
        </CardContent>
      </Card>

      {/* First admin - provisioned with the tenant in one transaction (plan 07 §7). */}
      {creating && (
        <Card>
          <CardContent className="py-1">
            <p className="border-b border-border py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              First admin user
            </p>
            <TextRow
              form={form}
              name="adminName"
              label="Admin name"
              editing
              required
              placeholder="e.g. Kay Meister"
              readValue={null}
            />
            <TextRow
              form={form}
              name="adminEmail"
              label="Admin email"
              editing
              required
              placeholder="admin@tenant.com"
              readValue={null}
            />
            <FormRow label="Temporary password" required>
              <FormField
                control={form.control}
                name="adminPassword"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <Input
                        type="password"
                        placeholder="At least 8 characters"
                        {...field}
                      />
                    </FormControl>
                    <p className="text-xs text-muted-foreground">
                      Hand it to the tenant admin out-of-band - invite emails
                      arrive with BL-033.
                    </p>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </FormRow>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ─────────────────────────── Modules tab ─────────────────────────── */

/**
 * Per-tenant module state + operator actions (plan 08 §8) - the same card grid
 * as the tenant storefront, against the operator endpoints. All actions gated
 * by tenants.manage_modules (platform key; require_platform_permission is the
 * real boundary).
 */
export function ModulesTab({ tenant }: { tenant: TenantDetail | null }) {
  if (!tenant || tenant.isPlatform) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Blocks className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">
            {tenant
              ? 'No modules for the platform tenant'
              : 'Save the tenant first'}
          </p>
          <p className="text-sm text-muted-foreground">
            {tenant
              ? 'The platform tenant hosts the operator team only - it never installs App Store modules (plan 07 §5).'
              : 'Modules can be managed once the tenant is provisioned.'}
          </p>
        </CardContent>
      </Card>
    );
  }
  return <TenantModulesGrid tenantId={tenant.id} />;
}

function TenantModulesGrid({ tenantId }: { tenantId: string }) {
  // Same Resource shell as the tenant storefront, parameterized to the operator
  // endpoints; every action gates on tenants.manage_modules (D6).
  const config = useModuleListConfig(tenantId);
  return <ResourceList config={config} />;
}

/* ─────────────────────────── Branding tab ─────────────────────────── */

/**
 * Operator surface of tenant branding (sprint-2/03) - the SAME editor as the
 * tenant's /settings/branding, against the operator endpoints. One platform
 * key (tenants.manage_branding) covers every edit; the platform tenant itself
 * keeps stock Foundryx branding (the console IS the product).
 */
export function BrandingTab({ tenant }: { tenant: TenantDetail | null }) {
  const { can } = useCan();
  if (!tenant || tenant.isPlatform) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Palette className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">
            {tenant
              ? 'No branding for the platform tenant'
              : 'Save the tenant first'}
          </p>
          <p className="text-sm text-muted-foreground">
            {tenant
              ? 'The platform console keeps stock Foundryx branding - tenant branding applies to customer tenants only.'
              : 'Branding can be managed once the tenant is provisioned.'}
          </p>
        </CardContent>
      </Card>
    );
  }
  return (
    <BrandingEditor
      tenantId={tenant.id}
      canManage={can('tenants.manage_branding')}
    />
  );
}
