'use client';

import { useEffect, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { toast } from 'sonner';
import type { BrandingFooter, BrandingSocials, BrandingTokens } from '@/types/branding';
import { isValidColor } from '@/lib/branding-tokens';
import { useBrandingAdmin } from '@/hooks/use-branding';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AssetUploadCard } from './asset-upload-card';
import { BrandingPreview } from './branding-preview';
import { EMPTY_FOOTER, EMPTY_SOCIALS, SocialFooterCard } from './social-footer-card';
import { ThemeTokenEditor } from './theme-token-editor';

export interface BrandingEditorProps {
  /** Omit = the caller's own tenant; set = operator console acting on a tenant. */
  tenantId?: string;
  canManage: boolean;
}

/**
 * The branding editor (sprint-2/03) - shared verbatim between the tenant
 * settings page and the operator console's Branding tab. Asset uploads apply
 * immediately; slogan + theme tokens are a draft committed by Save.
 */
export function BrandingEditor({ tenantId, canManage }: BrandingEditorProps) {
  const { branding, isLoading, error, save, upload, removeAsset } =
    useBrandingAdmin(tenantId);

  const [slogan, setSlogan] = useState('');
  const [appName, setAppName] = useState('');
  const [tokens, setTokens] = useState<BrandingTokens | null>(null);
  const [socials, setSocials] = useState<BrandingSocials>(EMPTY_SOCIALS);
  const [footer, setFooter] = useState<BrandingFooter>(EMPTY_FOOTER);
  const [saving, setSaving] = useState(false);

  // Sync draft from the loaded record (and after save round-trips).
  useEffect(() => {
    if (!branding) return;
    setSlogan(branding.slogan ?? '');
    setAppName(branding.appName ?? '');
    setTokens(branding.tokens);
    setSocials(branding.socials ?? EMPTY_SOCIALS);
    setFooter(branding.footer ?? EMPTY_FOOTER);
  }, [branding]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>
    );
  }

  if (error || !branding) {
    return (
      <div className="flex flex-col items-center gap-2 py-24 text-center">
        <p className="text-sm font-medium">Could not load branding.</p>
        <p className="text-sm text-muted-foreground">{error}</p>
      </div>
    );
  }

  const isDirty =
    slogan.trim() !== (branding.slogan ?? '') ||
    appName.trim() !== (branding.appName ?? '') ||
    JSON.stringify(tokens) !== JSON.stringify(branding.tokens) ||
    JSON.stringify(socials) !== JSON.stringify(branding.socials ?? EMPTY_SOCIALS) ||
    JSON.stringify(footer) !== JSON.stringify(branding.footer ?? EMPTY_FOOTER);

  const invalidValues = tokens
    ? [...Object.values(tokens.light), ...Object.values(tokens.dark)].filter(
        (v) => !isValidColor(v),
      )
    : [];

  const handleSave = async () => {
    if (invalidValues.length) {
      toast.error('Fix the invalid color values first.');
      return;
    }
    setSaving(true);
    try {
      await save({ slogan: slogan.trim() || null, appName: appName.trim() || null, tokens, socials, footer });
      toast.success('Branding saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => {
    setSlogan(branding.slogan ?? '');
    setAppName(branding.appName ?? '');
    setTokens(branding.tokens);
    setSocials(branding.socials ?? EMPTY_SOCIALS);
    setFooter(branding.footer ?? EMPTY_FOOTER);
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Assets - apply immediately (server validates again). */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <AssetUploadCard
          kind="logo"
          title="Logo"
          url={branding.logoUrl}
          canManage={canManage}
          onBrandSurface
          onUpload={(f) => upload('logo', f)}
          onRemove={() => removeAsset('logo')}
        />
        <AssetUploadCard
          kind="favicon"
          title="Browser-tab icon"
          url={branding.faviconUrl}
          canManage={canManage}
          onUpload={(f) => upload('favicon', f)}
          onRemove={() => removeAsset('favicon')}
        />
        <AssetUploadCard
          kind="illustration"
          title="Sign-in illustration"
          url={branding.illustrationUrl}
          canManage={canManage}
          onBrandSurface
          onUpload={(f) => upload('illustration', f)}
          onRemove={() => removeAsset('illustration')}
        />
      </div>

      {/* System name - part of the Save draft. Drives "Welcome to {name}". */}
      <Card>
        <CardHeader className="py-4">
          <CardTitle className="text-sm">System name</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Input
            value={appName}
            disabled={!canManage}
            maxLength={60}
            placeholder="e.g. Acme Events"
            aria-label="System name"
            onChange={(e) => setAppName(e.target.value)}
            className="max-w-xl"
          />
          <p className="text-xs text-muted-foreground">
            Shown as “Welcome to {'{name}'}” on the sign-in page. Leave empty to
            use your organization name.
          </p>
        </CardContent>
      </Card>

      {/* Slogan - part of the Save draft. */}
      <Card>
        <CardHeader className="py-4">
          <CardTitle className="text-sm">Slogan</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Input
            value={slogan}
            disabled={!canManage}
            maxLength={120}
            placeholder="e.g. Your events, brought to life."
            aria-label="Slogan"
            onChange={(e) => setSlogan(e.target.value)}
            className="max-w-xl"
          />
          <p className="text-xs text-muted-foreground">
            Shown under the logo on the sign-in page. Leave empty to show the
            logo alone.
          </p>
        </CardContent>
      </Card>

      {/* Social profiles + email footer (plan 07 D4) - part of the Save draft. */}
      <SocialFooterCard
        socials={socials}
        footer={footer}
        canManage={canManage}
        onSocialsChange={setSocials}
        onFooterChange={setFooter}
      />

      <ThemeTokenEditor
        tokens={tokens}
        onChange={setTokens}
        canManage={canManage}
      />

      <BrandingPreview
        slogan={slogan.trim() || null}
        appName={appName.trim() || null}
        logoUrl={branding.logoUrl}
        illustrationUrl={branding.illustrationUrl}
        tokens={tokens}
      />

      {canManage && (
        <div className="sticky bottom-4 z-(--z-sticky-content) flex items-center justify-end gap-2">
          {isDirty && (
            <>
              <Button
                variant="outline"
                onClick={handleDiscard}
                disabled={saving}
              >
                Discard
              </Button>
              <Button
                onClick={() => void handleSave()}
                disabled={saving || invalidValues.length > 0}
              >
                {saving && <LoaderCircleIcon className="size-4 animate-spin" />}
                Save branding
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
