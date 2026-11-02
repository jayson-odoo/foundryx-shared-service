"""The one sentence a crashed job handler stores as its error."""


def crash_text(exc: BaseException) -> str:
    """Fixed text naming only the exception class, never the exception's text."""
    return f"Job crashed ({type(exc).__name__})."


def failure_text(what: str, exc: BaseException) -> str:
    """A fixed sentence for a failure a handler catches itself: the step that
    failed plus the class of the underlying cause (the end of the ``raise ...
    from`` chain), never the exception's text."""
    seen = 0
    while exc.__cause__ is not None and seen < 8:
        exc = exc.__cause__
        seen += 1
    return f"{what} ({type(exc).__name__})."
