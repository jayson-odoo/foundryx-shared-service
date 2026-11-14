"""The lookup's ONE vendor reader (D1): every AutoCount call the doc finder
makes goes through ``DocLookupReader.send``, which refuses anything but a GET
before a byte leaves the process. The read itself reuses ``DocFeedVendor``'s
retry ladder + parse unchanged."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from ..doc_feed.clock import yyyymmdd
from ..doc_feed.vendor import DocFeedVendor


class ReadOnlyViolation(Exception):
    """Something asked the doc finder to send a non-GET to AutoCount."""


class DocLookupReader:
    def __init__(self, client: Any) -> None:
        self._vendor = DocFeedVendor(client)

    def send(self, method: str, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        if method != "GET":
            raise ReadOnlyViolation(
                f"The document finder only reads from AutoCount; refused {method} {path}."
            )
        return self._vendor.get_day(path, params)

    def day(self, path: str, param: str, on: date) -> List[Dict[str, Any]]:
        return self.send("GET", path, {param: yyyymmdd(on)})
