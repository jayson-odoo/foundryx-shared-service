# Plan 40: Frontend container and deploy transport hardening

Small hardening PR, no application behaviour changes. The frontend container runs with the least it needs, and the deploy verifies the host it sends secrets to.

## Acceptance criteria

| AC | Rule |
|---|---|
| AC-40-01 | `frontend_blue` and `frontend_green` set `cap_drop: [ALL]` and `security_opt: ["no-new-privileges:true"]` |
| AC-40-02 | `frontend_blue` and `frontend_green` set `read_only: true` with size-limited tmpfs on `/tmp` and `/app/.next/cache`. Nothing else is writable. Backend colors, workers and infra are unchanged |
| AC-40-03 | Every `ssh` and `scp` in `.github/workflows/deploy.yml` uses `StrictHostKeyChecking=yes` and a known-hosts file written from `secrets.SSH_KNOWN_HOSTS`. No `StrictHostKeyChecking=no` and no `UserKnownHostsFile=/dev/null` remain |
| AC-40-04 | If `SSH_KNOWN_HOSTS` is empty, the workflow fails with `::error::` before any connection to the host |
| AC-40-05 | After writing `.env`, the deploy sets mode 600 on it, so an older file with a wider mode is corrected. A refused write still only warns, as today |
| AC-40-06 | `DEPLOY.md` documents `SSH_KNOWN_HOSTS`: how to get the value and verify it against the host, and that a host move or rebuild needs it updated. It also documents the frontend's read-only filesystem and where it may write |
| AC-40-07 | When a host connection fails with ssh's exit 255 at the first connection step, the error names `SSH_KNOWN_HOSTS` and says not to re-run until checked. A remote command failing still gets today's permissions message |
| AC-40-08 | `DEPLOY.md` says to keep the unedited line from `ssh-keyscan -t ed25519 -p <SSH_PORT> <SSH_HOST>`, using the same host value as `SSH_HOST`, because the stored name and port must match the connection. It says what stays writable accurately |

## Before merge

The `SSH_KNOWN_HOSTS` secret must exist, verified against the host's real key and not just scanned over the network. Without it, or with a wrong value, the deploy stops before connecting or at the host key check, with the live stack untouched. Do not re-run a failing deploy repeatedly, fix the cause first.

## Verification

Compose settings run live on a local daemon with the standalone build: same user and paths as the production stage, not the production image itself, and backend unreachable. The blue/green health gate stops an unhealthy frontend before the swap.
