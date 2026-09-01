# Ideation Capture - end-to-end simulation transcript

> **STALE FIELD SET.** This transcript was captured against the earlier
> `problem / module / who / impact` intake schema. The required fields were
> since revised to **problem statement, proposed solution, impact, department**
> (module/who dropped - business submitters don't know the module; the submitter
> identifies who). The state-machine behaviour shown (collecting → review →
> confirm → complete, dedup, revise/remove) is unchanged; only the field names
> differ. Re-run `scripts/simulate_ideation_capture.py` to regenerate.

Deterministic Conversational-Intake (NO LLM). Product **Sorento CRM** (`b6f06925-dcdb-493a-9dd4-080193e15f40`), domain base `https://fe-sorento.foundryx.my`. The brain extracts structured `fields`/`remove`/`confirm`; this module merges them against the schema, computes captured/missing and echoes a templated reply. Required fields: **problem, proposed_solution, impact, department**.

---

## Conversation A - build → confirm (7 turns)

### Turn 1 - INCOMPLETE (problem only)

**User (WhatsApp):** I wish the CRM reminded me before a DO's SLA breaches
**Brain-extracted →** fields={} (problem seeded from message)

```json
status  : collecting
captured: {'problem': "I wish the CRM reminded me before a DO's SLA breaches"}
missing : ['module', 'who', 'impact']
```

**Bot reply:**
```
Here's what I've got so far:
- Problem: I wish the CRM reminded me before a DO's SLA breaches

Still need: Module / area, Who it helps, Impact.
```

---

### Turn 2 - SOME missing filled (module)

**User (WhatsApp):** It's about the Orders module
**Brain-extracted →** fields={"module":"Orders"}

```json
status  : collecting
captured: {'problem': "I wish the CRM reminded me before a DO's SLA breaches", 'module': 'Orders'}
missing : ['who', 'impact']
```

**Bot reply:**
```
Here's what I've got so far:
- Problem: I wish the CRM reminded me before a DO's SLA breaches
- Module / area: Orders

Still need: Who it helps, Impact.
```

---

### Turn 3 - REST filled → REVIEW (no auto-complete)

**User (WhatsApp):** It'd help the CS team and save them about 30 minutes a day
**Brain-extracted →** fields={"who":"The CS team","impact":"Saves 30 minutes a day"}

```json
status  : review
captured: {'problem': "I wish the CRM reminded me before a DO's SLA breaches", 'module': 'Orders', 'who': 'The CS team', 'impact': 'Saves 30 minutes a day'}
missing : []
```

**Bot reply:**
```
Here's your idea:
- Problem: I wish the CRM reminded me before a DO's SLA breaches
- Module / area: Orders
- Who it helps: The CS team
- Impact: Saves 30 minutes a day

Reply 'confirm' to submit it, or tell me what to change.
```
*DB check → Idea.status = `draft`*

---

### Turn 4 - REVISION - change team

**User (WhatsApp):** Actually, change the team to Operations
**Brain-extracted →** fields={"who":"Operations"}

```json
status  : review
captured: {'problem': "I wish the CRM reminded me before a DO's SLA breaches", 'module': 'Orders', 'who': 'Operations', 'impact': 'Saves 30 minutes a day'}
missing : []
```

**Bot reply:**
```
Here's your idea:
- Problem: I wish the CRM reminded me before a DO's SLA breaches
- Module / area: Orders
- Who it helps: Operations
- Impact: Saves 30 minutes a day

Reply 'confirm' to submit it, or tell me what to change.
```

---

### Turn 5 - REVISION - remove impact (required)

**User (WhatsApp):** Actually remove the impact line
**Brain-extracted →** remove=["impact"]

```json
status  : collecting
captured: {'problem': "I wish the CRM reminded me before a DO's SLA breaches", 'module': 'Orders', 'who': 'Operations'}
missing : ['impact']
```

**Bot reply:**
```
Here's what I've got so far:
- Problem: I wish the CRM reminded me before a DO's SLA breaches
- Module / area: Orders
- Who it helps: Operations

Still need: Impact.
```

---

> _`impact` is a REQUIRED field in the intake schema, so removing it drops the intake back to **collecting** - the confirm gate cannot be reached until every required field is answered again._

### Turn 6 - MERGE more info → REVIEW

**User (WhatsApp):** Put the impact back - it saves about an hour a day
**Brain-extracted →** fields={"impact":"Saves an hour a day"}

```json
status  : review
captured: {'problem': "I wish the CRM reminded me before a DO's SLA breaches", 'module': 'Orders', 'who': 'Operations', 'impact': 'Saves an hour a day'}
missing : []
```

**Bot reply:**
```
Here's your idea:
- Problem: I wish the CRM reminded me before a DO's SLA breaches
- Module / area: Orders
- Who it helps: Operations
- Impact: Saves an hour a day

Reply 'confirm' to submit it, or tell me what to change.
```

---

### Turn 7 - EXPLICIT CONFIRM → COMPLETE

**User (WhatsApp):** Yes, submit it
**Brain-extracted →** confirm=true

```json
status  : complete
captured: {'problem': "I wish the CRM reminded me before a DO's SLA breaches", 'module': 'Orders', 'who': 'Operations', 'impact': 'Saves an hour a day'}
missing : []
link    : https://fe-sorento.foundryx.my/ideas/5b7dab10-96c9-4caf-95bd-e9f6034b64b3
```

**Bot reply:**
```
Your idea has been captured. Track it here: https://fe-sorento.foundryx.my/ideas/5b7dab10-96c9-4caf-95bd-e9f6034b64b3
```
*DB check → Idea.status = `captured`*

---

## Conversation B - one-shot complete STILL reviews first

### Turn B1 - ONE-SHOT (all fields on turn 1)

**User (WhatsApp):** Let me bulk-edit product prices by uploading a spreadsheet instead of one row at a time
**Brain-extracted →** fields={module,who,impact} (problem seeded)

```json
status  : review
captured: {'problem': 'Let me bulk-edit product prices by uploading a spreadsheet instead of one row at a time', 'module': 'Products', 'who': 'The pricing team', 'impact': 'Cuts a full afternoon of manual edits each month'}
missing : []
```

**Bot reply:**
```
Here's your idea:
- Problem: Let me bulk-edit product prices by uploading a spreadsheet instead of one row at a time
- Module / area: Products
- Who it helps: The pricing team
- Impact: Cuts a full afternoon of manual edits each month

Reply 'confirm' to submit it, or tell me what to change.
```
*DB check → Idea.status = `draft`*

---

> _Even though every required field was answered in the very first message, the intake returns **review** - the D-CONFIRM gate means nothing is captured without an explicit confirm._

### Turn B2 - …then CONFIRM → COMPLETE

**User (WhatsApp):** confirm
**Brain-extracted →** confirm=true

```json
status  : complete
captured: {'problem': 'Let me bulk-edit product prices by uploading a spreadsheet instead of one row at a time', 'module': 'Products', 'who': 'The pricing team', 'impact': 'Cuts a full afternoon of manual edits each month'}
missing : []
link    : https://fe-sorento.foundryx.my/ideas/39cde3d4-9a2c-4959-964a-94610c713372
```

**Bot reply:**
```
Your idea has been captured. Track it here: https://fe-sorento.foundryx.my/ideas/39cde3d4-9a2c-4959-964a-94610c713372
```
*DB check → Idea.status = `captured`*

---

## Result

**All asserted status transitions matched.** collecting → collecting → review → review → collecting → review → complete, plus one-shot review-before-confirm. D-CONFIRM holds.

