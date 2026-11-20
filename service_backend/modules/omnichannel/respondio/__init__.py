"""respond.io Developer API v2 integration (plan 33, roadmap A6, slice S1).

- ``client.py`` - the throttled/retrying HTTP client (``RespondIoClient``).
- ``shapes.py`` - pydantic mirrors of the vendor's EXACT field names.
- ``channel_map.py`` - ``SOURCE_TO_CHANNEL_TYPE`` (the ONE place a new source
  channel type plugs in, D-A6-10).

Not imported by core or by any other module - the migration tool is entirely
internal to ``modules.omnichannel``.
"""
