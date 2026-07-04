"""Iterator expansion pass (plan sprint-3/03 D4/D5) — table + repeater.

Repetition is STRUCTURAL: a table/repeater block iterates a LIST fact and the
expand pass stamps out concrete blocks BEFORE either compiler runs (MJML email
or PDF). The merge renderer stays substitution-only — this module produces the
repeated STRUCTURE; ``render_tokens`` fills the values downstream.

Run order in both render seams: prune-by-conditions → **expand** → compile.
The pass is a no-op for docs with no table/repeater (every existing email
template is unchanged).

- ``TableBlock`` → a ``CustomHtmlBlock`` carrying a fully-built ``<table>``
  (thead from columns, one tbody row per source item, tfoot from footer rows).
  A single pre-rendered HTML block is the simplest representation both
  compilers already understand (PDF emits it directly; MJML wraps it in
  ``mj-raw``). Row/footer cells keep their merge tokens — they substitute at
  compile time against the row/context facts.
- ``RepeaterBlock`` → its body leaf blocks deep-copied once per source item,
  with every ``{{ row.<k> }}`` token rewritten to a per-item context key so the
  substitution-only renderer resolves it (``row.*`` is rewritten to a unique
  ``__row_<id>.<k>`` key injected into the facts).

Single level only (the schema forbids table/repeater nesting). Rows are plain
dicts (merge-only — no per-row rule conditions; that bridge is backlogged).
"""

import html as html_mod
import re
from typing import Any, Dict, List, Sequence, Tuple

from app.template_engine.merge import render_tokens
from app.template_engine.schemas import (
    CustomHtmlBlock,
    RepeaterBlock,
    TableBlock,
    TemplateBlockModel,
    TemplateColumnModel,
    TemplateDocumentModel,
)

# Reserved facts namespace for repeater row scope (see _expand_repeater).
_ROW_FACT_PREFIX = "__row"
# Matches a merge token whose key starts with ``row.`` — scopes the per-item
# rebind to tokens only (never literal text / unrelated tokens).
_ROW_TOKEN_RE = re.compile(r"\{\{(\s*)row\.([\w.]*\s*)\}\}")


def has_iterators(doc: TemplateDocumentModel) -> bool:
    """True if any block needs the expansion pass (cheap guard for the email
    seam — docs without iterators skip expansion entirely)."""
    for _s, _c, block in doc.iter_blocks():
        if isinstance(block, (TableBlock, RepeaterBlock)):
            return True
    return False


