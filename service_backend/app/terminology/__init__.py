"""Terminology engine (sprint-3/08, F10) — per-tenant entity relabeling.

Core, general, horizontal: any module registers its entities' default labels
(``register_term``); any tenant overrides the display word. Mirrors the
``rule_engine``/``status_engine`` package shape (registry + lazy_once seed).
The DB/code names are the contract; only the label is presentation.
"""
