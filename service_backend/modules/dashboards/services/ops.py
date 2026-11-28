"""Pure application of the builder's operations to a draft (contract section 5). No I/O, no model call.

``apply_operations(draft, operations)`` returns an ``Applied``: the new draft, the operations as applied
(an ``add_tile`` echoes the SS-assigned id), the ids of the tiles added or whose ``source`` / ``show``
changed, and the question when the model asked one. A badly formed operation list is not partly applied:
it comes back as ``problems`` so the caller can ask the model once more."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TILE_ID = re.compile(r"^t([0-9]{1,3})$")
MAX_OPTION_CHARS = 60


@dataclass
class Applied:
    draft: Dict[str, Any]
    operations: List[Dict[str, Any]] = field(default_factory=list)
    changed_tile_ids: List[str] = field(default_factory=list)
    question: Optional[Dict[str, Any]] = None
    problems: List[Dict[str, str]] = field(default_factory=list)


def next_free_id(tiles: List[Dict[str, Any]]) -> str:
    used = {t.get("id") for t in tiles if isinstance(t, dict)}
    nums = [int(m.group(1)) for t in used if isinstance(t, str) and (m := TILE_ID.match(t))]
    candidate = (max(nums) + 1) if nums else 1
    if candidate > 999:
        candidate = next(n for n in range(1, 1000) if f"t{n}" not in used)
    return f"t{candidate}"


def _problem(i: int, reason: str) -> Dict[str, str]:
    return {"path": f"operations[{i}]", "reason": reason}


def _index(tiles: List[Dict[str, Any]], tile_id: Any) -> int:
    for i, t in enumerate(tiles):
        if t.get("id") == tile_id:
            return i
    return -1


def _question(op: Dict[str, Any], i: int) -> tuple:
    text, options = op.get("text"), op.get("options")
    if not isinstance(text, str) or not text.strip():
        return None, _problem(i, "A question needs its text.")
    if not isinstance(options, list) or not 2 <= len(options) <= 5:
        return None, _problem(i, "A question offers between 2 and 5 answers.")
    if not all(isinstance(o, str) and 0 < len(o.strip()) <= MAX_OPTION_CHARS for o in options):
        return None, _problem(i, f"Each answer must be 1 to {MAX_OPTION_CHARS} characters.")
    return {"text": text.strip(), "options": [o.strip() for o in options]}, None


def apply_operations(draft: Dict[str, Any], operations: Any) -> Applied:
    out = Applied(draft=copy.deepcopy(draft))
    if not isinstance(operations, list):
        out.problems.append({"path": "operations", "reason": "The changes must be a list."})
        return out
    ops = [o for o in operations]
    if any(isinstance(o, dict) and o.get("op") == "ask" for o in ops) and len(ops) > 1:
        out.problems.append({"path": "operations", "reason": "A question must stand alone, with no other change."})
        return out

    tiles: List[Dict[str, Any]] = out.draft["tiles"]
    for i, op in enumerate(ops):
        kind = op.get("op") if isinstance(op, dict) else None
        if kind == "ask":
            q, problem = _question(op, i)
            if problem:
                out.problems.append(problem)
                return out
            out.question = q
            out.operations.append({"op": "ask", **q})
        elif kind == "add_tile":
            tile = op.get("tile")
            if not isinstance(tile, dict):
                out.problems.append(_problem(i, "A new chart needs its details."))
                continue
            new = {**copy.deepcopy(tile), "id": next_free_id(tiles)}
            tiles.append(new)
            out.operations.append({"op": "add_tile", "tile": copy.deepcopy(new)})
        elif kind == "change_tile":
            tile, at = op.get("tile"), _index(tiles, op.get("tile_id"))
            if at < 0:
                out.problems.append(_problem(i, "That chart does not exist, so it cannot be changed."))
            elif not isinstance(tile, dict):
                out.problems.append(_problem(i, "A changed chart needs its details."))
            else:
                tiles[at] = {**copy.deepcopy(tile), "id": tiles[at]["id"]}
                out.operations.append({"op": "change_tile", "tile_id": tiles[at]["id"], "tile": {k: v for k, v in tiles[at].items() if k != "id"}})
        elif kind == "remove_tile":
            at = _index(tiles, op.get("tile_id"))
            if at < 0:
                out.problems.append(_problem(i, "That chart does not exist, so it cannot be removed."))
            else:
                out.operations.append({"op": "remove_tile", "tile_id": tiles.pop(at)["id"]})
        elif kind == "move_tile":
            at, to = _index(tiles, op.get("tile_id")), op.get("to")
            if at < 0:
                out.problems.append(_problem(i, "That chart does not exist, so it cannot be moved."))
            elif not isinstance(to, int) or isinstance(to, bool) or not 0 <= to < len(tiles):
                out.problems.append(_problem(i, "That position does not exist."))
            else:
                tiles.insert(to, tiles.pop(at))
                out.operations.append({"op": "move_tile", "tile_id": op["tile_id"], "to": to})
        elif kind == "set_title":
            if not isinstance(op.get("title"), str):
                out.problems.append(_problem(i, "A title must be text."))
            else:
                out.draft["title"] = op["title"]
                out.operations.append({"op": "set_title", "title": op["title"]})
        elif kind == "set_period":
            if "period" not in op:
                out.problems.append(_problem(i, "A period change needs the period."))
            else:
                out.draft["period"] = copy.deepcopy(op["period"])
                out.operations.append({"op": "set_period", "period": copy.deepcopy(op["period"])})
        else:
            out.problems.append(_problem(i, "One of the changes was not understood."))

    if out.question is not None:
        out.draft = copy.deepcopy(draft)
        out.changed_tile_ids = []
        return out
    before = {t.get("id"): t for t in draft.get("tiles", []) if isinstance(t, dict)}
    for t in tiles:
        old = before.get(t.get("id"))
        if old is None or old.get("source") != t.get("source") or old.get("show") != t.get("show"):
            out.changed_tile_ids.append(t["id"])
    return out
