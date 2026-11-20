"""The one sentence a crashed job handler stores as its error."""


def crash_text(exc: BaseException) -> str:
    """Fixed text naming only the exception class, never the exception's text."""
    return f"Job crashed ({type(exc).__name__})."


def failure_text(what: str, exc: BaseException, *, allow_message: bool = True) -> str:
    """A fixed sentence for a failure a handler catches itself: the step that
    failed plus the class of the underlying cause (the end of the ``raise ...
    from`` chain), never the exception's text. One allowance: an exception
    whose class sets ``operator_safe_message = True`` (checked on the outer
    exception, by attribute) has a message built for operators, so the
    sentence is ``<what>: <message>``; a caller passes ``allow_message=False``
    where the failure text lands somewhere the operator wording does not
    belong."""
    if allow_message and getattr(type(exc), "operator_safe_message", False):
        return f"{what}: {getattr(exc, 'message', None) or exc}"
    seen = 0
    while exc.__cause__ is not None and seen < 8:
        exc = exc.__cause__
        seen += 1
    return f"{what} ({type(exc).__name__})."
