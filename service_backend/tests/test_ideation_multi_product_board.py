"""SS-MULTI-PRODUCT-BOARD - one feedback board, served per product. RED first.

Contract: ``documentation/plans/ideation/multi-product-board-acceptance-criteria.md``
(AC-MPB-xx ids below). A personal board link belongs to the product of the item
it was minted for; that board shows only that product and carries the
product's board colour + name.
"""
from tests.test_ideation_feedback_link import _contact, _exchange  # noqa: F401
from tests.test_ideation_portal import _idea  # noqa: F401
from tests.test_ideation_public_status import (  # noqa: F401
    _auth,
    _create_software_product,
    ideation_client,
    setup,
)


def _mint(s, idea_id) -> str:
    """Mint the board link the way production does (from an item) and return
    the link token."""
    from modules.ideation.models import Idea
    from modules.ideation.services.feedback_links import mint_board_link

    db = s["factory"]()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        url = mint_board_link(db, idea)
        db.commit()
        assert url
        return url.split("/board/", 1)[1].split("/", 1)[0]
    finally:
        db.close()


def _session(s, token) -> dict:
    res = _exchange(s, token)
    assert res.status_code == 200, res.text
    return res.json()


def _h(session) -> dict:
    return {"Authorization": f"Bearer {session['token']}"}


def _board(s, h, product_id, **body):
    return s["client"].put(f"/ideation/products/{product_id}/delivery", headers=h, json=body)


def _two_products(s):
    """Sorento (setup's product) + a second product, one item each by the same
    contact."""
    other = _create_software_product(s["client"], s["h"], name="EcoHub")
    cid = _contact(s)
    a = _idea(s, 1, submitter_contact_id=cid)
    b = _idea(s, 2, submitter_contact_id=cid)
    from modules.ideation.models import Idea

    db = s["factory"]()
    try:
        db.query(Idea).filter(Idea.id == b).first().product_id = other
        db.commit()
    finally:
        db.close()
    return cid, a, b, other


# ── AC-MPB-1: a link belongs to one product ───────────────────────────────────


def test_ac_mpb_01_link_per_product(setup):
    cid, a, b, other = _two_products(setup)
    ta = _mint(setup, a)
    tb = _mint(setup, b)
    assert ta != tb
    assert _mint(setup, a) == ta  # stable per product
    from modules.ideation.models import IdeaContactLink

    db = setup["factory"]()
    try:
        rows = {r.token: r.product_id for r in db.query(IdeaContactLink).filter_by(contact_id=cid)}
    finally:
        db.close()
    assert rows == {ta: setup["product_id"], tb: other}


# ── AC-MPB-2: the board shows only that product ───────────────────────────────


def test_ac_mpb_02_board_scoped_to_link_product(setup):
    cid, a, b, other = _two_products(setup)
    sa = _session(setup, _mint(setup, a))
    assert sa["principal"]["productId"] == setup["product_id"]
    h = _h(sa)
    c = setup["client"]
    ids = {i["id"] for i in c.get("/portal/ideas", headers=h).json()["items"]}
    assert ids == {a}
    assert c.get(f"/portal/ideas/{b}", headers=h).status_code == 404
    me = c.get("/portal/ideas/me", headers=h).json()
    assert me["productId"] == setup["product_id"]

    sb = _session(setup, _mint(setup, b))
    ids_b = {i["id"] for i in c.get("/portal/ideas", headers=_h(sb)).json()["items"]}
    assert ids_b == {b}


def test_ac_mpb_02_unscoped_old_link_unchanged(setup):
    """A link with no product (minted before this lane) still sees every product."""
    from tests.test_ideation_feedback_link import _link

    cid, a, b, other = _two_products(setup)
    s = _session(setup, _link(setup, cid))
    assert s["principal"]["productId"] is None
    assert s["principal"]["brand"] is None
    ids = {i["id"] for i in setup["client"].get("/portal/ideas", headers=_h(s)).json()["items"]}
    assert ids == {a, b}


# ── AC-MPB-3/4: product board colour + name ───────────────────────────────────


def test_ac_mpb_03_brand_from_product(setup):
    cid, a, b, other = _two_products(setup)
    res = _board(setup, setup["h"], setup["product_id"], boardColor="#3B82F6", boardName="Sorento CRM")
    assert res.status_code == 200, res.text
    assert res.json()["boardColor"] == "#3b82f6"
    assert res.json()["boardName"] == "Sorento CRM"
    # The domain base set by the fixture is untouched by a board-only PUT.
    assert res.json()["productDomainBase"] == "https://fe-sorento.foundryx.my"

    sa = _session(setup, _mint(setup, a))
    assert sa["principal"]["brand"] == {"name": "Sorento CRM", "color": "#3b82f6"}
    me = setup["client"].get("/portal/ideas/me", headers=_h(sa)).json()
    assert me["brand"] == {"name": "Sorento CRM", "color": "#3b82f6"}
    # The other product has no board settings: SS default.
    sb = _session(setup, _mint(setup, b))
    assert sb["principal"]["brand"] is None


def test_ac_mpb_04_board_color_validated_and_clearable(setup):
    pid = setup["product_id"]
    bad = _board(setup, setup["h"], pid, boardColor="blue")
    assert bad.status_code == 422
    assert _board(setup, setup["h"], pid, boardColor="#16a34a", boardName="X").status_code == 200
    cleared = _board(setup, setup["h"], pid, boardColor=None, boardName=None)
    assert cleared.status_code == 200
    assert cleared.json()["boardColor"] is None
    assert cleared.json()["boardName"] is None
    got = setup["client"].get(f"/ideation/products/{pid}/delivery", headers=setup["h"]).json()
    assert got["boardColor"] is None


def test_ac_mpb_04_brand_name_only(setup):
    cid, a, b, other = _two_products(setup)
    assert _board(setup, setup["h"], setup["product_id"], boardName="Sorento CRM").status_code == 200
    sa = _session(setup, _mint(setup, a))
    assert sa["principal"]["brand"] == {"name": "Sorento CRM", "color": None}


# ── AC-MPB-5: backfill for links already sent ─────────────────────────────────


def test_ac_mpb_05_backfill_single_product_contacts_only(setup):
    from modules.ideation.models import IdeaContactLink
    from modules.ideation.services.feedback_links import backfill_link_products
    from tests.test_ideation_feedback_link import _link

    cid, a, b, other = _two_products(setup)  # two products -> stays unscoped
    solo = _contact(setup, phone="+60123459999")
    _idea(setup, 3, submitter_contact_id=solo)
    t_two = _link(setup, cid)
    t_solo = _link(setup, solo)

    db = setup["factory"]()
    try:
        assert backfill_link_products(db) == 1
        db.commit()
        got = {r.token: r.product_id for r in db.query(IdeaContactLink)}
        assert backfill_link_products(db) == 0  # idempotent
    finally:
        db.close()
    assert got[t_two] is None
    assert got[t_solo] == setup["product_id"]
    s = _session(setup, t_solo)
    assert s["principal"]["productId"] == setup["product_id"]


def test_ac_mpb_tenant_isolation_of_brand(setup):
    """The brand is read with the link's own tenant: another tenant's product
    delivery row with the same product id can never colour this board."""
    cid, a, b, other = _two_products(setup)
    from modules.ideation.models import ProductDelivery

    db = setup["factory"]()
    try:
        db.add(ProductDelivery(tenant_id="someone-else", product_id=other, board_color="#000000"))
        db.commit()
    finally:
        db.close()
    sb = _session(setup, _mint(setup, b))
    assert sb["principal"]["brand"] is None
