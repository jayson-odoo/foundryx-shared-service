"""Re-export shim - the Meta Graph plumbing moved to core
``app/integrations/meta/graph.py`` (plan 64 D3, review R1).

Every name of the core module (underscore helpers, ``httpx``, ``settings``
included) is re-bound here, so existing imports such as
``from ..adapters.meta_graph import provider_error_text`` and tests that patch
``meta_graph.MetaGraphMixin`` keep resolving to the SAME objects. New code
imports from ``app.integrations.meta`` directly.
"""
from app.integrations.meta import graph as _core_graph

globals().update(
    {name: value for name, value in vars(_core_graph).items() if not name.startswith("__")}
)
