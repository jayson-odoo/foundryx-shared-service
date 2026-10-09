"""Upload target: a local directory or s3://bucket/prefix (R2 / S3 compatible)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


class Storage:
    def __init__(self, target: str) -> None:
        self.target = target
        self._s3 = None
        if target.startswith("s3://"):
            import boto3

            rest = target[5:]
            self.bucket, _, self.prefix = rest.partition("/")
            self._s3 = boto3.client(
                "s3",
                endpoint_url=os.environ.get("BOT_S3_ENDPOINT") or None,
                region_name=os.environ.get("BOT_S3_REGION", "auto"),
            )
        else:
            self.local = Path(target)
            self.local.mkdir(parents=True, exist_ok=True)

    def put(self, path: Path, name: str | None = None) -> str:
        name = name or path.name
        if self._s3 is not None:
            key = f"{self.prefix.rstrip('/')}/{name}" if self.prefix else name
            self._s3.upload_file(str(path), self.bucket, key)
            return f"s3://{self.bucket}/{key}"
        dest = self.local / name
        if path.resolve() != dest.resolve():
            shutil.copy2(path, dest)
        return str(dest)
