"""DEV-ONLY: synthetic AutoCount-shaped source DB for the local parity proof
(plan sprint-5/02 S4 prep - no production code, dev fixture only).

    python -m scripts.seed_autocount_shape_source                  # build/refresh ac_sim (idempotent)
    python -m scripts.seed_autocount_shape_source --open-po 3       # + force 3 settled PO lines open
    python -m scripts.seed_autocount_shape_source --spo 2           # + clone 2 PO docs as SPO- docs
    python -m scripts.seed_autocount_shape_source --open-po 3 --spo 2

Creates a Postgres schema **`ac_sim`** (in the SAME `foundryx_service` database
this process' own `DATABASE_URL` points at - no second server) with tables
named/columned like a real AutoCount 2.x company database (the shapes come
from `documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md`'s SQL
pack, `modules/autocount/presets/` does not exist yet so this is the
authoritative source): ``SO``, ``SODTL``, ``PO``, ``PODTL``, ``Debtor``,
``Creditor``, ``Item``, ``ItemUOM``, ``Location``, ``SalesAgent``. The intent
is that a plan-02 SO/PO source preset, built against the pack's
``AED_SORENTO.dbo.<table>`` queries, runs UNCHANGED here after a
``{database}.dbo`` -> ``ac_sim`` string swap.

    !!  THIS IS A DEV FIXTURE, NOT A PRODUCT TABLE SET.  !!

Filled from the two Sorento oracle books (real AutoCount exports, not
hand-typed data) named in
``.claude/handoffs/20260904T170346Z-sorento-oracle-and-alias-table.md``:

- SO: ``~/Desktop/Dealer oustanding 2022 - 2025.xlsx`` (462 rows, real headers
  Doc No/Doc Date/Delivery Date/Debtor Code/Debtor Name/Agent/Item Code/
  Item Description/Location/Qty/Transfered Qty/Remaining Qty/Unit Price/
  Discount/Total (Inc)/Note - dates are RAW EXCEL SERIALS, no UOM column).
- PO/SPO: ``sorento-crm/.../fixtures/po_spo_history_sample.xlsx`` (33 rows,
  real AutoCount PO/SPO export - Doc No/Doc Date/Creditor Name/Agent/
  Item Code/Location/Qty/Transfered Qty/Remaining Qty/Delivery Date/
  FromSODocList; no Unit Price column, no Creditor Code column, dates are
  real ``datetime`` cells).

Transform rules (deliberately simple + deterministic - never random):
- ``AutoKey``/``DocKey``/``DtlKey`` = a stable 1-based integer assigned by
  SORTING the natural key (DocNo / (DocNo,ItemCode,seq) / AccNo-ItemCode-
  Location-Agent) - see ``assign_keys``. Same input -> same ids every run.
- ``Cancelled = 'F'`` on every header (AutoCount's ``d_Boolean`` convention).
- ``TransferedQty = Qty - RemainingQty`` (``RemainingQty`` if present else 0)
  - the CANONICAL figure this rig computes, not the oracle's own "Transfered
    Qty" column (which can be internally inconsistent in a real export) -
    see ``_transfered_qty``.
- ``LastModified = now()`` on every header/master row at seed time.
- Masters (``Debtor``/``Creditor``/``Item``/``Location``/``SalesAgent``) are
  DERIVED from the distinct values the document rows carry - see
  ``derive_debtors``/``derive_creditors``/``derive_items``/
  ``derive_locations``/``derive_sales_agents``. The PO/SPO oracle has no
  creditor CODE column - ``_creditor_code`` mints a stable synthetic one from
  the name.

``--open-po N`` deterministically flips the first N SETTLED PO lines (by
sorted (DocNo, ItemCode) - ``mark_po_rows_open``) to OPEN (RemainingQty > 0,
i.e. ``TransferedQty < Qty``) so the outstanding-PO path has live data (most
of the oracle's PO rows are already fully received).

``--spo N`` deterministically clones the first N PO docs (by sorted DocNo -
``clone_spo_docs``) as `` SPO-``-prefixed docs (Sorento's outstanding_po
alias treats an ``SPO-`` DocNo as a shipping order, never a purchase order)
so the SPO path has live data too.

Every table is a plain UPSERT keyed on its integer PK (``ON CONFLICT ...
DO UPDATE``), so re-running with a DIFFERENT ``--open-po``/``--spo`` N
updates the same deterministic rows in place rather than leaving stale state
from an earlier run.

xlsx columns this rig does NOT map into ``ac_sim`` (present in one of the two
oracle books but with no target column in the SQL pack's SO/PO/PODTL shape,
and no consumer downstream of the pack): SO oracle's ``Ref Doc No``/``Ref``/
``Remark 1``; PO/SPO oracle's ``Loading Date``/``Ref``/``Shipping Order``/
``ICB Name``/``Account Book``/``Is Posted``/``Running No``/
``Post Gross Figure``/``Enable Auto Price``/``ICB To DocNo``/
``IB From SOKey``/``Import Post``/``Desc2``/``Width``/``Standard Price``
(these mirror Sorento's own "resolved but dropped" / "no alias" columns in
the handoff's alias table one-for-one).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import openpyxl
from openpyxl.utils.datetime import from_excel
from sqlalchemy import text

from app.config import settings
from app.database import engine

SCHEMA = "ac_sim"

DEFAULT_SO_XLSX = "/Users/tehjayson/Desktop/Dealer oustanding 2022 - 2025.xlsx"
DEFAULT_PO_XLSX = (
    "/Users/tehjayson/Documents/foundryx/sorento-crm/sorento_crm_backend/"
    "tests/scm/fixtures/po_spo_history_sample.xlsx"
)


# ---------------------------------------------------------------------------
# Pure transform functions - unit-tested directly in
# tests/test_seed_autocount_shape_source.py with inline sample rows (the
# real oracle xlsx paths live OUTSIDE the repo, so the DB/xlsx-touching
# driver below is exercised only by a real local run, never by pytest).
# ---------------------------------------------------------------------------


def _num(value: Any) -> Optional[float]:
    """Blank/None -> None (never 0 - a genuinely-absent figure must stay
    absent, not silently zero)."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _transfered_qty(qty: Optional[float], remaining: Optional[float]) -> float:
    """AutoCount-shape ``TransferedQty`` = ``Qty - RemainingQty`` (Remaining
    if present else 0) - the rig's own canonical figure (see module
    docstring); deliberately ignores the oracle's own "Transfered Qty"
    column."""
    q = qty or 0.0
    r = remaining if remaining is not None else 0.0
    return q - r


