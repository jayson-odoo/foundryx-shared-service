"""StorageService - re-export shim (sprint-2/03).

The implementation was lifted to core (``app/services/storage.py``) so core
features (tenant branding) can use it; module code keeps importing from here.
S3Storage is gone (plan 06 D1) - S3 now rides the connection-driven
``storage_for_tenant`` via ``app.integrations.s3_provider.S3CompatibleAdapter``.
"""
from app.services.storage import (  # noqa: F401 - re-exports are the point
    LocalDiskStorage,
    StorageService,
    get_storage,
    set_storage,
    storage_for_tenant,
)
