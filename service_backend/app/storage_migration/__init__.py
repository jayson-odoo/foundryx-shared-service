"""Storage-key location registry (sprint-4/10).

Slice-1 scope: the declarative + JSON-callback registry of every place a
``conn:<connection_id>:<raw>`` storage key lives, plus the generic
enumerate/rewrite engine and the drift-test reflection helper. The migration
service (start/copy/rewrite/cutover) is Slice 2.
"""
from app.storage_migration.registry import (
    StorageKeyLoc,
    all_key_columns,
    enumerate_keys,
    register_storage_key_location,
    registered_scalar_columns,
    rewrite_keys,
)

__all__ = [
    "StorageKeyLoc",
    "all_key_columns",
    "enumerate_keys",
    "register_storage_key_location",
    "registered_scalar_columns",
    "rewrite_keys",
]
