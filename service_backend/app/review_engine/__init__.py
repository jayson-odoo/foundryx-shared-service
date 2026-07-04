"""Generic Review/Approval engine (plan sprint-4/06 Part 2) — a horizontal core
form-engine extension over any ``form_submission``.

Core stays EMS-free: PERSONA actor pools are resolved through the injectable
``resolvers`` registry that the EMS module (Part B) fills at install. The engine
never imports the EMS Profile table.
"""
