"""``SqlSourceRuntime`` - the multi-dialect, READ-ONLY SQL source (plan 22 §2.2).

Four pieces, each independently testable:

  guard.py       SELECT-only static guard (deny-first, AC-22-03)
  runtime.py     dialect URL builder, engine cache, read-only sessions,
                 per-query timeouts, sanitised errors (AC-22-02/30)
  introspect.py  schemas → tables → columns, cached per connection (AC-22-05)
  preview.py     capped, dialect-wrapped query preview (AC-22-06)

    !!  HARD RULE: nothing in this package ever writes to a source DB.  !!

Every statement passes the guard, runs in a transaction that is ALWAYS rolled
back, on a session opened read-only where the dialect supports it, under a
bounded timeout. The source-side login should still be read-only (defense in
depth - the guard is never the only line).
"""
