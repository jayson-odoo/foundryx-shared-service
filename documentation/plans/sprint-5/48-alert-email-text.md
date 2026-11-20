# Plan 48: AutoCount alert email text

UAC: `48-alert-email-text-acceptance-criteria.md`. Size S. Branch `crew/ss-alert-email-text`.

| Area | File | Change |
|---|---|---|
| Email body | `modules/autocount/alerts.py` (email build, about :500) and its template | Status, fixed sentence, link; no error text |
| Doc | `documentation/engineering/autocount-integration-alerts.md` | The rule |
| Tests | new test file | Per AC, with a Sorento reply holding a MARKER |

Slices: S1 tester red, coder. S2 lead kill. S3 reviewer plus security-reviewer.
