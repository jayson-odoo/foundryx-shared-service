"""Find an AutoCount document by number (sprint-5/17, AC-DOC-FINDER).

Read only: the lookup never builds a sink and never writes to AutoCount or to
any feed / snapshot / ledger / cursor row. Its only writes are its own job row
and its own ``ac_doc_lookup_hint`` / ``ac_doc_lookup_settings`` rows.
"""
