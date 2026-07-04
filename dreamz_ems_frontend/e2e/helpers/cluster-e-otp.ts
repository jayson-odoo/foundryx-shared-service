/**
 * Cluster E OTP "mailbox" — the portal login code is emailed; with no SMTP it
 * lands in the `email_outbox` table. We read the latest code for an address by
 * shelling out to psql (the dedicated :8002 DB). The send body is
 * "Your one-time sign-in code is: NNNNNN" (email_service.send_profile_otp).
 */
import { execFileSync } from 'node:child_process';

const DB_URL =
  process.env.CLUSTER_E_DB ??
  'postgresql://dreamz:dreamz@localhost:5432/dreamz_ems_clustere';

/** Poll the outbox for the newest 6-digit OTP for `email`. Retries a few times
 * because the send is async (eager dispatcher commits within ~ms). */
export async function readLatestOtp(email: string, attempts = 12): Promise<string> {
  for (let i = 0; i < attempts; i++) {
    const out = execFileSync(
      'psql',
      [
        DB_URL,
        '-tA',
        '-c',
        `SELECT text_body FROM email_outbox WHERE to_email='${email.replace(/'/g, "''")}' AND template_key='portal.otp' ORDER BY created_at DESC LIMIT 1;`,
      ],
      { encoding: 'utf8' },
    ).trim();
    const m = out.match(/code is:\s*(\d{6})/);
    if (m) return m[1];
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`No OTP found in the outbox for ${email}`);
}