def _excel_date(value: Any) -> Optional[date]:
    """Accept a real ``datetime``/``date`` (PO/SPO oracle) OR a raw Excel
    serial number (SO oracle - its date columns are ``General``-formatted,
    so openpyxl hands back a plain int/float, not a datetime)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return from_excel(value).date()
    return None


def _creditor_code(name: str) -> str:
    """The PO/SPO oracle carries no creditor CODE column (only Creditor
    Name) - mint a stable synthetic ``AccNo`` from the name. Deterministic
    (same name -> same code every run), never random."""
    slug = "".join(ch for ch in str(name).upper() if ch.isalnum())[:10] or "UNKNOWN"
    return f"CR-{slug}"


def build_so_rows(
    raw_rows: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """SO oracle row (Desktop 'Dealer outstanding' xlsx headers) ->
    (SO header dict keyed by DocNo, SODTL line dict list). Pure - no xlsx/DB
    IO; the caller reads the workbook and passes plain dicts in."""
    headers: Dict[str, Dict[str, Any]] = {}
    lines: List[Dict[str, Any]] = []
    for row in raw_rows:
        doc_no = str(row.get("Doc No") or "").strip()
        if not doc_no:
            continue
        header = headers.setdefault(
            doc_no,
            {
                "doc_no": doc_no,
                "doc_date": _excel_date(row.get("Doc Date")),
                "debtor_code": row.get("Debtor Code"),
                "debtor_name": row.get("Debtor Name"),
                "sales_agent": row.get("Agent"),
                "note": None,
            },
        )
        if not header.get("note") and row.get("Note"):
            header["note"] = row.get("Note")
        item_code = row.get("Item Code")
        if not item_code:
            continue
        qty = _num(row.get("Qty")) or 0.0
        remaining = _num(row.get("Remaining Qty"))
        lines.append(
            {
                "doc_no": doc_no,
                "item_code": item_code,
                "description": row.get("Item Description"),
                "location": row.get("Location"),
                "qty": qty,
                "transfered_qty": _transfered_qty(qty, remaining),
                "unit_price": _num(row.get("Unit Price")),
                "discount_amt": _num(row.get("Discount")),
                "sub_total": _num(row.get("Total (Inc)")),
                "delivery_date": _excel_date(row.get("Delivery Date")),
            }
        )
    return headers, lines


def build_po_rows(
    raw_rows: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """PO/SPO oracle row -> (PO header dict keyed by DocNo, PODTL line dict
    list). Pure - see ``build_so_rows``."""
    headers: Dict[str, Dict[str, Any]] = {}
    lines: List[Dict[str, Any]] = []
    for row in raw_rows:
        doc_no = str(row.get("Doc No") or "").strip()
        if not doc_no:
            continue
        creditor_name = row.get("Creditor Name")
        header = headers.setdefault(
            doc_no,
            {
                "doc_no": doc_no,
                "doc_date": _excel_date(row.get("Doc Date")),
                "creditor_name": creditor_name,
                "creditor_code": _creditor_code(creditor_name) if creditor_name else None,
                "purchase_agent": row.get("Agent"),
            },
        )
        item_code = row.get("Item Code")
        if not item_code:
            continue
        qty = _num(row.get("Qty")) or 0.0
        remaining = _num(row.get("Remaining Qty"))
        lines.append(
            {
                "doc_no": doc_no,
                "item_code": item_code,
                "description": row.get("Description"),
                "location": row.get("Location"),
                "qty": qty,
                "transfered_qty": _transfered_qty(qty, remaining),
                # No Unit Price column in the PO/SPO oracle - unit_cost stays
                # NULL (module docstring "Implication" note).
                "unit_price": None,
                "discount_amt": None,
                "sub_total": None,
                "delivery_date": _excel_date(row.get("Delivery Date")),
                "from_so_doc_list": row.get("FromSODocList"),
            }
        )
    return headers, lines


def mark_po_rows_open(lines: Sequence[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """Return a NEW line list with the first ``n`` SETTLED lines (by the
    given order - callers pass them pre-sorted by (doc_no, item_code) for
    determinism) flipped OPEN: ``transfered_qty`` forced below ``qty`` so
    ``qty - transfered_qty`` (the outstanding figure) turns positive. Never
    mutates the input list/dicts. A no-op when ``n <= 0``."""
    if n <= 0:
        return list(lines)
    out: List[Dict[str, Any]] = []
    flipped = 0
    for row in lines:
        qty = row.get("qty") or 0.0
        transfered = row.get("transfered_qty") or 0.0
        settled = qty > 0 and transfered >= qty
        if settled and flipped < n:
            row = dict(row)
            # Leave at least 1 unit outstanding (never flip a zero-qty line
            # "open" - there would be nothing to receive).
            row["transfered_qty"] = max(qty - 1, 0.0)
            flipped += 1
        out.append(row)
    return out


def clone_spo_docs(
    headers: Dict[str, Dict[str, Any]],
    lines: Sequence[Dict[str, Any]],
    n: int,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Return NEW (headers, lines) with the first ``n`` doc numbers (sorted -
    deterministic) cloned under an ``SPO-``-prefixed DocNo (Sorento's
    outstanding_po alias treats an ``SPO-`` DocNo as a shipping order, never
    a purchase order - see the handoff doc). Never mutates the inputs."""
    new_headers = dict(headers)
    new_lines = list(lines)
    if n <= 0:
        return new_headers, new_lines
    lines_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for row in lines:
        lines_by_doc.setdefault(row["doc_no"], []).append(row)
    for doc_no in sorted(headers)[:n]:
        spo_doc_no = f"SPO-{doc_no}"
        cloned_header = dict(headers[doc_no])
        cloned_header["doc_no"] = spo_doc_no
        new_headers[spo_doc_no] = cloned_header
        for row in lines_by_doc.get(doc_no, []):
            cloned_line = dict(row)
            cloned_line["doc_no"] = spo_doc_no
            new_lines.append(cloned_line)
    return new_headers, new_lines


