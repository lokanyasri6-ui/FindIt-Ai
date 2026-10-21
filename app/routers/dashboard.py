from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..deps import get_current_user, get_db
from ..models import Claim, Item, Match, User
from ..schemas import ActivityOut, DashboardOut, GlobalStats, MyStats
from ..serializers import item_out

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _count(db: Session, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(Item).where(*conditions)) or 0


def _by_status(rows) -> dict[str, int]:
    counts = {"pending": 0, "approved": 0, "rejected": 0, "withdrawn": 0}
    for status, n in rows:
        counts[status] = n
    return counts


@router.get("", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Live numbers for the dashboard page (the frontend can label them however it likes)."""
    stats = GlobalStats(
        total_items=_count(db),
        lost_items=_count(db, Item.type == "lost"),
        found_items=_count(db, Item.type == "found"),
        potential_matches=db.scalar(select(func.count()).select_from(Match).where(Match.status == "suggested")) or 0,
        reunited_items=_count(db, Item.status == "returned"),
    )

    my_items = db.scalars(
        select(Item).where(Item.user_id == user.id).order_by(Item.created_at.desc(), Item.id.desc())
    ).all()
    my_ids = [i.id for i in my_items]

    my_matches = []
    if my_ids:
        my_matches = list(
            db.scalars(
                select(Match)
                .options(joinedload(Match.lost_item), joinedload(Match.found_item))
                .where(or_(Match.lost_item_id.in_(my_ids), Match.found_item_id.in_(my_ids)), Match.status == "suggested")
                .order_by(Match.created_at.desc())
            ).unique()
        )

    made = db.execute(
        select(Claim.status, func.count()).where(Claim.claimant_id == user.id).group_by(Claim.status)
    ).all()
    received = (
        db.execute(select(Claim.status, func.count()).where(Claim.item_id.in_(my_ids)).group_by(Claim.status)).all()
        if my_ids
        else []
    )

    mine = MyStats(
        reports=len(my_items),
        lost_reports=sum(1 for i in my_items if i.type == "lost"),
        found_reports=sum(1 for i in my_items if i.type == "found"),
        potential_matches=len(my_matches),
        claims_made=_by_status(made),
        claims_received=_by_status(received),
    )

    activity: list[ActivityOut] = [
        ActivityOut(kind="report", message=f"You reported a {i.type} item: {i.title}", at=i.created_at, item_id=i.id)
        for i in my_items
    ]
    for m in my_matches:
        mine_item = m.lost_item if m.lost_item.user_id == user.id else m.found_item
        activity.append(
            ActivityOut(
                kind="match",
                message=f"New possible match ({m.final_score:.0f}%) for your report: {mine_item.title}",
                at=m.created_at,
                item_id=mine_item.id,
            )
        )
    claims = db.scalars(
        select(Claim)
        .options(joinedload(Claim.item), joinedload(Claim.claimant))
        .where(or_(Claim.claimant_id == user.id, Claim.item_id.in_(my_ids or [-1])))
    ).unique()
    for c in claims:
        if c.claimant_id == user.id:
            activity.append(
                ActivityOut(
                    kind="claim_made",
                    message=f"Your claim request on '{c.item.title}' is {c.status}",
                    at=c.updated_at,
                    item_id=c.item_id,
                )
            )
        else:
            first = (c.claimant.name.split() or ["Someone"])[0]
            activity.append(
                ActivityOut(
                    kind="claim_received",
                    message=f"{first} sent a claim request for '{c.item.title}' ({c.status})",
                    at=c.updated_at,
                    item_id=c.item_id,
                )
            )
    activity.sort(key=lambda a: a.at, reverse=True)

    return DashboardOut(
        stats=stats,
        mine=mine,
        my_reports=[item_out(i, user) for i in my_items],
        recent_activity=activity[:15],
    )
