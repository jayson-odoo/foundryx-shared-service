"""Core Meta (Facebook / Instagram / WhatsApp) plumbing shared by every
Service - plan 64 D3/D5/D15. Omnichannel keeps re-export shims at its old
import paths; new code imports from here.

- ``graph``: Graph client mixin, error/rate-limit helpers, ``graph_base_url``.
- ``errors``: ``SendError``, ``CodeExchangeError``.
- ``pages``: code exchange, long-lived token, Page list, Page subscribe
  (union) / unsubscribe (remainder).
- ``signature``: ``X-Hub-Signature-256`` check.
- ``webhook_registry``: per-(object, field) change-handler registry.
"""
