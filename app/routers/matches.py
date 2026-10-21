from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..deps import get_current_user, get_current_user_optional, get_db
from ..models import Item, ItemEmbedding, Match, User
from ..schemas import MatchListOut, MatchOut, ScoringInfo
from ..serializers import item_brief, match_out
from ..services.embeddings import get_embedder
from ..services.matching import find_matches, load_matches

router = APIRouter(tags=["matches"])


def _scoring_info() -> ScoringInfo:
    embedder = get_embedder()
    total = settings.image_weight + settings.text_weight
    wi, wt = settings.image_weight / total, settings.text_weight / total
    return ScoringInfo(
        image_weight=round(wi, 3),
        text_weight=round(wt, 3),
        embedding_backend=embedder.name,
        is_simulated=embedder.is_simulated,
        formula=f"overall = {wi:.0%} image similarity + {wt:.0%} description similarity",
    )


@router.get("/items/{item_id}/matches", response_model=MatchListOut)
def item_matches(
    item_id: int,
    refresh: bool = Query(False, description="Owner only: recompute matches now"),
    min_score: Optional[float] = Query(None, ge=0, le=100),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Possible matches for a report (lost -> found candidates, found -> lost candidates)."""
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Item not found")

    # Embeddings are generated in the background after upload; tell the client to poll briefly.
    if db.get(ItemEmbedding, item.id) is None:
        return MatchListOut(item=item_brief(item), indexing=True, scoring=_scoring_info(), matches=[])

    is_owner = user is not None and user.id == item.user_id
    rows = load_matches(db, item)
    if (refresh and is_owner) or not rows:
        find_matches(db, item)
        rows = load_matches(db, item)

    if min_score is not None:
        rows = [m for m in rows if m.final_score >= min_score]
    return MatchListOut(
        item=item_brief(item),
        indexing=False,
        scoring=_scoring_info(),
        matches=[match_out(m, user, relative_to=item) for m in rows[:limit]],
    )


@router.get("/matches/mine", response_model=list[MatchOut])
def my_matches(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    my_ids = select(Item.id).where(Item.user_id == user.id)
    rows = db.scalars(
        select(Match)
        .options(joinedload(Match.lost_item), joinedload(Match.found_item))
        .where(or_(Match.lost_item_id.in_(my_ids), Match.found_item_id.in_(my_ids)), Match.status != "dismissed")
        .order_by(Match.final_score.desc())
    ).unique()
    return [match_out(m, user) for m in rows]


@router.post("/matches/{match_id}/dismiss", response_model=MatchOut)
def dismiss_match(match_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "Match not found")
    if user.id not in (match.lost_item.user_id, match.found_item.user_id):
        raise HTTPException(403, "This match isn't about one of your reports")
    match.status = "dismissed"
    db.commit()
    return match_out(match, user)
