from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Auth ----------
class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Items ----------
class ItemBrief(BaseModel):
    id: int
    type: str
    title: str
    category: str
    image_url: Optional[str] = None
    status: str


class ItemOut(ItemBrief):
    description: str
    location_text: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    date_event: date
    distinguishing_features: Optional[str] = None
    # Only populated for the owner of the report.
    private_detail: Optional[str] = None
    created_at: datetime
    is_mine: bool = False


class ItemListOut(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


class ItemUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = Field(None, min_length=10)
    distinguishing_features: Optional[str] = None
    private_detail: Optional[str] = None
    status: Optional[Literal["open", "returned", "closed"]] = None


# ---------- Matches ----------
class MatchOut(BaseModel):
    id: int
    final_score: float
    image_score: Optional[float] = None
    text_score: float
    location_score: Optional[float] = None
    location_label: str
    days_apart: int
    explanation: str
    status: str
    created_at: datetime
    lost_item: ItemOut
    found_item: ItemOut
    # The report on the other side of the match, relative to the item that was requested.
    other_item: Optional[ItemOut] = None


class ScoringInfo(BaseModel):
    image_weight: float
    text_weight: float
    embedding_backend: str
    is_simulated: bool
    formula: str


class MatchListOut(BaseModel):
    item: ItemBrief
    indexing: bool = False
    scoring: ScoringInfo
    matches: list[MatchOut]


# ---------- Claims ----------
class ClaimCreate(BaseModel):
    item_id: int
    lost_item_id: Optional[int] = None
    message: str = Field(min_length=10, max_length=1000)
    verification_detail: Optional[str] = Field(None, max_length=500)


class ClaimStatusUpdate(BaseModel):
    status: Literal["approved", "rejected", "withdrawn"]


class ClaimOut(BaseModel):
    id: int
    direction: Literal["made", "received"]
    status: str
    message: str
    verification_detail: Optional[str] = None
    claimant_name: str
    item: ItemBrief
    lost_item: Optional[ItemBrief] = None
    created_at: datetime
    updated_at: datetime


# ---------- Dashboard ----------
class ActivityOut(BaseModel):
    kind: Literal["report", "match", "claim_made", "claim_received"]
    message: str
    at: datetime
    item_id: Optional[int] = None


class GlobalStats(BaseModel):
    total_items: int
    lost_items: int
    found_items: int
    potential_matches: int
    reunited_items: int


class MyStats(BaseModel):
    reports: int
    lost_reports: int
    found_reports: int
    potential_matches: int
    claims_made: dict[str, int]
    claims_received: dict[str, int]


class DashboardOut(BaseModel):
    stats: GlobalStats
    mine: MyStats
    my_reports: list[ItemOut]
    recent_activity: list[ActivityOut]
