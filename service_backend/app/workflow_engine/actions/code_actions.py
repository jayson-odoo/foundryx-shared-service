"""``code.run`` - the generic sandboxed Code action (sprint-4/19 S4).

The worker NEVER evaluates builder source: it renders the explicit input
mappings, submits the job to the external runner through the
``CodeRunnerClient`` seam, and validates the returned ``result`` against the
node's declared output schema before it enters the run context.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.workflow_engine.code_runner import (
    CodeRunnerUnavailable,
    get_code_runner_client,
)
from app.workflow_engine.context import render_field


class ActionError(Exception):
    pass


INPUT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SUPPORTED_LANGUAGES = ("python",)
MAX_INPUTS = 64
MAX_INPUT_VALUE_LENGTH = 64 * 1024


def code_config_issues(config: Dict[str, Any]) -> List[str]:
    """Publish-gate checks beyond the generic required-field pass: language,
    input mapping keys, and the shared static policy on the source."""
    from code_runner.policy import validate_source

    issues: List[str] = []
    language = config.get("language") or "python"
    if language not in SUPPORTED_LANGUAGES:
        issues.append(f'Code: language "{language}" is not supported.')
    inputs = config.get("inputs")
    if inputs is None:
        inputs = []
    if not isinstance(inputs, list):
        issues.append("Code: input mappings must be a list.")
    else:
        if len(inputs) > MAX_INPUTS:
            issues.append(f"Code: at most {MAX_INPUTS} input mappings are allowed.")
        seen: set[str] = set()
        for row in inputs:
            key = row.get("key") if isinstance(row, dict) else None
            if not isinstance(key, str) or not key.strip():
                issues.append("Code: every input mapping needs a name.")
                continue
            if INPUT_KEY_RE.fullmatch(key) is None:
                issues.append(f'Code: input name "{key}" must be a Python identifier.')
            elif key in seen:
                issues.append(f'Code: duplicate input name "{key}".')
            seen.add(key)
    source = config.get("source")
    if isinstance(source, str) and source.strip():
        issues.extend(f"Code: {message}" for message in validate_source(source))
    return issues


def _valid_value(value: Any, definition: Dict[str, Any]) -> bool:
    row_type = definition.get("type")
    if row_type == "string":
        return isinstance(value, str)
    if row_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if row_type == "boolean":
        return isinstance(value, bool)
    if row_type == "enum":
        return isinstance(value, str) and value in (definition.get("enumValues") or [])
    return False


def validate_declared_outputs(result: Dict[str, Any], params: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep ONLY declared keys; a mistyped or missing-required value fails."""
    accepted: Dict[str, Any] = {}
    for row in params:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str):
            continue
        key = row["key"]
        if key not in result:
            if row.get("required"):
                raise ActionError(f'Code output "{key}" is required but was not returned.')
            continue
        value = result[key]
        if value is None and not row.get("required"):
            accepted[key] = None
            continue
        if not _valid_value(value, row):
            raise ActionError(f'Code output "{key}" does not match its declared type.')
        accepted[key] = value
    return accepted


def render_inputs(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, str]:
    rendered: Dict[str, str] = {}
    for row in config.get("inputs") or []:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        if not isinstance(key, str) or INPUT_KEY_RE.fullmatch(key) is None:
            raise ActionError(f'Code input "{key}" must be a Python identifier.')
        value = render_field(row.get("value"), ctx)
        if len(value) > MAX_INPUT_VALUE_LENGTH:
            raise ActionError(f'Code input "{key}" is too large.')
        rendered[key] = value
    return rendered


_TERMINATION_MESSAGES = {
    "timeout": "Code exceeded the time limit.",
    "memory_limit": "Code exceeded the memory limit.",
    "resource_limit": "Code exceeded a CPU or memory limit.",
    "output_limit": "Code result exceeds the output size limit.",
    "source_limit": "Code exceeds the source size limit.",
    "input_limit": "Code inputs exceed the size limit.",
    "invalid_result": "Code must assign a dictionary to result.",
    "policy": "Code violates the language policy.",
    "runner_error": "The Code runner failed to execute the job.",
}


def code_run(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    del db, tenant_id  # the runner holds no platform data; nothing to scope here
    issues = code_config_issues(config)
    if issues:
        raise ActionError(issues[0])
    source = config.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ActionError("Code: source is required.")
    params = config.get("outputs") or []
    if not isinstance(params, list) or not params:
        raise ActionError("Code: declare at least one output parameter.")
    inputs = render_inputs(config, ctx)

    client = get_code_runner_client()
    if client is None or client is False:
        raise ActionError("The Code runner is not configured.")
    try:
        outcome = client.run(source, inputs)
    except CodeRunnerUnavailable as exc:
        # Transport details (URL, auth, status) stay out of the run log.
        raise ActionError("The Code runner is unavailable.") from exc

    runtime = {
        "input": inputs,
        "stdout": outcome.stdout,
        "stderr": outcome.stderr,
        "consoleTruncated": outcome.console_truncated,
        "durationMs": outcome.duration_ms,
        "runnerVersion": outcome.runner_version,
        "termination": outcome.termination,
    }
    if not outcome.ok or outcome.result is None:
        detail = outcome.error.strip()
        message = _TERMINATION_MESSAGES.get(outcome.termination, "Code failed.")
        if detail and outcome.termination in ("error", "policy", "invalid_result"):
            message = f"{message} {detail}".strip()
        raise CodeNodeFailed(message, runtime)
    accepted = validate_declared_outputs(outcome.result, params)
    return {**accepted, "runtime": runtime}


class CodeNodeFailed(ActionError):
    """Carries the bounded console + termination so the trace stays inspectable."""

    def __init__(self, message: str, runtime: Dict[str, Any]):
        super().__init__(message)
        self.runtime = runtime


__all__ = [
    "ActionError",
    "CodeNodeFailed",
    "code_config_issues",
    "code_run",
    "render_inputs",
    "validate_declared_outputs",
]
