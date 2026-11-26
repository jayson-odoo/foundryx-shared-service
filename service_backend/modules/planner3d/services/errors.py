"""Planner 3D service errors - routers map them to the HTTP detail envelope."""

from __future__ import annotations


class P3Error(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
