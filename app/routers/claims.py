from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..constants import OPEN_STATUSES
from ..deps import get_current_user, get_db
from ..models import Claim, Item, User, utcnow
from ..schemas import ClaimCreate, ClaimOut, ClaimStatusUpdate
from ..serializers import claim_out

router = APIRouter(prefix="/claims", tags=["claims"])

_LOAD = (joinedload(Claim.item), joinedload(Claim.claimant), joinedload(Claim.lost_item))


@router.post("", response_model=ClaimOut, status_code=201)
def create_claim(body: ClaimCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Ask the owner of a report to hand an item over (or confirm they found it).

    Claims are *requests*, not proof of ownership: the report owner reviews the optional
    verification detail and decides. Contact details are never exchanged through this API.
    """
    item = db.get(Item, body.item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    if item.user_id == user.id:
        raise HTTPException(400, "You can't claim your own report")
    if item.status not in OPEN_STATUSES:
        raise HTTPException(409, "This item is no longer open for claims")

    if body.lost_item_id is not None:
        mine = db.get(Item, body.lost_item_id)
        if mine is None or mine.user_id != user.id:
            raise HTTPException(400, "lost_item_id must be one of your own reports")
        if mine.type == item.type:
            raise HTTPException(400, "Your report must be the opposite type (lost vs found) of the item you're claiming")

    duplicate = db.scalar(
        select(Claim).where(Claim.claimant_id == user.id, Claim.item_id == item.id, Claim.status == "pending")
    )
    if duplicate:
        raise HTTPException(409, "You already have a pending claim request for this item")

    claim = Claim(
        claimant_id=user.id,
        item_id=item.id,
        lost_item_id=body.lost_item_id,
        message=body.message.strip(),
        verification_detail=(body.verification_detail or "").strip() or None,
    )
    item.status = "claim_pending"
    db.add(claim)
    db.commit()
    claim.claimant, claim.item = user, item
    claim.lost_item = db.get(Item, body.lost_item_id) if body.lost_item_id else None
    return claim_out(claim, "made")


@router.get("/mine", response_model=list[ClaimOut])
def claims_made(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Claim).options(*_LOAD).where(Claim.claimant_id == user.id).order_by(Claim.updated_at.desc())
    ).unique()
    return [claim_out(c, "made") for c in rows]


@router.get("/received", response_model=list[ClaimOut])
def claims_received(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    my_ids = select(Item.id).where(Item.user_id == user.id)
    rows = db.scalars(
        select(Claim).options(*_LOAD).where(Claim.item_id.in_(my_ids)).order_by(Claim.updated_at.desc())
    ).unique()
    return [claim_out(c, "received") for c in rows]


@router.patch("/{claim_id}", response_model=ClaimOut)
def update_claim(
    claim_id: int,
    body: ClaimStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = db.scalar(select(Claim).options(*_LOAD).where(Claim.id == claim_id))
    if claim is None:
        raise HTTPException(404, "Claim not found")
    item = claim.item
    if claim.status != "pending":
        raise HTTPException(409, f"This claim is already {claim.status}")

    if body.status == "withdrawn":
        if claim.claimant_id != user.id:
            raise HTTPException(403, "Only the person who made the claim can withdraw it")
        direction = "made"
    else:
        if item.user_id != user.id:
            raise HTTPException(403, "Only the owner of the report can approve or reject claims")
        direction = "received"

    now = utcnow()
    claim.status = body.status
    claim.updated_at = now

    if body.status == "approved":
        item.status = "returned"
        if claim.lost_item is not None:
            claim.lost_item.status = "returned"
        for other in db.scalars(
            select(Claim).where(Claim.item_id == item.id, Claim.status == "pending", Claim.id != claim.id)
        ):
            other.status, other.updated_at = "rejected", now
    elif item.status == "claim_pending":
        still_pending = db.scalar(
            select(Claim.id).where(Claim.item_id == item.id, Claim.status == "pending", Claim.id != claim.id)
        )
        if still_pending is None:
            item.status = "open"

    db.commit()
    return claim_out(claim, direction)
