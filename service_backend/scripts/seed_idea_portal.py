"""Seed the idea portal (lane IDEA-PORTAL) with realistic demo data for a hand test.

  python -m scripts.seed_idea_portal [--tenant-slug default] [--product "Sorento CRM"]

What it writes, for ONE tenant (idempotent - re-running adds nothing; every
seeded idea carries ``intake_ref = "portal-seed:<key>"``):

- the two real ideas the owner named: IDEA-0010 "Order status tracking for
  dealers" (New, 0 votes) and IDEA-0014 "Quotation knowledge capture" (New).
  If either idea number already exists in the database it is left alone.
- ``[sample]`` sanitaryware/dealer ideas in EVERY roadmap status (Triaged,
  Linked to BR, Building, Delivered, Closed) plus one Rejected (off-ramp, only
  under the Closed filter);
- upvotes (named Sorento staff + one WhatsApp-style dealer vote), comments with
  a reply and a like, status-change activity rows;
- one idea hidden from the portal, one delivered idea with a changelog note.

Requires the ideation module ACTIVE for the tenant (Services > Ideation >
Install) - refuses otherwise, so a hand test never runs on a half-set-up tenant.
Never run against production data: everything it writes is demo content.
"""
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

SEED_PREFIX = "portal-seed:"

# key, idea_number (None = mint), title, business problem, status key, votes,
# extra fields
_IDEAS = [
    ("idea-0010", "IDEA-0010", "Order status tracking for dealers",
     "Dealers cannot track the status after they place an order.", "captured", 0,
     {"raw_text": "dealer want to have a function to track the status after they place order",
      "source": "whatsapp", "submitter_name": "Aiman"}),
    ("idea-0014", "IDEA-0014", "Quotation knowledge capture",
     "Quotation know-how sits with a few salespeople and is lost when they leave.", "captured", 0,
     {"source": "whatsapp"}),
    ("price-list", None, "[sample] Dealer price list for basins and WCs in the chatbot",
     "Dealers ask the sales desk for the latest price of basins and WCs several times a day.",
     "triaged", 5, {"desired_outcome": "The chatbot replies with the current dealer price.",
                    "use_cases": "Dealer quoting a walk-in customer\nDealer preparing a project tender"}),
    ("warehouse-stock", None, "[sample] Show stock by warehouse for shower sets",
     "Sales cannot see which warehouse holds a shower set before promising delivery.",
     "linked", 3, {"current_workaround": "Call each warehouse and ask."}),
    ("reorder", None, "[sample] Reorder last month's order in one tap",
     "Dealers retype the same monthly order by hand.", "building", 2, {}),
    ("spec-sheet", None, "[sample] Download product spec sheet (PDF) from the catalogue",
     "Spec sheets are emailed one by one on request.", "delivered", 4,
     {"portal_note": "[sample] Every catalogue item now has a Spec sheet button."}),
    ("colour-swatch", None, "[sample] Colour swatches for vanity cabinets",
     "Dealers cannot show cabinet colours without the physical sample book.", "closed", 1, {}),
    ("margin-report", None, "[sample] Internal margin report per dealer",
     "Management wants margin per dealer - internal pricing detail.", "triaged", 1,
     {"portal_hidden": True}),
    ("free-delivery", None, "[sample] Free delivery for every order",
     "Dealers ask for free delivery on small orders.", "rejected", 0, {}),
]
_VOTERS = ["Hafiz", "Wei Ling", "Nadia", "Ravi", "Siti"]
_MOVES = {
    "triaged": [("New", "Triaged")],
    "linked": [("New", "Triaged"), ("Triaged", "Linked to BR")],
    "building": [("New", "Triaged"), ("Triaged", "Linked to BR"), ("Linked to BR", "Building")],
    "delivered": [("New", "Triaged"), ("Triaged", "Linked to BR"), ("Linked to BR", "Building"),
                  ("Building", "Delivered")],
    "closed": [("New", "Triaged"), ("Triaged", "Delivered"), ("Delivered", "Closed")],
    "rejected": [("New", "Rejected")],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _product(db: Session, tenant_id: str, name: str):
    from app.models.catalog import Product

    p = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_id, Product.name == name, Product.is_deleted.is_(False))
        .first()
    )
    if p is None:
        p = Product(tenant_id=tenant_id, name=name, kind="software")
        db.add(p)
        db.flush()
    return p


