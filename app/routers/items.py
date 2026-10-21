from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..constants import CATEGORIES, ITEM_TYPES
from ..deps import get_current_user, get_current_user_optional, get_db
from ..models import Claim, Item, Match, User
from ..schemas import ItemListOut, ItemOut, ItemUpdate
from ..serializers import item_out
from ..services.matching import index_and_match
from ..services.storage import ImageError, process_image, save_image

router = APIRouter(prefix="/items", tags=["items"])


def _opt_float(value: Optional[str], name: str, lo: float, hi: float) -> Optional[float]:
    if value is None or not str(value).strip():
        return None
    try:
        number = float(value)
    except ValueError:
        raise HTTPException(422, f"{name} must be a number") from None
    if not lo <= number <= hi:
        raise HTTPException(422, f"{name} must be between {lo} and {hi}")
    return number


def _clean(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value or None


@router.post("", response_model=ItemOut, status_code=201)
async def create_item(
    background: BackgroundTasks,
    type: str = Form(..., description="lost | found"),
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    location_text: str = Form(...),
    date_event: date = Form(...),
    lat: Optional[str] = Form(None),
    lng: Optional[str] = Form(None),
    distinguishing_features: Optional[str] = Form(None),
    private_detail: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Report a lost or found item. Embeddings + matching run in the background after the response."""
    title, description, location_text = title.strip(), description.strip(), location_text.strip()
    if type not in ITEM_TYPES:
        raise HTTPException(422, "type must be 'lost' or 'found'")
    if category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of: {', '.join(CATEGORIES)}")
    if not 2 <= len(title) <= 120:
        raise HTTPException(422, "Item name must be 2-120 characters")
    if len(description) < 10:
        raise HTTPException(422, "Please add a more detailed description (at least 10 characters)")
    if len(location_text) < 2:
        raise HTTPException(422, "Please tell us where it was lost or found")
    if date_event > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise HTTPException(422, "The date can't be in the future")

    processed: Optional[bytes] = None
    image_url: Optional[str] = None
    if image is not None and image.filename:
        raw = await image.read()
        if raw:
            try:
                processed = process_image(raw)
            except ImageError as exc:
                raise HTTPException(422, str(exc)) from None
            image_url = save_image(processed)

    item = Item(
        user_id=user.id,
        type=type,
        title=title,
        description=description,
        category=category,
        image_url=image_url,
        location_text=location_text,
        lat=_opt_float(lat, "lat", -90, 90),
        lng=_opt_float(lng, "lng", -180, 180),
        date_event=date_event,
        distinguishing_features=_clean(distinguishing_features),
        private_detail=_clean(private_detail),
    )
    db.add(item)
    db.commit()

    background.add_task(index_and_match, item.id, processed)
    return item_out(item, user)


@router.get("", response_model=ItemListOut)
def list_items(
    q: Optional[str] = Query(None, description="Search item name, description and distinguishing features"),
    type: Optional[str] = Query(None, pattern="^(lost|found)$"),
    category: Optional[str] = None,
    location: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    stmt = select(Item)
    if q:
        for word in q.lower().split():  # every word must appear somewhere
            stmt = stmt.where(
                or_(
                    func.lower(Item.title).contains(word, autoescape=True),
                    func.lower(Item.description).contains(word, autoescape=True),
                    func.lower(func.coalesce(Item.distinguishing_features, "")).contains(word, autoescape=True),
                )
            )
    if type:
        stmt = stmt.where(Item.type == type)
    if category:
        stmt = stmt.where(Item.category == category)
    if location:
        stmt = stmt.where(func.lower(Item.location_text).contains(location.lower().strip(), autoescape=True))
    if date_from:
        stmt = stmt.where(Item.date_event >= date_from)
    if date_to:
        stmt = stmt.where(Item.date_event <= date_to)
    if status:
        stmt = stmt.where(Item.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Item.created_at.desc(), Item.id.desc()).limit(limit).offset(offset)).all()
    return ItemListOut(items=[item_out(i, user) for i in rows], total=total, limit=limit, offset=offset)


@router.get("/mine", response_model=list[ItemOut])
def my_items(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Item).where(Item.user_id == user.id).order_by(Item.created_at.desc(), Item.id.desc())
    ).all()
    return [item_out(i, user) for i in rows]


def _get_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    return item


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user_optional)):
    return item_out(_get_item(db, item_id), user)


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(
    item_id: int,
    body: ItemUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item(db, item_id)
    if item.user_id != user.id:
        raise HTTPException(403, "You can only edit your own reports")
    changes = body.model_dump(exclude_unset=True)
    text_changed = any(k in changes for k in ("title", "description", "distinguishing_features"))
    for field, value in changes.items():
        if field in ("distinguishing_features", "private_detail"):
            value = _clean(value)
        setattr(item, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    if text_changed:
        background.add_task(index_and_match, item.id, None, True)  # keep the stored image vector
    return item_out(item, user)


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = _get_item(db, item_id)
    if item.user_id != user.id:
        raise HTTPException(403, "You can only delete your own reports")
    db.execute(delete(Match).where(or_(Match.lost_item_id == item.id, Match.found_item_id == item.id)))
    db.execute(delete(Claim).where(or_(Claim.item_id == item.id, Claim.lost_item_id == item.id)))
    db.delete(item)
    db.commit()
