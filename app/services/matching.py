"""Matching service: weighted cosine similarity between a lost and a found report.

    overall = image_weight * image_similarity + text_weight * description_similarity     (default 60/40)

Hard filters run first (opposite type, open status, different owner, date window, category,
geographic radius when coordinates exist). Location and date are reported as compatibility
signals next to the score instead of being folded into it.
"""

import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..constants import OPEN_STATUSES
from ..database import SessionLocal
from ..models import Item, ItemEmbedding, Match
from .embeddings import build_item_text, canonical_tokens, get_embedder

log = logging.getLogger("findit.matching")

_GENERIC_WORDS = {"item", "thing", "found", "lost", "area", "report", "one", "small", "large"}


@dataclass
class PairScore:
    image_score: Optional[float]
    text_score: float
    location_score: Optional[float]
    location_label: str
    days_apart: int
    final_score: float
    explanation: str


# ---------- math helpers ----------
def cosine(a: Optional[list[float]], b: Optional[list[float]]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def calibrate(sim: float, floor: float) -> float:
    """Rescale a raw cosine from [floor, 1] to [0, 1]."""
    if floor >= 1:
        return 0.0
    return max(0.0, min(1.0, (sim - floor) / (1 - floor)))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------- location ----------
def assess_location(a: Item, b: Item) -> Optional[tuple[Optional[float], str]]:
    """Return (score 0-100 or None, label), or None when the two spots are too far apart to match."""
    if None not in (a.lat, a.lng, b.lat, b.lng):
        km = haversine_km(a.lat, a.lng, b.lat, b.lng)  # type: ignore[arg-type]
        if km > settings.match_radius_km * 3:
            return None
        score = max(0.0, 1 - km / settings.match_radius_km) * 100
        label = "Same spot" if km <= 0.15 else "Nearby" if km <= settings.match_radius_km else "Farther away"
        return round(score, 1), label

    ta, tb = set(canonical_tokens(a.location_text)), set(canonical_tokens(b.location_text))
    if not ta or not tb:
        return None, "Unknown"
    overlap = len(ta & tb) / min(len(ta), len(tb))
    label = "Same area" if overlap >= 0.6 else "Possibly nearby" if overlap >= 0.25 else "Different area"
    return round(overlap * 100, 1), label


# ---------- explanation ----------
def _item_tokens(item: Item) -> set[str]:
    text = f"{item.title} {item.description} {item.distinguishing_features or ''}"
    return {t for t in canonical_tokens(text) if t not in _GENERIC_WORDS and len(t) > 2}


def _explain(
    lost: Item, found: Item, image: Optional[float], text: float, loc_label: str, days: int
) -> str:
    parts: list[str] = []
    shared = sorted(_item_tokens(lost) & _item_tokens(found))
    if shared:
        parts.append("Both reports mention " + ", ".join(shared[:5]))
    if lost.category == found.category and lost.category != "other":
        parts.append("same category")
    if image is not None:
        level = "very similar" if image >= 75 else "somewhat similar" if image >= 50 else "only loosely similar"
        parts.append(f"photos look {level}")
    if text >= 70:
        parts.append("descriptions are closely aligned")
    elif text >= 40:
        parts.append("descriptions partly overlap")
    if loc_label not in ("Unknown", "Different area"):
        parts.append(f"location: {loc_label.lower()}")
    parts.append("reported the same day" if days == 0 else f"reported {days} day{'s' if days != 1 else ''} apart")
    sentence = "; ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


# ---------- scoring ----------
def score_pair(
    lost: Item, found: Item, lost_emb: ItemEmbedding, found_emb: ItemEmbedding
) -> Optional[PairScore]:
    delta = (found.date_event - lost.date_event).days
    if delta < -1 or delta > settings.match_window_days:  # can't be found before it was lost
        return None
    if lost.category != found.category and "other" not in (lost.category, found.category):
        return None
    location = assess_location(lost, found)
    if location is None:
        return None
    loc_score, loc_label = location

    text_sim = calibrate(cosine(lost_emb.text_vec, found_emb.text_vec), settings.text_sim_floor) * 100
    image_sim: Optional[float] = None
    if lost_emb.image_vec and found_emb.image_vec:
        image_sim = calibrate(cosine(lost_emb.image_vec, found_emb.image_vec), settings.image_sim_floor) * 100

    if image_sim is None:  # at least one report has no photo: fall back to description only
        final = text_sim
    else:
        wi, wt = settings.image_weight, settings.text_weight
        final = (wi * image_sim + wt * text_sim) / (wi + wt)

    days = abs(delta)
    return PairScore(
        image_score=round(image_sim, 1) if image_sim is not None else None,
        text_score=round(text_sim, 1),
        location_score=loc_score,
        location_label=loc_label,
        days_apart=days,
        final_score=round(final, 1),
        explanation=_explain(lost, found, image_sim, text_sim, loc_label, days),
    )


# ---------- persistence ----------
def upsert_embedding(db: Session, item: Item, image_bytes: Optional[bytes]) -> ItemEmbedding:
    """(Re)compute and store an item's embeddings. Without new image bytes an existing image vector is kept."""
    embedder = get_embedder()
    text_vec = embedder.embed_text(build_item_text(item.title, item.category, item.description, item.distinguishing_features))
    image_vec = embedder.embed_image(image_bytes) if image_bytes else None

    row = db.get(ItemEmbedding, item.id)
    if row is None:
        row = ItemEmbedding(item_id=item.id, backend=embedder.name)
        db.add(row)
    row.text_vec = text_vec
    if image_vec is not None or row.backend != embedder.name:
        row.image_vec = image_vec
    row.backend = embedder.name
    db.commit()
    return row


def find_matches(db: Session, item: Item) -> list[Match]:
    """Score `item` against every eligible opposite report and store the matches above the threshold."""
    embedder = get_embedder()
    own = db.get(ItemEmbedding, item.id)
    if own is None or own.backend != embedder.name:
        return []

    window = timedelta(days=settings.match_window_days)
    opposite = "found" if item.type == "lost" else "lost"
    candidates = db.execute(
        select(Item, ItemEmbedding)
        .join(ItemEmbedding, ItemEmbedding.item_id == Item.id)
        .where(
            Item.type == opposite,
            Item.status.in_(OPEN_STATUSES),
            Item.id != item.id,
            Item.user_id != item.user_id,
            ItemEmbedding.backend == embedder.name,
            Item.date_event.between(item.date_event - window, item.date_event + window),
        )
    ).all()

    existing = {
        (m.lost_item_id, m.found_item_id): m
        for m in db.scalars(
            select(Match).where(or_(Match.lost_item_id == item.id, Match.found_item_id == item.id))
        )
    }

    keep: set[tuple[int, int]] = set()
    results: list[Match] = []
    for other, other_emb in candidates:
        lost, lost_emb, found, found_emb = (
            (item, own, other, other_emb) if item.type == "lost" else (other, other_emb, item, own)
        )
        scored = score_pair(lost, found, lost_emb, found_emb)
        if scored is None or scored.final_score < settings.min_match_score:
            continue
        key = (lost.id, found.id)
        keep.add(key)
        match = existing.get(key)
        if match is None:
            match = Match(lost_item_id=lost.id, found_item_id=found.id)
            db.add(match)
        elif match.status == "dismissed":
            continue
        match.image_score = scored.image_score
        match.text_score = scored.text_score
        match.location_score = scored.location_score
        match.location_label = scored.location_label
        match.days_apart = scored.days_apart
        match.final_score = scored.final_score
        match.explanation = scored.explanation
        results.append(match)

    for key, match in existing.items():  # drop suggestions that no longer qualify
        if key not in keep and match.status == "suggested":
            db.delete(match)

    db.commit()
    return sorted(results, key=lambda m: m.final_score, reverse=True)


def load_matches(db: Session, item: Item) -> list[Match]:
    stmt = (
        select(Match)
        .options(joinedload(Match.lost_item), joinedload(Match.found_item))
        .where(or_(Match.lost_item_id == item.id, Match.found_item_id == item.id), Match.status != "dismissed")
        .order_by(Match.final_score.desc())
    )
    return list(db.scalars(stmt).unique())


# ---------- background entry points ----------
def index_and_match(item_id: int, image_bytes: Optional[bytes] = None, text_only: bool = False) -> None:
    """Runs after the HTTP response (FastAPI BackgroundTasks) so uploads return immediately."""
    try:
        with SessionLocal() as db:
            item = db.get(Item, item_id)
            if item is None:
                return
            upsert_embedding(db, item, None if text_only else image_bytes)
            find_matches(db, item)
    except Exception:  # never let a model failure break the request lifecycle
        log.exception("Indexing/matching failed for item %s", item_id)
