"""Pure, evidence-backed reducer for stateful AI Agent output patches."""
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ReductionResult:
    state: Dict[str, Any]
    provenance: Dict[str, Dict[str, Any]]
    changed_fields: List[str]
    rejected_fields: List[str]


def _schema_map(schema: Any) -> Dict[str, Dict[str, Any]]:
    return {
        row["key"]: row
        for row in (schema if isinstance(schema, list) else [])
        if isinstance(row, dict)
        and isinstance(row.get("key"), str)
        and row.get("stateful") is True
    }


def _evidence_slice(message: str, evidence: Any) -> Optional[str]:
    if not isinstance(message, str) or not isinstance(evidence, str):
        return None
    wanted = unicodedata.normalize("NFKC", evidence).strip().casefold()
    if not wanted:
        return None
    normalized_parts: List[str] = []
    offsets: List[int] = [0]
    for character in message:
        normalized_parts.append(unicodedata.normalize("NFKC", character).casefold())
        offsets.append(offsets[-1] + len(normalized_parts[-1]))
    normalized = "".join(normalized_parts)
    start = normalized.find(wanted)
    if start < 0:
        return None
    end = start + len(wanted)
    original_start = next(
        (index for index, offset in enumerate(offsets[:-1]) if offset == start),
        None,
    )
    original_end = next(
        (index for index, offset in enumerate(offsets[1:], start=1) if offset == end),
        None,
    )
    if original_start is None or original_end is None:
        return None
    # Keep the original message slice so provenance shows what the user wrote,
    # even when Unicode normalization or case folding expanded a character.
    return message[original_start:original_end]


def _valid_value(value: Any, definition: Dict[str, Any]) -> bool:
    row_type = definition.get("type")
    if row_type == "string":
        return isinstance(value, str)
    if row_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if row_type == "boolean":
        return isinstance(value, bool)
    if row_type == "enum":
        return isinstance(value, str) and value in definition.get("enumValues", [])
    return False


def reduce_agent_state(
    state: Dict[str, Any],
    provenance: Dict[str, Dict[str, Any]],
    patches: Any,
    message: str,
    schema: Any,
    *,
    run_id: str,
    message_id: Optional[str],
    now: datetime,
) -> ReductionResult:
    definitions = _schema_map(schema)
    # A published definition is the current state schema. Drop removed,
    # transient, type-incompatible, or obsolete Enum values before accepting
    # patches, and surface those exclusions as rejected diagnostics.
    next_state = {
        key: value
        for key, value in (state or {}).items()
        if key in definitions and _valid_value(value, definitions[key])
    }
    next_provenance = {
        key: value
        for key, value in (provenance or {}).items()
        if key in next_state and isinstance(value, dict)
    }
    changed: List[str] = []
    rejected: List[str] = [
        key for key in (state or {}) if key not in next_state
    ]
    if not isinstance(patches, dict):
        return ReductionResult(next_state, next_provenance, changed, list(definitions))

    for key, patch in patches.items():
        definition = definitions.get(key)
        if definition is None or not isinstance(patch, dict):
            if key in definitions:
                rejected.append(key)
            continue
        operation = patch.get("operation")
        if operation == "no_change":
            continue
        if operation == "ambiguous":
            rejected.append(key)
            continue
        evidence = _evidence_slice(message, patch.get("evidence"))
        if evidence is None:
            rejected.append(key)
            continue
        if operation == "set":
            value = patch.get("value")
            if not _valid_value(value, definition):
                rejected.append(key)
                continue
            next_state[key] = value
            next_provenance[key] = {
                "runId": run_id,
                "messageId": message_id,
                "evidence": evidence,
                "updatedAt": now.isoformat(),
            }
            changed.append(key)
        elif operation == "clear":
            next_state.pop(key, None)
            next_provenance.pop(key, None)
            changed.append(key)
        else:
            rejected.append(key)

    return ReductionResult(next_state, next_provenance, changed, rejected)


__all__ = ["ReductionResult", "reduce_agent_state"]
