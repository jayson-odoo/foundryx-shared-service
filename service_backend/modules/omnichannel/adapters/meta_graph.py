"""Re-export shim - the Meta Graph plumbing moved to core
``app/integrations/meta/graph.py`` (plan 64 D3, review R1).

This module name is an ALIAS of the core module (``sys.modules`` points both
names at one module object), so existing imports such as
``from ..adapters.meta_graph import provider_error_text`` keep working AND a
test that patches ``meta_graph.httpx`` / ``meta_graph.settings`` patches the
module the code actually runs in, exactly as before the move. New code
imports from ``app.integrations.meta`` directly.
"""
import sys

from app.integrations.meta import graph as _core_graph

sys.modules[__name__] = _core_graph
