"""Core catalog (sprint-4/08) — horizontal product + category master data.

Products/categories live in core ``public`` (consumed by CRM quotations, EMS
ticketing, future commerce), NOT in any one module. ``kind`` is an extensible
metadata-only registry (modules add vocabulary at install); core never branches
on it. Cross-module "is this product in use?" goes through the reference-guard
registry (``app/module_platform/reference_guards.py``) so core stays
module-ignorant.
"""
