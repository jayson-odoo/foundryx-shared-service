"""``SttProvider`` adapter (S3 plan §3.1).

An adapter earns its place here because a second implementation is already
planned (M12 - a GPU VM / Modal driver when volume demands it, Deepgram as a
configured fallback) - not because "we might want to configure this later".

Provider selection is a PLATFORM setting (``settings.meetings_stt_provider``),
not per-tenant: one pilot host runs one model (R5). ``get_provider`` fails
LOUDLY when the configured name is unknown or names a provider that has no
driver yet - it never silently falls back to ``mlx_local`` (AC-S3-10).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Protocol

# Names the settings/UAC recognise but that ship no driver in S3. Kept as a
# named set (rather than "anything that is not mlx_local raises") so the error
# message can say WHICH provider is unbuilt, not just that resolution failed.
UNBUILT_PROVIDERS = frozenset({"deepgram"})

MLX_LOCAL = "mlx_local"


@dataclass
class SttSegment:
    """One Whisper segment, before speaker alignment."""

    start_ms: int
    end_ms: int
    text: str
    # R3 AMENDED (S3 code-switch fix, 2026-09-01): the chunked mlx_runner
    # detects language PER CHUNK, so this carries the real detected language
    # for the chunk this segment came from - never a guess. None only for an
    # older runner payload / a provider that has not adopted per-segment
    # language yet.
    language: Optional[str] = None


@dataclass
class SttResult:
    """One provider call's whole output - many segments, each with its own
    detected language (R3 AMENDED), plus a file-level ``language`` that is
    the majority chunk language (ties broken by first occurrence)."""

    language: Optional[str]
    segments: List[SttSegment] = field(default_factory=list)


class SttProvider(Protocol):
    def transcribe(self, audio_path: Path) -> SttResult: ...


class UnbuiltSttProviderError(Exception):
    """The configured provider is unknown, or named but not built yet."""


def get_provider(name: Optional[str] = None) -> SttProvider:
    """Resolve the configured STT provider by name.

    ``name`` defaults to ``settings.meetings_stt_provider`` (read lazily so a
    test can monkeypatch the setting rather than importing this module
    before the patch lands)."""
    from app.config import settings

    provider_name = name if name is not None else settings.meetings_stt_provider

    if provider_name == MLX_LOCAL:
        from .mlx_local import MlxLocalProvider

        return MlxLocalProvider()

    if provider_name in UNBUILT_PROVIDERS:
        raise UnbuiltSttProviderError(
            f"STT provider '{provider_name}' is not built yet - S3 ships only "
            f"'{MLX_LOCAL}'. Set MEETINGS_STT_PROVIDER={MLX_LOCAL} or build the "
            f"'{provider_name}' driver first."
        )

    raise UnbuiltSttProviderError(
        f"Unknown STT provider '{provider_name}'. Known providers: "
        f"'{MLX_LOCAL}' (built), {sorted(UNBUILT_PROVIDERS)!r} (config only)."
    )