def _source_rows(source: str, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The list bound to a table/repeater ``source``. Falls back to '' on a
    missing source (preview callers inject the list-fact sample into facts, so
    a live binding is the only path that can be empty)."""
    rows = facts.get(source)
    if not isinstance(rows, (list, tuple)):
        return []
    return [dict(r) if isinstance(r, dict) else {} for r in rows]


def _td_style(align: str) -> str:
    return f"text-align:{html_mod.escape(align, quote=True)}"


def _table_html(
    block: TableBlock, rows: Sequence[Dict[str, Any]], facts: Dict[str, Any], mode: str
) -> str:
    """Build the table markup with cell values ALREADY merged + HTML-escaped.

    Rendering values here (not as leftover tokens) keeps the substitution-only
    contract AND ensures attendee/row-controlled values are escaped — the
    surrounding CustomHtmlBlock compiles with escape=False (table tags must
    survive), so an un-escaped value would inject markup. Body cells merge
    against the row dict; footer cells merge scalar context facts (totals)."""
    head_cells = "".join(
        f'<th style="{_td_style(col.align)}">{html_mod.escape(col.header)}</th>'
        for col in block.columns
    )
    thead = f"<thead><tr>{head_cells}</tr></thead>"

    body_rows: List[str] = []
    for row in rows:
        cells = "".join(
            f'<td style="{_td_style(col.align)}">'
            f"{render_tokens('{{ ' + col.key + ' }}', row, mode=mode, escape=True)}</td>"
            for col in block.columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    tbody = f'<tbody>{"".join(body_rows)}</tbody>'

    tfoot = ""
    if block.footer:
        foot_rows: List[str] = []
        for frow in block.footer:
            fcells = "".join(
                f'<td style="{_td_style(cell.align)}" colspan="{cell.span}">'
                f"{render_tokens(cell.text, facts, mode=mode, escape=True)}</td>"
                for cell in frow.cells
            )
            foot_rows.append(f"<tr>{fcells}</tr>")
        tfoot = f'<tfoot>{"".join(foot_rows)}</tfoot>'

    return f'<table class="tpl-table">{thead}{tbody}{tfoot}</table>'


def _rewrite_row_tokens(value: str, idx: int) -> str:
    """``{{ row.<k> }}`` → ``{{ __row<idx>.<k> }}`` (per-item context key).

    Scoped to MERGE TOKENS only (and only the ``row.`` prefix) — a blanket
    ``str.replace("row.", …)`` corrupts literal copy like ``tomorrow.`` or an
    unrelated token like ``{{ arrow.size }}`` (code-review fix)."""
    return _ROW_TOKEN_RE.sub(
        lambda m: "{{" + m.group(1) + _ROW_FACT_PREFIX + str(idx) + "." + m.group(2) + "}}",
        value,
    )


def _rewrite_block_row_tokens(block: TemplateBlockModel, idx: int) -> TemplateBlockModel:
    """A deep copy of a repeater-body leaf block with its row.* tokens rebound
    to the per-item key. Only the token-bearing fields are rewritten."""
    updates: Dict[str, Any] = {"id": f"{block.id}__r{idx}"}
    # Mirror _block_token_values' field set (leaf blocks only inside a body).
    for fld in ("text", "html", "label", "href", "src"):
        if hasattr(block, fld):
            current = getattr(block, fld)
            if isinstance(current, str) and "row." in current:
                updates[fld] = _rewrite_row_tokens(current, idx)
    return block.model_copy(update=updates)


def _expand_repeater(
    block: RepeaterBlock, rows: Sequence[Dict[str, Any]]
) -> Tuple[List[TemplateBlockModel], Dict[str, Any]]:
    """Stamp the body once per source row. Returns the expanded blocks plus the
    per-item facts to merge into the render facts (``__row<idx>.<k>``)."""
    expanded: List[TemplateBlockModel] = []
    extra_facts: Dict[str, Any] = {}
    for idx, row in enumerate(rows):
        for key, val in row.items():
            extra_facts[f"{_ROW_FACT_PREFIX}{idx}.{key}"] = val
        for child in block.body:
            expanded.append(_rewrite_block_row_tokens(child, idx))
    return expanded, extra_facts


def _expand_table(
    block: TableBlock, rows: Sequence[Dict[str, Any]], facts: Dict[str, Any], mode: str
) -> CustomHtmlBlock:
    """Table → a pre-rendered CustomHtmlBlock with cell values fully merged +
    escaped (no leftover tokens — the compiler emits the markup verbatim)."""
    return CustomHtmlBlock(
        id=f"{block.id}__expanded",
        type="customHtml",
        html=_table_html(block, rows, facts, mode),
        conditionsJson=block.conditions_json,
    )


def expand_iterators(
    doc: TemplateDocumentModel, facts: Dict[str, Any], *, mode: str = "send"
) -> Tuple[TemplateDocumentModel, Dict[str, Any]]:
    """Expand every table/repeater into concrete blocks.

    Returns the new doc AND the augmented facts (the original facts plus the
    per-row ``__row<idx>.<k>`` entries the expanded blocks reference). The
    augmented facts are what the compiler must render against.

    The list-fact sample is the fallback source for preview — callers inject it
    into ``facts`` under the list-fact key (so this pass sees a live binding or
    a sample identically). Whole-table/repeater visibility (a condition on the
    block itself) is preserved: tables carry it onto the pre-rendered block;
    repeaters are pruned-or-kept by the earlier prune pass before they reach
    here (a conditioned repeater that survived pruning expands in full).
    """
    if not has_iterators(doc):
        return doc, facts

    augmented = dict(facts)
    sections = []
    for section in doc.sections:
        columns = []
        for column in section.columns:
            new_blocks: List[TemplateBlockModel] = []
            for block in column.blocks:
                if isinstance(block, TableBlock):
                    rows = _source_rows(block.source, facts)
                    new_blocks.append(_expand_table(block, rows, facts, mode))
                elif isinstance(block, RepeaterBlock):
                    rows = _source_rows(block.source, facts)
                    expanded, extra = _expand_repeater(block, rows)
                    augmented.update(extra)
                    new_blocks.extend(expanded)
                else:
                    new_blocks.append(block)
            columns.append(column.model_copy(update={"blocks": new_blocks}))
        sections.append(section.model_copy(update={"columns": columns}))

    return doc.model_copy(update={"sections": sections}), augmented


__all__ = ["expand_iterators", "has_iterators"]
