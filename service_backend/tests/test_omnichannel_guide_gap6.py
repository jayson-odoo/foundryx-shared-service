"""Plan 38 gap 6 (AC-38-110..115): the consumer guide states voice, interactive
replies and endpoint re-enable as the code does. Reads the guide, asserts per section."""
import functools
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_GUIDE_PATH = _REPO / "documentation/omnichannel/consumer-integration-guide.md"


@functools.cache
def _guide():
    return _GUIDE_PATH.read_text()


def _section(start, end):
    i = _guide().index(start)
    j = _guide().index(end, i + len(start))
    return _guide()[i:j]


def _row(section, first_cell):
    for line in section.splitlines():
        if line.startswith("|") and line.split("|")[1].strip() == first_cell:
            return line
    raise AssertionError(f"no table row {first_cell!r}")


def _media_table():
    return _section("**Size ceilings & accepted MIME types**", "### 4.3")


def _sentences(section):
    return [s for s in re.split(r"(?<=[.!?])\s+|\n", section) if s.strip()]


def _changelog():
    return _section("> **Changelog**", "\n\n---")


# AC-38-110
def test_ac_38_110_voice_row_names_ogg_and_webm():
    row = _row(_media_table(), "voice").lower()
    assert "ogg" in row and "webm" in row


def test_ac_38_110_voice_row_names_both_webm_mime_types():
    section = _section("### 4.2", "### 4.3")
    assert "audio/webm" in section and "video/webm" in section


def test_ac_38_110_guide_says_voice_is_sent_as_ogg_opus():
    section = _section("### 4.2", "### 4.3").lower()
    assert any("voice" in s and "ogg/opus" in s for s in _sentences(section))


def test_ac_38_110_audio_row_does_not_take_webm():
    assert "webm" not in _row(_media_table(), "audio").lower()


def test_ac_38_110_control_audio_row_still_lists_ogg():
    assert "ogg" in _row(_media_table(), "audio").lower()


# AC-38-111
def test_ac_38_111_send_section_does_not_promise_transcode_failed_422():
    sec = _section("## 4. Sending messages", "## 5. Listing approved templates")
    assert "transcode_failed" not in sec


def test_ac_38_111_error_reference_media_row_does_not_list_transcode_failed():
    sec = _section("## 10. Error reference", "## 11.")
    assert "transcode_failed" not in sec


def test_ac_38_111_guide_says_unconvertible_voice_fails_later_as_message_status_failed():
    sec = _section("### 4.2", "### 4.3")
    assert any(
        "voice" in s.lower() and "FAILED" in s and "message.status" in s
        and "convert" in s.lower()
        for s in _sentences(sec)
    )


def test_ac_38_110_prose_says_audio_does_not_take_webm():
    sec = _section("### 4.2", "### 4.3")
    assert any(
        "`audio`" in s and "webm" in s.lower() and re.search(r"\bnot?\b|n't", s.lower())
        for s in _sentences(sec)
    )


def test_ac_38_111_guide_says_send_answers_202_after_type_and_size_checks():
    sec = _section("### 4.2", "### 4.3")
    assert any("202" in s and "size" in s.lower() for s in _sentences(sec))


# AC-38-112
def test_ac_38_112_inbound_voice_arrives_as_voice_with_provider_type_not_converted():
    sec = _section("## 7. Receiving events", "## 8. Media") + _section(
        "### 9.1 Default shapes", "### 9.2"
    )
    assert any(
        "voice" in s.lower() and "audio/ogg" in s and "not converted" in s.lower()
        for s in _sentences(sec)
    )


# AC-38-113
def test_ac_38_113_message_item_message_type_list_includes_interactive_reply():
    sec = _section("#### `MessageItem`", "#### `ThreadItem`")
    line = next(l for l in sec.splitlines() if '"messageType"' in l)
    block = sec[sec.index(line):]
    block = block[: block.index("\n", block.index("UNSUPPORTED"))]
    assert "INTERACTIVE_REPLY" in block


def test_ac_38_113_payload_by_type_documents_interactive_reply():
    sec = _section("* **`message.payload`**", "* **`sender.source")
    entry = next(l for l in sec.splitlines() if "interactive_reply" in l.lower())
    for token in ("kind", "id", "title", "description", "button", "list", "quick_reply", "postback"):
        assert token in entry, token


