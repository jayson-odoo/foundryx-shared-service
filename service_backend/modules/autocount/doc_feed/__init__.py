"""``doc_feed`` - the DO / GRN HTTP source, cursors and CRM sink
(sprint-5/14). A small package beside the ETL task framework (plan D1):
this feed is unmapped (Q1), day-windowed (not a whole-population diff), and
its deletion sweep is a bounded 45-day window - three properties the
existing ``ac_entity_config`` + ``HttpApiSource`` + ``sync.py`` staging
pipeline was not built for (plan section 2).
"""
