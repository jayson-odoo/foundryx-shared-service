"""The open (no-auth) REST API page-walk source (sprint-5/08).

Mirrors ``sql_source/`` in shape: ``source.py`` implements ``EntitySource``,
``client.py`` is the paged transport, ``envelope.py`` classifies a page's
shape, ``errors.py`` the failure type, ``preview.py`` the page-1 sample used
by both the task editor's Test button and ``routers/http.py``.
"""
