"""Print a dealer's personal feedback board link for one item (lane PUBLIC-IDEAS-BOARD).

  python -m scripts.feedback_link IDEA-0016 [--tenant-slug default]

Looks the item up by number in that tenant, takes its submitter contact and
prints ``{board base}/{link token}/{item number}`` - the same link the WhatsApp
reply and ``board_url`` carry (``services.feedback_links.mint_board_link``; the
contact's live link is minted on first use). Prints nothing useful for an item
with no submitter contact or a test item, and says so. For hand tests and
support: the link is a bearer credential, share it only with that contact.
"""
import argparse
import sys

from app.database import SessionLocal
from app.models.tenant import Tenant
from modules.ideation.models import Idea
from modules.ideation.services.feedback_links import mint_board_link


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("item_number")
    parser.add_argument("--tenant-slug", default="default")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == args.tenant_slug).first()
        if tenant is None:
            print(f"No tenant {args.tenant_slug!r}.", file=sys.stderr)
            return 1
        idea = (
            db.query(Idea)
            .filter(Idea.tenant_id == tenant.id, Idea.idea_number == args.item_number)
            .first()
        )
        if idea is None:
            print(f"Couldn't find {args.item_number} in {args.tenant_slug}.", file=sys.stderr)
            return 1
        link = mint_board_link(db, idea)
        if link is None:
            print(f"{args.item_number} has no submitter contact (or is a test item): no link.", file=sys.stderr)
            return 1
        db.commit()
        print(link)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