def seed_idea_portal(db: Session, tenant_id: str, product_name: str = "Sorento CRM") -> Dict[str, int]:
    """Idempotent. Returns ``{"created": n, "skipped": m}``."""
    from app.repositories.module_repository import ModuleRepository
    from modules.ideation.models import Idea, IdeaActivity, IdeaComment, IdeaCommentLike, IdeaVote
    from modules.ideation.services.numbering import mint_idea_identity
    from modules.ideation.services.statuses import idea_status_id

    if not ModuleRepository(db).is_active(tenant_id, "ideation"):
        raise SystemExit("Ideation is not active for this tenant - install it first (Services > Ideation).")

    product = _product(db, tenant_id, product_name)
    created = skipped = 0
    base = _now() - timedelta(days=12)
    for n, (key, number, title, problem, status_key, votes, extra) in enumerate(_IDEAS):
        ref = SEED_PREFIX + key
        exists = db.query(Idea.id).filter(Idea.tenant_id == tenant_id, Idea.intake_ref == ref).first()
        if exists or (number and db.query(Idea.id).filter(Idea.idea_number == number).first()):
            skipped += 1
            continue
        status_id = idea_status_id(db, status_key, tenant_id)
        if status_id is None:
            raise SystemExit(f"Status {status_key!r} not found for this tenant.")
        captured = {"problem": problem}
        for f in ("desired_outcome", "use_cases", "current_workaround"):
            if extra.get(f):
                captured[f] = extra[f]
        created_at = base + timedelta(days=n)
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product.id,
            status_id=status_id,
            title=title,
            problem=problem,
            raw_text=extra.get("raw_text", ""),
            source=extra.get("source", "manual"),
            submitter_name=extra.get("submitter_name"),
            intake_ref=ref,
            idea_number=number,
            captured_json=captured,
            portal_hidden=bool(extra.get("portal_hidden")),
            portal_note=extra.get("portal_note"),
            upvotes=votes,
            created_at=created_at,
        )
        for f in ("desired_outcome", "use_cases", "current_workaround"):
            if extra.get(f) and hasattr(Idea, f):
                setattr(idea, f, extra[f])
        db.add(idea)
        db.flush()
        mint_idea_identity(db, idea)
        for i in range(votes):
            # The last vote of a popular idea is a WhatsApp dealer (bare id).
            dealer = votes >= 3 and i == votes - 1
            db.add(IdeaVote(
                tenant_id=tenant_id, idea_id=idea.id,
                voter_id=f"seed-dealer-{key}" if dealer else f"embed-user:seed-{_VOTERS[i % 5].lower().replace(' ', '-')}",
                dir="up",
                voter_name=None if dealer else _VOTERS[i % 5],
                voter_role=None if dealer else "Staff",
                created_at=created_at + timedelta(hours=2 + i),
            ))
        for j, (frm, to) in enumerate(_MOVES.get(status_key, [])):
            db.add(IdeaActivity(
                tenant_id=tenant_id, idea_id=idea.id, kind="status_changed",
                from_label=frm, to_label=to, created_at=created_at + timedelta(days=1 + j),
            ))
        if votes >= 3:
            top = IdeaComment(
                tenant_id=tenant_id, idea_id=idea.id, author_kind="embed",
                author_id="embed-user:seed-nadia", author_name="Nadia",
                body="[sample] We can pull this from the ERP. Which dealers need it first?",
                created_at=created_at + timedelta(days=1, hours=3),
            )
            db.add(top)
            db.flush()
            db.add(IdeaComment(
                tenant_id=tenant_id, idea_id=idea.id, parent_id=top.id, author_kind="embed",
                author_id="embed-user:seed-hafiz", author_name="Hafiz",
                body="[sample] The Johor and Penang dealers ask every week.",
                created_at=created_at + timedelta(days=1, hours=5),
            ))
            db.add(IdeaCommentLike(
                tenant_id=tenant_id, idea_id=idea.id, comment_id=top.id,
                liker_id="embed-user:seed-wei-ling", liker_name="Wei Ling",
                created_at=created_at + timedelta(days=1, hours=6),
            ))
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}


def _tenant_id(db: Session, slug: str) -> str:
    from app.models.tenant import Tenant

    t = db.query(Tenant).filter(Tenant.slug == slug).first()
    if t is None:
        raise SystemExit(f"No tenant with slug {slug!r}.")
    return t.id


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for the idea portal.")
    parser.add_argument("--tenant-slug", default="default")
    parser.add_argument("--product", default="Sorento CRM")
    args = parser.parse_args(argv)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        out = seed_idea_portal(db, _tenant_id(db, args.tenant_slug), args.product)
        print(f"idea portal seed: created {out['created']}, skipped {out['skipped']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
