import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import { mockBusinessRequirementService as svc } from './business-requirement-service.mock';

/**
 * Plan ideation-br-send-to-build S0: the Phase 1 mock carries the header
 * states (sendable / blocked / already sent), the trace fixture and the
 * build-key CRUD. Fixtures are found by SHAPE, never by hard-coded id.
 */
async function allDetails(): Promise<BusinessRequirementDetail[]> {
  const rows = await svc.list({ filter: 'all' });
  return Promise.all(rows.map((r) => svc.get(r.id)));
}

describe('mockBusinessRequirementService build seeds (AC-STB-07/19)', () => {
  it('AC-STB-07 seeds a sendable BR, a blocked BR and an already-sent BR', async () => {
    const all = await allDetails();
    expect(all.some((b) => b.build.canSend === true && b.build.state === 'none')).toBe(true);
    const blocked = all.find((b) => b.build.canSend === false && b.build.blockers.length > 0);
    expect(blocked?.build.blockers).toEqual(['Missing: Success metric, Constraints']);
    const sent = all.find((b) => b.build.state === 'sent');
    expect(sent).toBeDefined();
  });

  it('AC-STB-19 the sent BR carries the 1402 issue and 5 trace events incl. a PR and a hand-test link', async () => {
    const sent = (await allDetails()).find((b) => b.build.state === 'sent')!;
    expect(sent.status).toBe('sent_to_build');
    expect(sent.build.issueUrl).toBe('https://github.com/jayson-odoo/sorento-crm/issues/1402');
    expect(sent.build.issueNumber).toBe(1402);
    expect(sent.build.repo).toBe('jayson-odoo/sorento-crm');
    expect(sent.build.events).toHaveLength(5);
    expect(sent.build.events.some((e) => e.prUrl)).toBe(true);
    expect(sent.build.events.some((e) => e.handtestUrl)).toBe(true);
    const seqs = sent.build.events.map((e) => e.seq);
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
  });

  it('AC-STB-19 getBuild returns the same BuildInfo as the detail', async () => {
    const sent = (await allDetails()).find((b) => b.build.state === 'sent')!;
    const build = await svc.getBuild(sent.id);
    expect(build.issueNumber).toBe(1402);
    expect(build.events).toHaveLength(5);
  });
});

describe('mockBusinessRequirementService.sendToBuild (AC-STB-08/09)', () => {
  it('AC-STB-08 rejects a blocked BR with 422 {message, blockers}', async () => {
    const blocked = (await allDetails()).find((b) => !b.build.canSend && b.build.blockers.length)!;
    const err = await svc.sendToBuild(blocked.id).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    const detail = (err as ApiError).detail as { message: string; blockers: string[] };
    expect(typeof detail.message).toBe('string');
    expect(detail.blockers).toEqual(['Missing: Success metric, Constraints']);
  });

  it('AC-STB-09 sending the sendable BR moves it to sent_to_build with an issue and a sent event', async () => {
    const sendable = (await allDetails()).find((b) => b.build.canSend && b.build.state === 'none')!;
    const sent = await svc.sendToBuild(sendable.id);
    expect(sent.status).toBe('sent_to_build');
    expect(sent.build.state).toBe('sent');
    expect(sent.build.issueUrl).toBeTruthy();
    expect(sent.build.issueNumber).toBeGreaterThan(0);
    expect(sent.build.events.some((e) => e.kind === 'sent')).toBe(true);
    const again = await svc.get(sendable.id);
    expect(again.status).toBe('sent_to_build');
  });

  it('AC-STB-09 a second send returns the same issue and does not append events', async () => {
    const sendable = (await allDetails()).find((b) => b.build.state === 'sent')!;
    const before = sendable.build.events.length;
    const second = await svc.sendToBuild(sendable.id);
    expect(second.build.issueNumber).toBe(sendable.build.issueNumber);
    expect(second.build.issueUrl).toBe(sendable.build.issueUrl);
    expect(second.build.events).toHaveLength(before);
  });
});

describe('mockBusinessRequirementService build keys (AC-STB-15)', () => {
  it('AC-STB-15 mint returns a fxb_live_ plaintext once; the list has the key without plaintext', async () => {
    const minted = await svc.mintBuildKey('Crew daemon');
    expect(minted.plaintext.startsWith('fxb_live_')).toBe(true);
    expect(minted.name).toBe('Crew daemon');
    const list = await svc.listBuildKeys();
    const row = list.find((k) => k.id === minted.id);
    expect(row).toBeDefined();
    expect(row!.keyPrefix.length).toBeGreaterThan(0);
    expect(row as unknown as Record<string, unknown>).not.toHaveProperty('plaintext');
  });

  it('AC-STB-15 revoke removes the key from the list', async () => {
    const minted = await svc.mintBuildKey('To revoke');
    await svc.revokeBuildKey(minted.id);
    const list = await svc.listBuildKeys();
    expect(list.some((k) => k.id === minted.id)).toBe(false);
  });
});
