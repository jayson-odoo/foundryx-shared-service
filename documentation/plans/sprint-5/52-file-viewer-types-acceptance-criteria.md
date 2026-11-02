# Plan 52 acceptance criteria: file previews use a fixed set of display types

| AC | Rule |
|---|---|
| AC-52-01 | [FE] Every in-app preview of a stored file (document drive, public share page, idea attachment preview) builds its local blob with a display type from one fixed allow-list (the same helper the form file viewer uses); any other stored type is shown as a download, never rendered |
| AC-52-02 | [FE] A frame or tab that shows a preview only ever receives a blob whose type comes from the allow-list: a PDF gets `application/pdf`, and no HTML-like type reaches a frame. (Browsers do not render PDFs in a sandboxed frame, so the type is the control, as in the form file viewer.) |
| AC-52-03 | [FE] Download-only paths are unchanged |
| AC-52-04 | [FE] Conversation media built from stored bytes follows the same rule, with the same list: a type outside the list becomes a download only |
| AC-52-05 | [FE] There is ONE list and ONE helper for every viewer. Every type on it keeps its type, matched case-blind and with parameters dropped (`audio/ogg; codecs=opus` gives `audio/ogg`; `text/plain` gives `text/plain;charset=utf-8`). The list holds what users send and upload today: png, jpeg, gif, webp, x-icon images; pdf, plain text, zip and the three Office formats; ogg, mpeg, mp4, aac, amr and webm audio; mp4, 3gpp and webm video. No type on it can run script when opened |

No backend change, no migration, no permission change.
