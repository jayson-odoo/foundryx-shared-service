# Plan 52 acceptance criteria: file previews use a fixed set of display types

| AC | Rule |
|---|---|
| AC-52-01 | [FE] Every in-app preview of a stored file (document drive, public share page, idea attachment preview) builds its local blob with a display type from one fixed allow-list (the same helper the form file viewer uses); any other stored type is shown as a download, never rendered |
| AC-52-02 | [FE] A PDF preview renders only through the same sandboxed frame the form file viewer uses |
| AC-52-03 | [FE] Download-only paths are unchanged |

No backend change, no migration, no permission change.
