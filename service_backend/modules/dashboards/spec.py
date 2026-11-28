"""Dashboard spec v1 validator (contract sections 2 and 4).

``validate_spec(spec)`` checks the shape and rules of section 2; ``validate_against_catalogue(spec,
catalogue)`` checks the names against the catalogue given with the turn (section 4);
``validate_catalogue(catalogue)`` checks the catalogue itself. All return a list of
``{"path", "reason"}`` (empty = ok). ``path`` is for logs; only ``reason`` is ever shown to a person, so
reasons are plain words - never validator jargon.

Pydantic v2 models (``extra="forbid"``, closed Literals, caps) own the object shapes. The three union
fields of the schema (``period``, ``group``, ``value``) are checked by hand, so their errors read plainly.
Nothing here evaluates, executes or interprets a string: names and values are only compared.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StringConstraints, ValidationError
from typing_extensions import Annotated

Problem = Dict[str, str]

MAX_TILES = 24
MAX_SPEC_BYTES = 65536
MAX_INDEX_BYTES = 20 * 1024
MAX_ENTITY_BYTES = 20 * 1024

FORBIDDEN = "Only names and values can be used in a chart, not code or links."
FORBIDDEN_SEQUENCES = ("<", ">", "://", ";", "--", "/*")

PERIODS = ("today", "yesterday", "this_week", "last_week", "this_month", "last_month",
           "this_quarter", "last_quarter", "this_year", "last_year")
SHOWS_ALL = ("number", "kpi_target", "gauge", "line", "area", "bar", "stacked_bar", "combo", "pie",
             "scatter", "heatmap", "table", "pivot", "map", "widget")
# The four charts whose shape rules SS checks (the rest are valid vocabulary; the product draws what it can).
SHOWS_NOW = ("number", "line", "bar", "table")
CALC_OPS = ("difference", "ratio", "percent_of_total", "percent_change", "running_total", "average_of",
            "sum_of", "percent_of_target")
BUCKETS = ("day", "week", "month", "quarter", "year")
AGGREGATES = ("count", "count_distinct", "sum", "avg", "min", "max")
FILTER_OPS = ("eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "contains",
              "starts_with", "is_null", "is_not_null")

_PATH_RE = r"^[a-z][a-z0-9_]{0,63}(\.[a-z][a-z0-9_]{0,63}){0,2}$"
_Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
_Path = Annotated[str, StringConstraints(pattern=_PATH_RE)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Filter(_Strict):
    field: _Path
    op: Literal[FILTER_OPS]  # type: ignore[valid-type]
    value: Any = None


class _Aggregate(_Strict):
    fn: Literal[AGGREGATES]  # type: ignore[valid-type]
    field: Optional[_Path] = None


class _Sort(_Strict):
    field: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,127}$")]
    dir: Optional[Literal["asc", "desc"]] = None


class _Query(_Strict):
    entity: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    filters: Optional[List[_Filter]] = Field(default=None, max_length=20)
    group_by: Optional[List[Any]] = Field(default=None, max_length=4)
    aggregates: Optional[List[_Aggregate]] = Field(default=None, max_length=8)
    fields: Optional[List[_Path]] = Field(default=None, max_length=8)
    sort: Optional[List[_Sort]] = Field(default=None, max_length=4)
    limit: Optional[int] = Field(default=None, ge=1, le=200)


class _Source(_Strict):
    kind: Literal["query", "report", "widget"]
    spec: _Query


_Number = Union[StrictInt, StrictFloat]


class _SeriesItem(_Strict):
    key: Annotated[str, StringConstraints(pattern=r"^s[0-9]$")]
    label: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    source: _Source
    as_: Optional[Literal["bar", "line", "area"]] = Field(default=None, alias="as")


class _Calc(_Strict):
    key: Annotated[str, StringConstraints(pattern=r"^c[0-9]$")]
    label: Optional[Annotated[str, StringConstraints(min_length=1, max_length=60)]] = None
    op: Literal[CALC_OPS]  # type: ignore[valid-type]
    args: List[Annotated[str, StringConstraints(
        pattern=r"^([a-z][a-z0-9_]{0,127}|s[0-9]\.[a-z][a-z0-9_]{0,127}|target)$")]] = Field(min_length=1, max_length=2)


class _Display(_Strict):
    legend: Optional[StrictBool] = None
    values: Optional[StrictBool] = None
    stacked: Optional[StrictBool] = None
    axis_min: Optional[_Number] = None
    axis_max: Optional[_Number] = None
    top_n: Optional[StrictInt] = Field(default=None, ge=1, le=50)
    other_bucket: Optional[StrictBool] = None


class _Size(_Strict):
    w: StrictInt = Field(ge=1, le=4)
    h: StrictInt = Field(ge=1, le=4)


class _Position(_Strict):
    x: StrictInt = Field(ge=0, le=3)
    y: StrictInt = Field(ge=0, le=99)


class _TargetValue(_Strict):
    value: _Number


class _TargetSource(_Strict):
    source: _Source


class _Tile(_Strict):
    id: Annotated[str, StringConstraints(pattern=r"^t[0-9]{1,3}$")]
    title: _Title
    show: Literal[SHOWS_ALL]  # type: ignore[valid-type]
    source: Optional[_Source] = None
    series: Optional[List[_SeriesItem]] = Field(default=None, min_length=1, max_length=4)
    calc: Optional[List[_Calc]] = Field(default=None, max_length=4)
    target: Any = None
    display: Optional[_Display] = None
    size: Optional[_Size] = None
    position: Optional[_Position] = None
    drill: Optional[Literal["list", "none"]] = None


class _Spec(_Strict):
    version: Literal[1]
    title: _Title
    period: Any
    tiles: List[_Tile] = Field(max_length=MAX_TILES)


# -- plain-words translation of pydantic errors ------------------------------------------------------

def _fmt_path(loc) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out


def _plain(err: Dict[str, Any]) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    loc = err.get("loc") or ()
    last = loc[-1] if loc else ""
    if kind == "missing":
        return "This is required."
    if kind == "extra_forbidden":
        return "This is not something a dashboard can contain."
    if kind == "literal_error":
        expected = str(ctx.get("expected", "")).replace("'", "")
        return f"This is not one of the allowed choices ({expected})." if expected else "This is not one of the allowed choices."
    if kind == "string_too_short":
        return "This cannot be empty." if ctx.get("min_length", 0) <= 1 else "This is too short."
    if kind == "string_too_long":
        return f"This is too long (at most {ctx.get('max_length')} characters)."
    if kind == "string_pattern_mismatch":
        if last == "id":
            return "A chart id looks like t1, t2 or t12."
        return "This is not written in the expected form (lowercase letters, digits and underscores)."
    if kind == "too_long":
        if last == "tiles":
            return f"A dashboard can have at most {ctx.get('max_length')} charts."
        return f"At most {ctx.get('max_length')} items are allowed here."
    if kind == "too_short":
        return "At least one item is needed here."
    if kind in ("bool_type", "bool_parsing"):
        return "This must be yes or no."
    if kind in ("greater_than_equal", "less_than_equal", "greater_than", "less_than"):
        return "This number is outside the allowed range."
    if kind.endswith("_type") or kind.endswith("_parsing"):
        return "This is the wrong kind of value."
    return "This value is not valid."


def _pydantic_problems(exc: ValidationError) -> List[Problem]:
    return [{"path": _fmt_path(e["loc"]), "reason": _plain(e)} for e in exc.errors()]


# -- hand-checked parts --------------------------------------------------------------------------------

def _scan_strings(node: Any, path: str, out: List[Problem]) -> None:
    """Recursive scan: no string anywhere (keys included) holds a forbidden sequence or control character."""
    if isinstance(node, str):
        if any(s in node for s in FORBIDDEN_SEQUENCES) or any(unicodedata.category(c) == "Cc" for c in node):
            out.append({"path": path, "reason": FORBIDDEN})
    elif isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else str(k)
            if isinstance(k, str) and (any(s in k for s in FORBIDDEN_SEQUENCES) or any(unicodedata.category(c) == "Cc" for c in k)):
                out.append({"path": sub, "reason": FORBIDDEN})
            _scan_strings(v, sub, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _scan_strings(v, f"{path}[{i}]", out)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _date(v: Any) -> Optional[_dt.date]:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return None
    try:
        return _dt.date.fromisoformat(v)
    except ValueError:
        return None


def _check_period(period: Any, out: List[Problem]) -> None:
    if isinstance(period, str):
        if period not in PERIODS:
            out.append({"path": "period", "reason": "The period must be one of: " + ", ".join(PERIODS) + "."})
        return
    if not isinstance(period, dict):
        out.append({"path": "period", "reason": "The period must be a named period or a from and to date."})
        return
    for key in period:
        if key not in ("from", "to"):
            out.append({"path": f"period.{key}", "reason": "This is not something a period can contain."})
    start, end = _date(period.get("from")), _date(period.get("to"))
    if "from" not in period:
        out.append({"path": "period.from", "reason": "This is required."})
    elif start is None:
        out.append({"path": "period.from", "reason": "This must be a real date written as year-month-day."})
    if "to" not in period:
        out.append({"path": "period.to", "reason": "This is required."})
    elif end is None:
        out.append({"path": "period.to", "reason": "This must be a real date written as year-month-day."})
    if start and end and start > end:
        out.append({"path": "period", "reason": "The start date is after the end date."})


def _group_parts(g: Any) -> Optional[tuple]:
    """(field, bucket) of a group_by item, or None when it is not a valid shape."""
    if isinstance(g, str):
        return (g, None) if re.fullmatch(_PATH_RE, g) else None
    if isinstance(g, dict) and set(g) <= {"field", "bucket"} and isinstance(g.get("field"), str):
        if not re.fullmatch(_PATH_RE, g["field"]):
            return None
        bucket = g.get("bucket")
        if bucket is not None and bucket not in BUCKETS:
            return None
        return (g["field"], bucket)
    return None


def _check_value(value: Any, path: str, out: List[Problem]) -> None:
    def scalar_ok(v: Any) -> bool:
        return (isinstance(v, str) and len(v) <= 200) or _is_number(v)

    if value is None or isinstance(value, bool) or scalar_ok(value):
        return
    if isinstance(value, list):
        if len(value) > 100:
            out.append({"path": path, "reason": "At most 100 values are allowed here."})
        elif not all(scalar_ok(v) for v in value):
            out.append({"path": path, "reason": "A list can only hold short text or numbers."})
        return
    out.append({"path": path, "reason": "This is the wrong kind of value."})


def _check_query_rules(show: str, q: Dict[str, Any], base: str, out: List[Problem]) -> None:
    aggs = q.get("aggregates") or []
    groups = q.get("group_by") or []
    fields = q.get("fields") or []
    for i, g in enumerate(groups):
        if _group_parts(g) is None:
            out.append({"path": f"{base}.group_by[{i}]", "reason": "A group is a field name, or a field with a day, week, month, quarter or year step."})
    for i, a in enumerate(aggs):
        if isinstance(a, dict) and a.get("fn") not in (None, "count") and not a.get("field"):
            out.append({"path": f"{base}.aggregates[{i}]", "reason": "Choose which field to calculate on."})
    for i, f in enumerate(q.get("filters") or []):
        if not isinstance(f, dict):
            continue
        op, fp = f.get("op"), f"{base}.filters[{i}]"
        if "value" in f:
            _check_value(f["value"], f"{fp}.value", out)
        if op in ("is_null", "is_not_null"):
            continue
        val = f.get("value")
        if "value" not in f or val is None:
            out.append({"path": f"{fp}.value", "reason": "Give a value to compare with."})
        elif op in ("in", "not_in") and not isinstance(val, list):
            out.append({"path": f"{fp}.value", "reason": "Give a list of values."})
        elif op == "between" and not (isinstance(val, list) and len(val) == 2):
            out.append({"path": f"{fp}.value", "reason": "Give exactly two values: from and to."})
        elif op not in ("in", "not_in", "between") and isinstance(val, list):
            out.append({"path": f"{fp}.value", "reason": "Give one value, not a list."})

    if show == "number":
        if len(aggs) != 1 or groups:
            out.append({"path": base, "reason": "A number shows one calculation and cannot be grouped."})
    elif show in ("line", "bar"):
        if len(groups) != 1 or len(aggs) < 1:
            out.append({"path": base, "reason": f"A {show} chart needs one group and at least one calculation."})
    elif show == "table":
        if fields and (groups or aggs):
            out.append({"path": base, "reason": "A table shows either rows or groups, not both."})
        elif not fields and not (groups and aggs):
            out.append({"path": base, "reason": "A table needs either fields to list, or a group with a calculation."})


def _check_tile_extras(tile: Dict[str, Any], base: str, out: List[Problem]) -> None:
    """Hand-checked parts of a tile: the target (value XOR source), unique series / calc keys."""
    if tile.get("target") is not None:
        target = tile["target"]
        if not isinstance(target, dict) or set(target) not in ({"value"}, {"source"}):
            out.append({"path": f"{base}.target", "reason": "A target is either a number (value) or a source, not both and not neither."})
        else:
            model = _TargetValue if "value" in target else _TargetSource
            try:
                model.model_validate(target)
            except ValidationError as exc:
                out += [{"path": f"{base}.target" + (("." + p["path"]) if p["path"] else ""), "reason": p["reason"]}
                        for p in _pydantic_problems(exc)]
    for name, key in (("series", "key"), ("calc", "key")):
        items = tile.get(name)
        if isinstance(items, list):
            keys = [i.get(key) for i in items if isinstance(i, dict)]
            if len(keys) != len(set(keys)):
                out.append({"path": f"{base}.{name}", "reason": "Two entries share the same key."})


def validate_spec(spec: Any) -> List[Problem]:
    """Section 2: shape, caps, forbidden text, slice-1 availability and chart-shape rules."""
    if not isinstance(spec, dict):
        return [{"path": "", "reason": "The dashboard must be an object."}]
    try:
        size = len(json.dumps(spec, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return [{"path": "", "reason": "The dashboard holds a value that cannot be stored."}]
    if size > MAX_SPEC_BYTES:
        return [{"path": "", "reason": "This dashboard is too large (at most 64 KB)."}]

    problems: List[Problem] = []
    _scan_strings(spec, "", problems)
    flagged = {p["path"] for p in problems}
    try:
        _Spec.model_validate(spec)
    except ValidationError as exc:
        problems += [p for p in _pydantic_problems(exc) if p["path"] not in flagged]
    if "period" in spec:
        _check_period(spec["period"], problems)

    tiles = spec.get("tiles")
    if isinstance(tiles, list):
        seen: set = set()
        for i, tile in enumerate(tiles):
            if not isinstance(tile, dict):
                continue
            base = f"tiles[{i}]"
            tid = tile.get("id")
            if isinstance(tid, str):
                if tid in seen:
                    problems.append({"path": f"{base}.id", "reason": "Two charts share the same id."})
                seen.add(tid)
            show = tile.get("show")
            source = tile.get("source") if isinstance(tile.get("source"), dict) else {}
            if ("source" in tile) == ("series" in tile):
                problems.append({"path": base, "reason": "A chart needs either one source or a list of series, not both and not neither."})
            q = source.get("spec")
            if show in SHOWS_NOW and isinstance(q, dict):
                _check_query_rules(show, q, f"{base}.source.spec", problems)
            _check_tile_extras(tile, base, problems)
    seen_paths = set()
    unique: List[Problem] = []
    for p in problems:
        key = (p["path"], p["reason"])
        if key not in seen_paths:
            seen_paths.add(key)
            unique.append(p)
    return unique


# -- catalogue ---------------------------------------------------------------------------------------

def validate_catalogue(catalogue: Any) -> List[Problem]:
    """The catalogue the CRM sends with a turn: well formed enough to check names against."""
    if not isinstance(catalogue, dict):
        return [{"path": "catalogue", "reason": "The list of available data is missing."}]
    def too_big(node: Any, cap: int) -> bool:
        try:
            return len(json.dumps(node, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > cap
        except (TypeError, ValueError):
            return True

    if too_big(catalogue.get("index", []), MAX_INDEX_BYTES):
        return [{"path": "catalogue.index", "reason": "The list of available data is too large."}]
    if isinstance(catalogue.get("entities"), list) and any(too_big(e, MAX_ENTITY_BYTES) for e in catalogue["entities"]):
        return [{"path": "catalogue.entities", "reason": "One kind of data in the list is too large."}]
    out: List[Problem] = []
    entities = catalogue.get("entities")
    if not isinstance(entities, list):
        return [{"path": "catalogue.entities", "reason": "The list of available data is missing."}]
    index = catalogue.get("index", [])
    if not isinstance(index, list) or not all(isinstance(i, dict) and isinstance(i.get("entity"), str) for i in index):
        out.append({"path": "catalogue.index", "reason": "The index of available data is not written in the expected form."})
    for i, ent in enumerate(entities):
        base = f"catalogue.entities[{i}]"
        if not isinstance(ent, dict) or not isinstance(ent.get("entity"), str) or not ent["entity"]:
            out.append({"path": base, "reason": "Each kind of data needs a name."})
            continue
        if not isinstance(ent.get("fields"), list) or not all(isinstance(f, dict) and isinstance(f.get("field"), str) for f in ent["fields"]):
            out.append({"path": f"{base}.fields", "reason": "Each kind of data needs a list of named fields."})
        rels = ent.get("relations", [])
        if not isinstance(rels, list) or not all(
            isinstance(r, dict) and isinstance(r.get("name"), str) and isinstance(r.get("fields", []), list) for r in rels
        ):
            out.append({"path": f"{base}.relations", "reason": "The related data is not written in the expected form."})
        if "show" in ent and not (isinstance(ent["show"], list) and all(isinstance(s, str) for s in ent["show"])):
            out.append({"path": f"{base}.show", "reason": "The chart types are not written in the expected form."})
    return out


class _Catalogue:
    """Name lookup over a validated catalogue."""

    def __init__(self, catalogue: Dict[str, Any]):
        self.entities: Dict[str, Dict[str, Any]] = {}
        for ent in catalogue.get("entities") or []:
            if not isinstance(ent, dict) or not isinstance(ent.get("entity"), str):
                continue
            fields = {f["field"]: str(f.get("type", "")) for f in ent.get("fields") or [] if isinstance(f, dict) and isinstance(f.get("field"), str)}
            rels: Dict[str, Dict[str, str]] = {}
            for r in ent.get("relations") or []:
                if isinstance(r, dict) and isinstance(r.get("name"), str):
                    rels[r["name"]] = {f["field"]: str(f.get("type", "")) for f in r.get("fields") or [] if isinstance(f, dict) and isinstance(f.get("field"), str)}
            self.entities[ent["entity"]] = {"fields": fields, "relations": rels, "show": ent.get("show"),
                                            "totals_allowed": ent.get("totals_allowed", True)}

    @staticmethod
    def resolve(ent: Dict[str, Any], path: str) -> Optional[str]:
        """Type of a field path (``field`` or one hop ``relation.field``), None when unknown."""
        parts = path.split(".")
        if len(parts) == 1:
            return ent["fields"].get(parts[0])
        if len(parts) == 2:
            return ent["relations"].get(parts[0], {}).get(parts[1])
        return None


_NON_NUMERIC = {"text", "string", "date", "datetime", "boolean", "bool"}
_DATE_TYPES = {"date", "datetime"}


def _short(value: Any) -> str:
    return str(value)[:60]


def validate_against_catalogue(spec: Any, catalogue: Any) -> List[Problem]:
    """Section 4/5: every entity, field path, ``show`` and bucket of every query tile is in the catalogue."""
    out: List[Problem] = []
    if not isinstance(spec, dict) or not isinstance(catalogue, dict):
        return out
    cat = _Catalogue(catalogue)
    for i, tile in enumerate(spec.get("tiles") or []):
        if not isinstance(tile, dict):
            continue
        base = f"tiles[{i}]"
        sources = [(tile["source"], f"{base}.source")] if isinstance(tile.get("source"), dict) else []
        for j, item in enumerate(tile.get("series") or []):
            if isinstance(item, dict) and isinstance(item.get("source"), dict):
                sources.append((item["source"], f"{base}.series[{j}].source"))
        target = tile.get("target")
        if isinstance(target, dict) and isinstance(target.get("source"), dict):
            sources.append((target["source"], f"{base}.target.source"))
        for source, sb in sources:
            _check_source(cat, tile, source, sb, out, whole_tile=sb == f"{base}.source")
    return out


def _check_source(cat: "_Catalogue", tile: Dict[str, Any], source: Dict[str, Any], sb: str,
                  out: List[Problem], *, whole_tile: bool) -> None:
    base = sb.split(".")[0]
    q = source.get("spec")
    if not isinstance(q, dict):
        return
    qb = f"{sb}.spec"
    name = q.get("entity")
    ent = cat.entities.get(name) if isinstance(name, str) else None
    if ent is None:
        out.append({"path": f"{qb}.entity", "reason": f'"{_short(name)}" is not available to this user.'})
        return
    show = tile.get("show")
    if not whole_tile:
        pass  # a series / target source is read as data: only its names are checked, not how the tile shows
    elif ent["totals_allowed"] is False and show != "table":
        out.append({"path": f"{base}.show", "reason": "This data can only be shown as a table."})
    elif isinstance(ent["show"], list) and show not in ent["show"]:
        out.append({"path": f"{base}.show", "reason": f"This data cannot be shown as a {_short(show)}."})

    def check(path: Any, where: str) -> Optional[str]:
        if not isinstance(path, str):
            return None
        t = cat.resolve(ent, path)
        if t is None:
            out.append({"path": where, "reason": f'"{_short(path)}" is not a field this user can use.'})
        return t

    known_aliases = set()
    for j, f in enumerate(q.get("filters") or []):
        if isinstance(f, dict):
            check(f.get("field"), f"{qb}.filters[{j}].field")
    for j, g in enumerate(q.get("group_by") or []):
        parts = _group_parts(g)
        if parts is None:
            continue
        gt = check(parts[0], f"{qb}.group_by[{j}]")
        if parts[1] and gt is not None and gt not in _DATE_TYPES:
            out.append({"path": f"{qb}.group_by[{j}]", "reason": "Only date fields can be grouped by day, week, month, quarter or year."})
        alias = parts[0].replace(".", "_")
        known_aliases.update({alias, f"{alias}_{parts[1]}"} if parts[1] else {alias})
    for j, a in enumerate(q.get("aggregates") or []):
        if not isinstance(a, dict):
            continue
        fn, fld = a.get("fn"), a.get("field")
        if fld is not None:
            at = check(fld, f"{qb}.aggregates[{j}].field")
            if fn in ("sum", "avg") and at is not None and at.lower() in _NON_NUMERIC:
                out.append({"path": f"{qb}.aggregates[{j}]", "reason": "Only number fields can be added up or averaged."})
            known_aliases.add(f"{fn}_{str(fld).replace('.', '_')}")
        elif fn == "count":
            known_aliases.add("count")
    for j, f in enumerate(q.get("fields") or []):
        check(f, f"{qb}.fields[{j}]")
        if isinstance(f, str):
            known_aliases.add(f.replace(".", "_"))
    for j, s in enumerate(q.get("sort") or []):
        if not isinstance(s, dict) or not isinstance(s.get("field"), str):
            continue
        sf = s["field"]
        if sf not in known_aliases and cat.resolve(ent, sf) is None:
            out.append({"path": f"{qb}.sort[{j}].field", "reason": f'"{_short(sf)}" is not something this chart shows, so it cannot be sorted on.'})
