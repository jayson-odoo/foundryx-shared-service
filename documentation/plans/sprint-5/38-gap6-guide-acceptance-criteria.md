# Plan 38 gap 6 acceptance criteria: the consumer guide states voice, interactive replies and endpoint re-enable as the code does

Guide only: `documentation/omnichannel/consumer-integration-guide.md`. No code change. Each rule names what the guide must say; the code reference is the source of truth, and a test reads the guide.

| AC | Rule |
|---|---|
| AC-38-110 | [DOC] The send table for `voice` says it accepts ogg, and webm as recorded by a browser (`audio/webm` or `video/webm`), and that every voice note is sent to the customer as ogg/opus (`modules/omnichannel/services/media_pipeline.py` `_VOICE_INPUT_MIMES`, send runner transcode). `audio` does not take webm, and the guide does not say it does |
| AC-38-111 | [DOC] The guide does not promise `422 transcode_failed` from the send call. A voice note that cannot be converted fails later and arrives as `message.status` `FAILED`, as the guide already says elsewhere; the send call answers `202` once the file passes the type and size checks |
| AC-38-112 | [DOC] Inbound voice: a WhatsApp voice note arrives as `voice` with the provider's own type (usually `audio/ogg`), not converted |
| AC-38-113 | [DOC] The `MessageItem` `messageType` list (the shape the `message.inbound` webhook uses) includes `INTERACTIVE_REPLY`, and the payload-by-type list documents its `payload`: WhatsApp `{kind: "button" or "list", id, title, description}`, Messenger and Instagram `{kind: "quick_reply" or "postback", id, title}`; `body` is the tapped title; on WhatsApp `replyTo` names the message that carried the buttons |
| AC-38-114 | [DOC] Webhook endpoints: the guide documents the endpoint fields `status` (including `AUTO_DISABLED`), `consecutiveFailures` and `disabledReason`; that one successful delivery resets the failure count; and that while an endpoint is not `ACTIVE` no events are queued for it and none are replayed after re-enable |
| AC-38-115 | [DOC] A changelog row names the corrections above and the sections it touches |
| AC-38-116 | [DOC] A tap on a template quick-reply button arrives as messageType `BUTTON` (`modules/omnichannel/adapters/whatsapp_cloud.py`, about :878 and :925-927); the guide lists it in the `MessageItem` messageType list and documents its payload, as for `INTERACTIVE_REPLY`. In the `?format=rio` shape the tapped title is `message.text`, in the default shape `body` |

Values must match the code at the time of the change; where the code and this table differ, the code wins and the table is corrected in the same PR.
