"""Shared constants (kept dependency-free so models/services/routers can all import it)."""

TEXT_DIM = 384   # SentenceTransformer all-MiniLM-L6-v2
IMAGE_DIM = 512  # CLIP ViT-B/32

ITEM_TYPES = ("lost", "found")
ITEM_STATUSES = ("open", "claim_pending", "returned", "closed")
OPEN_STATUSES = ("open", "claim_pending")
CLAIM_STATUSES = ("pending", "approved", "rejected", "withdrawn")

CATEGORIES = {
    "bags": "Bags & Backpacks",
    "electronics": "Electronics",
    "wallets": "Wallets & Purses",
    "keys": "Keys",
    "bottles": "Bottles & Lunch Boxes",
    "id_cards": "ID Cards & Documents",
    "umbrellas": "Umbrellas",
    "stationery": "Books & Stationery",
    "eyewear": "Spectacles & Eyewear",
    "clothing": "Clothing & Accessories",
    "jewelry": "Jewellery & Watches",
    "other": "Other",
}