def test_ac_38_113_body_is_the_tapped_title_and_reply_to_names_the_buttons_message():
    sec = _section("* **`message.payload`**", "* **`sender.source")
    text = sec.lower()
    assert "tapped title" in text
    assert "replyto" in text


def test_ac_38_113_description_is_in_the_whatsapp_reply_payload():
    sec = _section("* **`message.payload`**", "* **`sender.source")
    entry = next(l for l in sec.splitlines() if "interactive_reply" in l.lower())
    whatsapp = entry.split("Messenger")[0]
    assert "description" in whatsapp


def test_ac_38_113_control_interactive_payload_entry_kept():
    sec = _section("* **`message.payload`**", "* **`sender.source")
    assert "`interactive` →" in sec


# AC-38-114
def _endpoints():
    return _section("### Registering your callbacks", "## 8. Media") + _section(
        "### Delivery guarantees", "### Registering your callbacks"
    )


def test_ac_38_114_endpoint_fields_documented():
    sec = _endpoints()
    for token in ("AUTO_DISABLED", "consecutiveFailures", "disabledReason"):
        assert token in sec, token


def test_ac_38_114_fields_line_is_in_the_endpoint_section_itself():
    sec = _section("### Registering your callbacks", "## 8. Media")
    assert any(
        all(t in s for t in ("status", "consecutiveFailures", "disabledReason"))
        for s in _sentences(sec)
    )


def test_ac_38_114_re_enable_replays_nothing():
    sec = _section("### Delivery guarantees", "### Registering your callbacks")
    assert any(
        "re-enabled" in s.lower() and "replay" in s.lower() and "queue" in s.lower()
        for s in _sentences(sec)
    )


def test_ac_38_114_one_success_resets_the_count():
    sec = _endpoints()
    assert any(
        "success" in s.lower() and "reset" in s.lower() and "consecutiveFailures" in s
        for s in _sentences(sec)
    )


def test_ac_38_114_no_queue_or_replay_while_not_active():
    sec = _endpoints()
    assert any(
        "ACTIVE" in s and "queue" in s.lower() and "replay" in s.lower()
        and "AUTO_DISABLED" in s
        for s in _sentences(sec)
    )


def test_ac_38_114_control_enable_route_still_documented():
    assert "/webhooks/{id}/enable" in _endpoints()


# AC-38-115
def test_ac_38_115_changelog_row_names_interactive_reply_and_voice_webm():
    rows = [l for l in _changelog().splitlines() if l.startswith("> |")]
    assert any(
        "INTERACTIVE_REPLY" in r and "voice" in r.lower() and "webm" in r.lower()
        for r in rows
    )


def test_ac_38_115_changelog_row_names_section_9_2():
    rows = [l for l in _changelog().splitlines() if l.startswith("> |")]
    assert any("INTERACTIVE_REPLY" in r and re.search(r"9\.2", r) for r in rows)


# AC-38-116
def _payload_list():
    return _section("* **`message.payload`**", "* **`sender.source")


def test_ac_38_116_message_item_message_type_list_includes_button():
    sec = _section("#### `MessageItem`", "#### `ThreadItem`")
    start = sec.index('"messageType"')
    block = sec[start: sec.index("\n", sec.index("UNSUPPORTED", start))]
    assert re.search(r"\bBUTTON\b", block)


def test_ac_38_116_payload_list_documents_the_button_type():
    entries = [l for l in _payload_list().splitlines() if l.strip().startswith("*")]
    entry = next(
        (l for l in entries if re.search(r"`button`\s*(→|->)|\bBUTTON\b", l)
         and "interactive_reply" not in l.lower()),
        None,
    )
    assert entry is not None
    assert "null" in entry.lower() and "template" in entry.lower()


def test_ac_38_116_rio_notes_say_the_tapped_title_is_text():
    sec = _section("### 9.2", "### 9.3")
    assert any("tapped title" in s and "`text`" in s for s in _sentences(sec))


def test_ac_38_116_rio_notes_do_not_say_body_is_the_tapped_title():
    sec = _section("### 9.2", "### 9.3")
    assert "`body` is the tapped title" not in sec
