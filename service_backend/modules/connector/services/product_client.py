"""Outbound HTTP to the product (S4 fills the signed-call client).

``TRANSPORT`` is the test seam: None = real httpx; tests set an
``httpx.MockTransport``.
"""
from typing import Optional

import httpx

TRANSPORT: Optional[httpx.BaseTransport] = None
