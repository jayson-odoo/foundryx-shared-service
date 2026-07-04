'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { BrandingFooter, BrandingSocials } from '@/types/branding';

export const EMPTY_SOCIALS: BrandingSocials = {
  facebook: null,
  instagram: null,
  x: null,
  linkedin: null,
  youtube: null,
  tiktok: null,
  website: null,
};

export const EMPTY_FOOTER: BrandingFooter = {
  companyName: null,
  addressLine: null,
  tagline: null,
};

const SOCIAL_FIELDS: { key: keyof BrandingSocials; label: string; placeholder: string }[] = [
  { key: 'facebook', label: 'Facebook', placeholder: 'https://facebook.com/…' },
  { key: 'instagram', label: 'Instagram', placeholder: 'https://instagram.com/…' },
  { key: 'x', label: 'X (Twitter)', placeholder: 'https://x.com/…' },
  { key: 'linkedin', label: 'LinkedIn', placeholder: 'https://linkedin.com/company/…' },
  { key: 'youtube', label: 'YouTube', placeholder: 'https://youtube.com/@…' },
  { key: 'tiktok', label: 'TikTok', placeholder: 'https://tiktok.com/@…' },
  { key: 'website', label: 'Website', placeholder: 'https://…' },
];

export interface SocialFooterCardProps {
  socials: BrandingSocials;
  footer: BrandingFooter;
  canManage: boolean;
  onSocialsChange: (socials: BrandingSocials) => void;
  onFooterChange: (footer: BrandingFooter) => void;
}

/**
 * Social profiles + email footer (plan sprint-2/07 D4) — set once, every
 * email template's Brand Footer / Social Links blocks render these at send
 * time (live-follow: a rebrand updates already-saved templates).
 */
export function SocialFooterCard({
  socials,
  footer,
  canManage,
  onSocialsChange,
  onFooterChange,
}: SocialFooterCardProps) {
  return (
    <Card data-testid="social-footer-card">
      <CardHeader className="py-4">
        <CardTitle className="text-sm">Social &amp; email footer</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {SOCIAL_FIELDS.map(({ key, label, placeholder }) => (
            <div key={key} className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">{label}</Label>
              <Input
                value={socials[key] ?? ''}
                disabled={!canManage}
                placeholder={placeholder}
                aria-label={label}
                onChange={(e) => onSocialsChange({ ...socials, [key]: e.target.value || null })}
              />
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Company name</Label>
            <Input
              value={footer.companyName ?? ''}
              disabled={!canManage}
              placeholder="Acme Events Sdn Bhd"
              aria-label="Company name"
              onChange={(e) => onFooterChange({ ...footer, companyName: e.target.value || null })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Address line</Label>
            <Input
              value={footer.addressLine ?? ''}
              disabled={!canManage}
              placeholder="1 Example Street, Kuala Lumpur"
              aria-label="Address line"
              onChange={(e) => onFooterChange({ ...footer, addressLine: e.target.value || null })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Tagline</Label>
            <Input
              value={footer.tagline ?? ''}
              disabled={!canManage}
              placeholder="Your events, brought to life."
              aria-label="Footer tagline"
              onChange={(e) => onFooterChange({ ...footer, tagline: e.target.value || null })}
            />
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          Used by the Brand Footer and Social Links blocks in email templates. Emails update
          automatically — no need to re-save templates.
        </p>
      </CardContent>
    </Card>
  );
}
