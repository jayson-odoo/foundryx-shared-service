"""Import engine (sprint-3/09, F8) — the 6th cross-cutting core engine.

Generic bulk import for any opt-in Resource list: a per-entity declarative
``ImporterDef`` (sibling of WorkflowEntity/StatusEntity/FactSource) + a two-
phase, job-backed, Celery-decoupled, server-authoritative pipeline (Validate →
Commit, all-or-nothing). Mirrors the ``form_engine`` package shape.
"""
