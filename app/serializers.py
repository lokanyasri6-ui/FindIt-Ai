from typing import Optional

from .config import settings
from .models import Claim, Item, Match, User
from .schemas import ClaimOut, ItemBrief, ItemOut, MatchOut


def absolute_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{settings.public_base_url.rstrip('/')}{url}"


def item_brief(item: Item) -> ItemBrief:
    return ItemBrief(
        id=item.id,
        type=item.type,
        title=item.title,
        category=item.category,
        image_url=absolute_url(item.image_url),
        status=item.status,
    )


def item_out(item: Item, user: Optional[User] = None) -> ItemOut:
    """Public view of a report. Never includes the owner's identity or contact details;
    `private_detail` is only revealed to the owner."""
    mine = user is not None and item.user_id == user.id
    return ItemOut(
        **item_brief(item).model_dump(),
        description=item.description,
        location_text=item.location_text,
        lat=item.lat,
        lng=item.lng,
        date_event=item.date_event,
        distinguishing_features=item.distinguishing_features,
        private_detail=item.private_detail if mine else None,
        created_at=item.created_at,
        is_mine=mine,
    )


def match_out(match: Match, user: Optional[User] = None, relative_to: Optional[Item] = None) -> MatchOut:
    other = None
    if relative_to is not None:
        other_item = match.found_item if relative_to.id == match.lost_item_id else match.lost_item
        other = item_out(other_item, user)
    return MatchOut(
        id=match.id,
        final_score=match.final_score,
        image_score=match.image_score,
        text_score=match.text_score,
        location_score=match.location_score,
        location_label=match.location_label,
        days_apart=match.days_apart,
        explanation=match.explanation,
        status=match.status,
        created_at=match.created_at,
        lost_item=item_out(match.lost_item, user),
        found_item=item_out(match.found_item, user),
        other_item=other,
    )


def claim_out(claim: Claim, direction: str) -> ClaimOut:
    first_name = (claim.claimant.name.split() or ["Someone"])[0]
    return ClaimOut(
        id=claim.id,
        direction=direction,  # type: ignore[arg-type]
        status=claim.status,
        message=claim.message,
        verification_detail=claim.verification_detail,
        claimant_name=first_name,
        item=item_brief(claim.item),
        lost_item=item_brief(claim.lost_item) if claim.lost_item else None,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
