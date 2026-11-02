"""The one sentence a crashed job handler stores as its error."""


def crash_text(exc: BaseException) -> str:
    """Fixed text naming only the exception class, never the exception's text."""
    return f"Job crashed ({type(exc).__name__})."
