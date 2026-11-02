# Plan 48 acceptance criteria: AutoCount alert email text

| AC | Rule |
|---|---|
| AC-48-01 | [BE] The AutoCount failure alert email and its reminder carry the integration's name, the status, a fixed sentence and a link to the integration in the app; the recovered email carries the name, the status and the link. None of them carries the run's error text, Sorento's reply or a record message |
| AC-48-02 | [BE] The same holds for every recipient, including the "Also email" addresses |
| AC-48-03 | [BE] The in-app run error and the incident's last error keep the full text, unchanged, for operators |
| AC-48-04 | [T] `documentation/engineering/autocount-integration-alerts.md` states the rule |

No migration, no new permission, no screen change.
