# Plan 52 acceptance criteria: file previews use a fixed set of display types

| AC | Rule |
|---|---|
| AC-52-01 | [FE] Every in-app preview of a stored file (document drive, public share page, idea attachment preview) builds its local blob with a display type from one fixed allow-list (the same helper the form file viewer uses); any other stored type is shown as a download, never rendered |
| AC-52-02 | [FE] A frame or tab that shows a preview only ever receives a blob whose type comes from the allow-list: a PDF gets `application/pdf`, and no HTML-like type reaches a frame. (Browsers do not render PDFs in a sandboxed frame, so the type is the control, as in the form file viewer.) |
| AC-52-03 | [FE] Download-only paths are unchanged |
| AC-52-04 | [FE] Conversation media built from stored bytes follows the same rule: a document type outside the list becomes a download only, and audio, video and image media keep their type only when it is on a fixed list |

No backend change, no migration, no permission change.
