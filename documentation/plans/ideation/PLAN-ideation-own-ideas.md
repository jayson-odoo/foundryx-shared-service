# SS-IDEATION-OWN - own-idea contract for IDEATION-CAPTURE (sorento PR #1444)

Status: in progress (crew lane SS-IDEATION-OWN). Additive only - the existing
`/ideation/intake/create-idea` draft flow stays untouched.

Scope:
1. One-shot idea create from the chatbot intake that returns the idea id + number.
2. Own-similar lookup: same submitter only (phone or linked CRM user id, never name),
   live ideas only, top 3, existing pg_trgm similarity + threshold.
3. Embed list: `mine=true` filter + per-idea `isMine` for the viewing CRM user.
4. `phone` claim in the CRM embed assertion (for 3).

The final API contract is recorded below once built.
