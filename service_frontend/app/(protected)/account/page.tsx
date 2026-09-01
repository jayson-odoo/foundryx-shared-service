'use client';

import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import { useSessionSync } from '@/hooks/use-session-sync';
import { ChangeEmailDialog } from './components/change-email-dialog';
import { TimezoneCard } from './components/timezone-card';
import { useAccountForm } from './components/use-account-form';

/**
 * My Account (plan sprint-2/04; Resource form shell since plan 06) - minimal
 * self-service surface on the system design language: global Edit toggle
 * (name), avatar slot, Profile + Security tabs (change-email ceremony,
 * password reset). Perm-free like /auth/me (self-scope only); future home
 * for timezone (plan 05).
 */
export default function AccountPage() {
  // Catch a backend identity flip this session couldn't see (plan 04 email
  // ceremony; generalized in plan 06 D8) - conditional update() via /auth/me
  // probe. The protected layout probes per hard load; this re-probes on
  // every nav to /account.
  useSessionSync();

  const { config, form, emailChange, dialogOpen, setDialogOpen, email } =
    useAccountForm();

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>

      {/* Display preferences - timezone picker (plan sprint-2/05). */}
      <TimezoneCard />

      <ChangeEmailDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        currentEmail={email}
        isProcessing={emailChange.isProcessing}
        error={emailChange.error}
        onRequest={emailChange.requestChange}
        clearError={emailChange.clearError}
      />
    </Container>
  );
}