def assign_keys(
    natural_keys: Sequence[str], existing: Optional[Dict[str, int]] = None
) -> Dict[str, int]:
    """Stable integer id per DISTINCT natural key.

    Without ``existing``: a 1-based id assigned by sorting the keys -
    "deterministic from row order" (same input set -> same ids every run,
    never random/hash-based).

    With ``existing`` (rig defect fix, coordinator finding): a real
    AutoCount key never moves once assigned, so a RE-SEED must never
    renumber a code that is already present in the target table. Every
    natural key already in ``existing`` KEEPS its existing id untouched;
    only genuinely NEW natural keys are minted, starting at
    ``max(existing.values()) + 1`` and counting up in sorted order (so two
    new codes arriving in the same run still rank deterministically
    relative to each other, not by incidental iteration order)."""
    distinct = sorted(set(natural_keys))
    if not existing:
        return {key: i + 1 for i, key in enumerate(distinct)}
    result: Dict[str, int] = {}
    new_codes = []
    for key in distinct:
        if key in existing:
            result[key] = existing[key]
        else:
            new_codes.append(key)
    next_id = max(existing.values(), default=0) + 1
    for key in sorted(new_codes):
        result[key] = next_id
        next_id += 1
    return result


def derive_debtors(so_headers: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Debtor master from SO headers' distinct (DebtorCode, DebtorName)."""
    seen: Dict[str, Dict[str, Any]] = {}
    for header in so_headers.values():
        code = header.get("debtor_code")
        if not code or code in seen:
            continue
        seen[code] = {
            "acc_no": code,
            "company_name": header.get("debtor_name"),
            "sales_agent": header.get("sales_agent"),
        }
    return [seen[k] for k in sorted(seen)]


def derive_creditors(po_headers: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Creditor master from PO headers' distinct (synthetic code, name)."""
    seen: Dict[str, Dict[str, Any]] = {}
    for header in po_headers.values():
        code = header.get("creditor_code")
        if not code or code in seen:
            continue
        seen[code] = {
            "acc_no": code,
            "company_name": header.get("creditor_name"),
            "purchase_agent": header.get("purchase_agent"),
        }
    return [seen[k] for k in sorted(seen)]


def derive_items(
    so_lines: Sequence[Dict[str, Any]], po_lines: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Item master from distinct ItemCode (+ its first-seen Description)
    across BOTH document sources."""
    seen: Dict[str, Dict[str, Any]] = {}
    for row in list(so_lines) + list(po_lines):
        code = row.get("item_code")
        if not code or code in seen:
            continue
        seen[code] = {"item_code": code, "description": row.get("description")}
    return [seen[k] for k in sorted(seen)]


def derive_locations(
    so_lines: Sequence[Dict[str, Any]], po_lines: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Warehouse master from distinct Location across both sources."""
    seen: set = set()
    for row in list(so_lines) + list(po_lines):
        loc = row.get("location")
        if loc:
            seen.add(loc)
    return [{"location": loc} for loc in sorted(seen)]


def derive_sales_agents(
    so_headers: Dict[str, Dict[str, Any]], po_headers: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """SalesAgent master from distinct Agent code across SO (sales agent) and
    PO (purchase agent) headers - AutoCount shares ONE agent registry for
    both roles."""
    seen: set = set()
    for header in so_headers.values():
        agent = header.get("sales_agent")
        if agent:
            seen.add(agent)
    for header in po_headers.values():
        agent = header.get("purchase_agent")
        if agent:
            seen.add(agent)
    return [{"agent": agent} for agent in sorted(seen)]


# ---------------------------------------------------------------------------
# xlsx IO (thin - hands rows to the pure builders above)
# ---------------------------------------------------------------------------


def _read_xlsx_rows(path: str) -> List[Dict[str, Any]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows_iter)]
    out: List[Dict[str, Any]] = []
    for values in rows_iter:
        if values is None or all(v is None for v in values):
            continue
        out.append(dict(zip(header, values)))
    return out


# ---------------------------------------------------------------------------
# DDL + upsert driver (real Postgres IO - not exercised by pytest)
# ---------------------------------------------------------------------------

DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {SCHEMA}."SO" (
    "DocKey"        integer PRIMARY KEY,
    "DocNo"         text NOT NULL UNIQUE,
    "DocDate"       date,
    "LastModified"  timestamptz NOT NULL DEFAULT now(),
    "DebtorCode"    text,
    "DebtorName"    text,
    "SalesAgent"    text,
    "CurrencyCode"  text DEFAULT 'MYR',
    "Note"          text,
    "Cancelled"     char(1) NOT NULL DEFAULT 'F',
    "UDF_DelDate"   date
);
-- The SO preset (SF2) reads the requested-delivery-date override off this
-- UDF column; ADD COLUMN IF NOT EXISTS keeps this idempotent against an
-- already-seeded local database that predates the column.
ALTER TABLE {SCHEMA}."SO" ADD COLUMN IF NOT EXISTS "UDF_DelDate" date;

CREATE TABLE IF NOT EXISTS {SCHEMA}."SODTL" (
    "DtlKey"        integer PRIMARY KEY,
    "DocKey"        integer NOT NULL REFERENCES {SCHEMA}."SO"("DocKey"),
    "Seq"           integer NOT NULL,
    "ItemCode"      text NOT NULL,
    "Location"      text,
    "Description"   text,
    "Qty"           numeric(18,4) NOT NULL DEFAULT 0,
    "TransferedQty" numeric(18,4) NOT NULL DEFAULT 0,
    "UnitPrice"     numeric(18,4),
    "DiscountAmt"   numeric(18,4),
    "SubTotal"      numeric(18,4),
    "UOM"           text,
    "DeliveryDate"  date
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."PO" (
    "DocKey"        integer PRIMARY KEY,
    "DocNo"         text NOT NULL UNIQUE,
    "DocDate"       date,
    "LastModified"  timestamptz NOT NULL DEFAULT now(),
    "CreditorCode"  text,
    "CreditorName"  text,
    "PurchaseAgent" text,
    "CurrencyCode"  text DEFAULT 'MYR',
    "Cancelled"     char(1) NOT NULL DEFAULT 'F'
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."PODTL" (
    "DtlKey"          integer PRIMARY KEY,
    "DocKey"          integer NOT NULL REFERENCES {SCHEMA}."PO"("DocKey"),
    "Seq"             integer NOT NULL,
    "ItemCode"        text NOT NULL,
    "Location"        text,
    "Description"     text,
    "Qty"             numeric(18,4) NOT NULL DEFAULT 0,
    "TransferedQty"   numeric(18,4) NOT NULL DEFAULT 0,
    "UnitPrice"       numeric(18,4),
    "DiscountAmt"     numeric(18,4),
    "SubTotal"        numeric(18,4),
    "UOM"             text,
    "DeliveryDate"    date,
    "FromSODocList"   text
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."Debtor" (
    "AutoKey"       integer PRIMARY KEY,
    "AccNo"         text NOT NULL UNIQUE,
    "CompanyName"   text,
    "SalesAgent"    text,
    "IsActive"      char(1) NOT NULL DEFAULT 'T',
    "LastModified"  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."Creditor" (
    "AutoKey"        integer PRIMARY KEY,
    "AccNo"          text NOT NULL UNIQUE,
    "CompanyName"    text,
    "PurchaseAgent"  text,
    "IsActive"       char(1) NOT NULL DEFAULT 'T',
    "LastModified"   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."Item" (
    "AutoKey"       integer PRIMARY KEY,
    "ItemCode"      text NOT NULL UNIQUE,
    "Description"   text,
    "BaseUOM"       text DEFAULT 'UNIT',
    "IsActive"      char(1) NOT NULL DEFAULT 'T',
    "LastModified"  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."ItemUOM" (
    "AutoKey"            integer PRIMARY KEY,
    "ItemCode"           text NOT NULL,
    "UOM"                text NOT NULL,
    "IsBaseUOM"          char(1) NOT NULL DEFAULT 'T',
    "ConversionFactor"   numeric(18,6) NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."Location" (
    "AutoKey"       integer PRIMARY KEY,
    "Location"      text NOT NULL UNIQUE,
    "IsActive"      char(1) NOT NULL DEFAULT 'T'
);

CREATE TABLE IF NOT EXISTS {SCHEMA}."SalesAgent" (
    "Agent"         text PRIMARY KEY,
    "Description"   text,
    "IsActive"      char(1) NOT NULL DEFAULT 'T'
);
"""


def _guard() -> None:
    if settings.environment != "development":
        raise SystemExit(
            f"Refusing to seed the AutoCount-shape source in '{settings.environment}'. "
            "This is a development fixture."
        )


def _read_existing_keys(conn, table: str, key_col: str, natural_col: str) -> Dict[str, int]:
    """Rig defect fix (coordinator finding): the natural-key -> integer-id map
    already committed in the target table, read back so a re-seed can REUSE
    every key that's already there instead of re-ranking the whole set from
    scratch (a real AutoCount key never moves once assigned). Empty on a
    fresh table - `assign_keys` falls back to its from-scratch numbering
    then, unchanged from before this fix."""
    rows = conn.execute(
        text(f'SELECT "{natural_col}", "{key_col}" FROM {SCHEMA}."{table}"')
    ).all()
    return {str(r[0]): int(r[1]) for r in rows}


def _upsert_header(conn, table: str, key_col: str, row: Dict[str, Any], cols: List[str]) -> None:
    col_list = ", ".join(f'"{c}"' for c in [key_col] + cols)
    placeholders = ", ".join(f":{c}" for c in [key_col] + cols)
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols)
    conn.execute(
        text(
            f'INSERT INTO {SCHEMA}."{table}" ({col_list}) VALUES ({placeholders}) '
            f'ON CONFLICT ("{key_col}") DO UPDATE SET {updates}'
        ),
        row,
    )


def seed(
    *,
    so_xlsx: str = DEFAULT_SO_XLSX,
    po_xlsx: str = DEFAULT_PO_XLSX,
    open_po: int = 0,
    spo: int = 0,
) -> Dict[str, int]:
    so_headers, so_lines = build_so_rows(_read_xlsx_rows(so_xlsx))
    po_headers, po_lines = build_po_rows(_read_xlsx_rows(po_xlsx))

    po_lines_sorted = sorted(po_lines, key=lambda r: (r["doc_no"], r["item_code"]))
    po_lines_sorted = mark_po_rows_open(po_lines_sorted, open_po)
    po_headers, po_lines_sorted = clone_spo_docs(po_headers, po_lines_sorted, spo)

    debtors = derive_debtors(so_headers)
    creditors = derive_creditors(po_headers)
    items = derive_items(so_lines, po_lines_sorted)
    locations = derive_locations(so_lines, po_lines_sorted)
    agents = derive_sales_agents(so_headers, po_headers)

    counts: Dict[str, int] = {}
    with engine.begin() as conn:
        for statement in DDL.strip().split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))

        # Rig defect fix (coordinator finding): read back whatever the
        # target already has BEFORE minting any keys, so a re-seed with a
        # different derived set (SO+PO books, --open-po/--spo flags) never
        # renumbers a code/doc that's already there - a real AutoCount key
        # never moves. SODTL/PODTL keep their pre-existing from-scratch
        # numbering (their natural key already embeds a per-run line
        # position, a separate concern from this fix - never referenced as
        # a cross-run "ref" the way Item/Debtor/Creditor/SO/PO ids are).
        so_doc_keys = assign_keys(
            so_headers.keys(), existing=_read_existing_keys(conn, "SO", "DocKey", "DocNo")
        )
        po_doc_keys = assign_keys(
            po_headers.keys(), existing=_read_existing_keys(conn, "PO", "DocKey", "DocNo")
        )
        so_dtl_keys = assign_keys(
            f"{r['doc_no']}::{r['item_code']}::{i}" for i, r in enumerate(so_lines)
        )
        po_dtl_keys = assign_keys(
            f"{r['doc_no']}::{r['item_code']}::{i}" for i, r in enumerate(po_lines_sorted)
        )
        debtor_keys = assign_keys(
            (d["acc_no"] for d in debtors),
            existing=_read_existing_keys(conn, "Debtor", "AutoKey", "AccNo"),
        )
        creditor_keys = assign_keys(
            (c["acc_no"] for c in creditors),
            existing=_read_existing_keys(conn, "Creditor", "AutoKey", "AccNo"),
        )
        item_keys = assign_keys(
            (i["item_code"] for i in items),
            existing=_read_existing_keys(conn, "Item", "AutoKey", "ItemCode"),
        )
        location_keys = assign_keys(
            (l["location"] for l in locations),
            existing=_read_existing_keys(conn, "Location", "AutoKey", "Location"),
        )

        for doc_no, header in so_headers.items():
            _upsert_header(
                conn,
                "SO",
                "DocKey",
                {
                    "DocKey": so_doc_keys[doc_no],
                    "DocNo": doc_no,
                    "DocDate": header["doc_date"],
                    "DebtorCode": header["debtor_code"],
                    "DebtorName": header["debtor_name"],
                    "SalesAgent": header["sales_agent"],
                    "Note": header["note"],
                },
                ["DocNo", "DocDate", "DebtorCode", "DebtorName", "SalesAgent", "Note"],
            )
        for i, row in enumerate(so_lines):
            key = f"{row['doc_no']}::{row['item_code']}::{i}"
            _upsert_header(
                conn,
                "SODTL",
                "DtlKey",
                {
                    "DtlKey": so_dtl_keys[key],
                    "DocKey": so_doc_keys[row["doc_no"]],
                    "Seq": i,
                    "ItemCode": row["item_code"],
                    "Location": row["location"],
                    "Description": row["description"],
                    "Qty": row["qty"],
                    "TransferedQty": row["transfered_qty"],
                    "UnitPrice": row["unit_price"],
                    "DiscountAmt": row["discount_amt"],
                    "SubTotal": row["sub_total"],
                    "DeliveryDate": row["delivery_date"],
                },
                [
                    "DocKey",
                    "Seq",
                    "ItemCode",
                    "Location",
                    "Description",
                    "Qty",
                    "TransferedQty",
                    "UnitPrice",
                    "DiscountAmt",
                    "SubTotal",
                    "DeliveryDate",
                ],
            )

        for doc_no, header in po_headers.items():
            _upsert_header(
                conn,
                "PO",
                "DocKey",
                {
                    "DocKey": po_doc_keys[doc_no],
                    "DocNo": doc_no,
                    "DocDate": header["doc_date"],
                    "CreditorCode": header["creditor_code"],
                    "CreditorName": header["creditor_name"],
                    "PurchaseAgent": header["purchase_agent"],
                },
                ["DocNo", "DocDate", "CreditorCode", "CreditorName", "PurchaseAgent"],
            )
        for i, row in enumerate(po_lines_sorted):
            key = f"{row['doc_no']}::{row['item_code']}::{i}"
            _upsert_header(
                conn,
                "PODTL",
                "DtlKey",
                {
                    "DtlKey": po_dtl_keys[key],
                    "DocKey": po_doc_keys[row["doc_no"]],
                    "Seq": i,
                    "ItemCode": row["item_code"],
                    "Location": row["location"],
                    "Description": row["description"],
                    "Qty": row["qty"],
                    "TransferedQty": row["transfered_qty"],
                    "UnitPrice": row["unit_price"],
                    "DiscountAmt": row["discount_amt"],
                    "SubTotal": row["sub_total"],
                    "DeliveryDate": row["delivery_date"],
                    "FromSODocList": row.get("from_so_doc_list"),
                },
                [
                    "DocKey",
                    "Seq",
                    "ItemCode",
                    "Location",
                    "Description",
                    "Qty",
                    "TransferedQty",
                    "UnitPrice",
                    "DiscountAmt",
                    "SubTotal",
                    "DeliveryDate",
                    "FromSODocList",
                ],
            )

        for d in debtors:
            _upsert_header(
                conn,
                "Debtor",
                "AutoKey",
                {
                    "AutoKey": debtor_keys[d["acc_no"]],
                    "AccNo": d["acc_no"],
                    "CompanyName": d["company_name"],
                    "SalesAgent": d["sales_agent"],
                },
                ["AccNo", "CompanyName", "SalesAgent"],
            )
        for c in creditors:
            _upsert_header(
                conn,
                "Creditor",
                "AutoKey",
                {
                    "AutoKey": creditor_keys[c["acc_no"]],
                    "AccNo": c["acc_no"],
                    "CompanyName": c["company_name"],
                    "PurchaseAgent": c["purchase_agent"],
                },
                ["AccNo", "CompanyName", "PurchaseAgent"],
            )
        for it in items:
            _upsert_header(
                conn,
                "Item",
                "AutoKey",
                {
                    "AutoKey": item_keys[it["item_code"]],
                    "ItemCode": it["item_code"],
                    "Description": it["description"],
                },
                ["ItemCode", "Description"],
            )
            conn.execute(
                text(
                    f'INSERT INTO {SCHEMA}."ItemUOM" ("AutoKey", "ItemCode", "UOM") '
                    f'VALUES (:auto_key, :item_code, :uom) '
                    f'ON CONFLICT ("AutoKey") DO UPDATE SET "ItemCode" = EXCLUDED."ItemCode"'
                ),
                {"auto_key": item_keys[it["item_code"]], "item_code": it["item_code"], "uom": "UNIT"},
            )
        for loc in locations:
            _upsert_header(
                conn,
                "Location",
                "AutoKey",
                {"AutoKey": location_keys[loc["location"]], "Location": loc["location"]},
                ["Location"],
            )
        for agent in agents:
            conn.execute(
                text(
                    f'INSERT INTO {SCHEMA}."SalesAgent" ("Agent") VALUES (:agent) '
                    f'ON CONFLICT ("Agent") DO NOTHING'
                ),
                {"agent": agent["agent"]},
            )

        for table in ("SO", "SODTL", "PO", "PODTL", "Debtor", "Creditor", "Item", "ItemUOM", "Location", "SalesAgent"):
            counts[table] = conn.execute(text(f'SELECT count(*) FROM {SCHEMA}."{table}"')).scalar_one()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--so-xlsx", default=DEFAULT_SO_XLSX, help="path to the SO oracle xlsx")
    parser.add_argument("--po-xlsx", default=DEFAULT_PO_XLSX, help="path to the PO/SPO oracle xlsx")
    parser.add_argument(
        "--open-po",
        type=int,
        default=0,
        metavar="N",
        help="deterministically force N settled PO lines open (Remaining > 0)",
    )
    parser.add_argument(
        "--spo",
        type=int,
        default=0,
        metavar="N",
        help="deterministically clone N PO docs as SPO- prefixed docs",
    )
    args = parser.parse_args()
    _guard()

    for path in (args.so_xlsx, args.po_xlsx):
        if not Path(path).exists():
            raise SystemExit(f"xlsx not found: {path}")

    counts = seed(so_xlsx=args.so_xlsx, po_xlsx=args.po_xlsx, open_po=args.open_po, spo=args.spo)
    for table, n in counts.items():
        print(f'{SCHEMA}."{table}": {n} row(s) ready.')
    print(
        f"Point a `sql_database` connection at this Postgres "
        f"(database '{settings.database_url.split('/')[-1]}') and query "
        f'`SELECT * FROM {SCHEMA}."SO"` etc - schema `{SCHEMA}` mirrors the '
        "AutoCount SQL pack's table/column shape (documentation/plans/"
        "sprint-4/22-autocount-db-etl-autocount-sql.md)."
    )


if __name__ == "__main__":
    main()
