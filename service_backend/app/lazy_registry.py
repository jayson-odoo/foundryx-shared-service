"""One-shot lazy core registration (code-review consolidation).

Three code-side registries (status entities, rule facts, rule sites) each
hand-rolled a ``_core_registered`` module global + ``_ensure_core()`` guard.
This is the single helper: ``ensure = lazy_once(register_fn)`` - call
``ensure()`` before reads; the wrapped function runs exactly once.
"""
from typing import Callable


def lazy_once(register: Callable[[], None]) -> Callable[[], None]:
    done = False

    def ensure() -> None:
        nonlocal done
        if done:
            return
        done = True
        register()

    return ensure
